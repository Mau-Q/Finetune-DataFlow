"""Identity-bound lightweight results, immutable terminals and artifact-bound evaluation."""
from app.services.model_training import training_transaction
from app.services.dataset_persistence import atomic_write
import copy
import json
from pathlib import Path
import re
from app.services.model_training import TrainingError, canonical, digest

TERMINAL={'completed','failed','stopped'}
ACTIVE={'preflight','running','queued'}
MAX_RESULT=10*1024*1024


def load_result(service, record):
    p=service.root/'results'/(record['content_sha256']+'.json')
    if not p.is_file() or digest(p.read_bytes())!=record['content_sha256']:raise TrainingError('结果文件缺失或损坏',503)
    return json.loads(p.read_bytes())


@training_transaction
def import_result(service, payload):
    try:blob=canonical(payload)
    except (ValueError,TypeError) as e:raise TrainingError('结果包含非法 JSON 数值') from e
    if len(blob)>MAX_RESULT:raise TrainingError('轻量结果超过 10 MiB')
    required=['schema_version','run_id','attempt_id','input_manifest_sha256','sequence','synthetic','status','metrics','artifacts','environment','actual_config']
    if any(k not in payload for k in required) or payload['schema_version']!=1:raise TrainingError('结果包 v1 字段不完整')
    if any(not isinstance(payload[k],str) or not re.fullmatch('[a-zA-Z0-9_-]{1,80}',payload[k]) for k in ['run_id','attempt_id']):raise TrainingError('run/attempt ID 无效')
    if type(payload['sequence']) is not int or payload['sequence']<0 or type(payload['synthetic']) is not bool or payload['status'] not in TERMINAL|ACTIVE:raise TrainingError('结果序号/状态/合成标记无效')
    if not isinstance(payload['metrics'],list) or not isinstance(payload.get('strategy_metrics',[]),list) or not isinstance(payload['artifacts'],list):raise TrainingError('指标/产物必须为列表')
    for key in ['metrics','strategy_metrics']:
        if any(not isinstance(r,dict) for r in payload.get(key,[])):raise TrainingError('每条指标必须为对象')
    if not isinstance(payload['actual_config'],dict) or not isinstance(payload['environment'],dict) or not isinstance(payload.get('log',''),str):raise TrainingError('配置/环境需要对象，日志需要字符串')
    artifacts=payload['artifacts']
    if any(not isinstance(a,dict) or not a.get('id') or not re.fullmatch('[0-9a-f]{64}',a.get('sha256','')) or a.get('availability') not in ['remote_registered','local_verified'] for a in artifacts):raise TrainingError('产物需要 ID、哈希和位置状态')
    if len({a['id'] for a in artifacts})!=len(artifacts):raise TrainingError('产物 ID 重复')
    # Imports never certify a user supplied local download location.
    for a in artifacts:
        if a.get('availability')=='local_verified':raise TrainingError('导入包只能登记远程产物，下载需独立核验')
    bundles=[b for b in service.list('bundles') if b['manifest_sha256']==payload['input_manifest_sha256']]
    if not bundles:raise TrainingError('输入清单身份未登记；请先导入/生成对应运行包',409)
    bundle=bundles[0];attempt=payload['attempt_id'];existing=next((r for r in service.list('runs') if r['id']==attempt),None)
    h=digest(blob)
    if existing:
        if existing['content_sha256']==h:return dict(existing,idempotent=True)
        old=load_result(service,existing)
        if old['status'] in TERMINAL:raise TrainingError('终态结果已封存，拒绝覆盖',409)
        for key in ['run_id','attempt_id','input_manifest_sha256','synthetic']:
            if old[key]!=payload[key]:raise TrainingError('结果身份冲突',409)
        if payload['sequence']<=old['sequence']:raise TrainingError('结果序号回退或冲突',409)
        for key in ['metrics','strategy_metrics']:
            previous=old.get(key,[]);current=payload.get(key,[])
            if current[:len(previous)]!=previous:raise TrainingError('已有指标不能被改写',409)
        for a in old['artifacts']:
            if a not in payload['artifacts']:raise TrainingError('已有产物身份不能被改写',409)
    # Same run cannot refer to unrelated inputs or switch fixture provenance across attempts.
    for r in service.list('runs'):
        if r['run_id']==payload['run_id'] and (r['manifest_sha256']!=payload['input_manifest_sha256'] or r['synthetic']!=payload['synthetic']):raise TrainingError('运行身份冲突',409)
    directory=service.root/'results';directory.mkdir(exist_ok=True)
    atomic_write(directory/(h+'.json'),blob)
    return service.put('runs',{'run_id':payload['run_id'],'bundle_id':bundle['id'],'plan_snapshot':bundle['plan_snapshot'],'source':bundle['manifest']['source'],'manifest_sha256':payload['input_manifest_sha256'],'synthetic':payload['synthetic'],'sequence':payload['sequence'],'status':payload['status'],'content_sha256':h},attempt,existing['version'] if existing else None)


def run_detail(service,attempt):
    r=service.get('runs',attempt)
    return dict(r,result=load_result(service,r),evaluations=[e for e in service.list('evaluations') if e['attempt_id']==attempt])


@training_transaction
def add_evaluation(service,payload):
    fields=['attempt_id','artifact_id','artifact_sha256','task','dataset_version','metric_definitions','metrics','tool_version','config']
    if any(not payload.get(k) for k in fields):raise TrainingError('评测需绑定运行、产物、任务、数据版本、指标定义、工具与配置')
    result=run_detail(service,payload['attempt_id'])['result']
    artifact=next((a for a in result['artifacts'] if a['id']==payload['artifact_id'] and a['sha256']==payload['artifact_sha256']),None)
    if not artifact:raise TrainingError('评测产物与运行记录不匹配',409)
    payload=copy.deepcopy(payload);payload['synthetic']=result['synthetic'];payload['artifact_identity_scope']=artifact.get('identity_scope','unspecified')
    payload['config_sha256']=digest(canonical(payload['config']))
    key=digest(canonical(payload))
    existing=next((e for e in service.list('evaluations') if e['id']==key),None)
    return existing or service.put('evaluations',payload,key)


def compare(service, attempts, include_synthetic=False):
    records=[run_detail(service,k) for k in attempts]
    records=[r for r in records if include_synthetic or not r['synthetic']]
    fields=['model','model_revision','tokenizer','task','modality','finetuning_type','max_steps','batch_size','gradient_accumulation_steps','seed','data','strategy','advanced']
    conditions={k:[r['plan_snapshot'].get(k) for r in records] for k in fields}
    conditions['source']=[r['source'] for r in records];conditions['input_manifest_sha256']=[r['manifest_sha256'] for r in records]
    differences=[k for k,v in conditions.items() if len({canonical(x) for x in v})>1]
    return {'runs':records,'conditions':conditions,'differences':differences,'basis':'step / batch；相同步数不代表相同 token、时间或策略成本','missing':'未采集指标不估算；策略参考集指标不是独立评测'}
