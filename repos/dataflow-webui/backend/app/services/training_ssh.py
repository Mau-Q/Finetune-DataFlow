"""One fixed SSH target. System authentication and strict known_hosts are mandatory."""
from contextlib import contextmanager
import base64
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import uuid
from app.services.model_training import TrainingError,canonical,digest,now
from app.services.training_results import import_result,load_result
from app.services.platform_lock import exclusive_lock


def validate_host(body):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,100}',body.get('alias','')):raise TrainingError('SSH alias 无效（使用系统 SSH config 别名）')
    for key in ['workdir','python']:
        value=body.get(key,'')
        if not re.fullmatch(r'/[A-Za-z0-9_./-]+',value) or '..' in Path(value).parts or value in ['/','/tmp','/home','/root']:raise TrainingError(key+': 需要明确的绝对路径，仅支持字母数字及 _ . / -')
    if not re.fullmatch(r'[0-9]+(?:,[0-9]+)*',body.get('gpus','0')):raise TrainingError('GPU 配置需要编号列表')
    return {k:body.get(k,'0') for k in ['alias','workdir','python','gpus']}


class SSHTransport:
    def __init__(self,host):self.host=validate_host(host)
    def execute(self,code,*args):
        command=shlex.join([self.host['python'],'-c',code,*map(str,args)])
        try:
            r=subprocess.run(['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=10',self.host['alias'],command],capture_output=True,text=True,encoding='utf-8',timeout=90)
        except (OSError,subprocess.TimeoutExpired) as e:raise TrainingError('SSH 连接未完成，运行状态未知',503) from e
        if r.returncode:raise TrainingError('SSH 操作失败: '+r.stderr[-1500:],503 if r.returncode==255 else 409)
        try:return json.loads(r.stdout)
        except ValueError as e:raise TrainingError('SSH 返回非 JSON 状态',502) from e
    def upload(self,path,remote):
        if not re.fullmatch(r'/[A-Za-z0-9_./-]+',remote):raise TrainingError('上传路径无效')
        # Local path is escaped for SFTP batch syntax; credentials never enter the command.
        local='"'+str(Path(path).resolve()).replace('\\','\\\\').replace('"','\\"')+'"'
        try:
            r=subprocess.run(['sftp','-b','-','-oBatchMode=yes','-oStrictHostKeyChecking=yes','-oConnectTimeout=10',self.host['alias']],input='put '+local+' '+remote+'\n',text=True,capture_output=True,timeout=120)
        except (OSError,subprocess.TimeoutExpired) as e:raise TrainingError('SFTP 上传未完成',503) from e
        if r.returncode:raise TrainingError('SFTP 上传失败: '+r.stderr[-1000:],503)


@contextmanager
def control_lock(service):
    with (service.root/'.ssh.lock').open('a+') as lock:
        with exclusive_lock(lock):
            yield


def host_config(service):
    records=service.list('host')
    return records[0] if records else None


def save_host(service,body):
    host=validate_host(body)
    with control_lock(service):
        if any(c['phase'] not in ['completed','failed','stopped'] for c in service.list('controls')):raise TrainingError('尚有未确认结束的运行，请先同步/停止再更改主机',409)
        previous=host_config(service)
        return service.put('host',{'config':host},'active',previous['version'] if previous else None)


def transport_for(service, factory):
    host=host_config(service)
    if not host:raise TrainingError('未配置固定训练主机；保存和导出仍可使用',409)
    return factory(host['config']),host['config']


def probe(service,factory=SSHTransport):
    transport,host=transport_for(service,factory)
    return transport.execute(PROBE)


def start(service,bundle_id,request_id,factory=SSHTransport):
    if not isinstance(request_id,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{8,80}',request_id):raise TrainingError('需要稳定的启动幂等标识')
    attempt=digest(canonical([bundle_id,request_id]))[:32]
    with control_lock(service):
        existing=next((c for c in service.list('controls') if c['id']==attempt),None)
        if existing:return dict(existing,idempotent=True)
        if any(c['phase'] not in ['completed','failed','stopped'] for c in service.list('controls')):raise TrainingError('已有训练任务或状态待确认；先同步或停止',409)
        transport,host=transport_for(service,factory);bundle=service.get('bundles',bundle_id)
        path=Path(bundle['path'])
        if not path.is_file() or digest(path.read_bytes())!=bundle['archive_sha256']:raise TrainingError('本地运行包校验失败',409)
        if any(b['kind']!='file' for b in bundle['manifest']['external_references']):raise TrainingError('HF 数据引用尚未物化；请先固定数据并生成可执行包')
        directory=host['workdir'].rstrip('/')+'/runs/'+attempt
        control=service.put('controls',{'bundle_id':bundle_id,'attempt_id':attempt,'run_id':uuid.uuid4().hex,'phase':'uploading','connection':'connected','host':host,'directory':directory,'manifest_sha256':bundle['manifest_sha256'],'last_observed_at':now()},attempt)
        try:
            transport.execute(MKDIR,directory)
            transport.upload(path,directory+'/input.zip')
            transport.execute(PUBLISH,directory,bundle['archive_sha256'],bundle['manifest_sha256'])
            transport.execute(PREFLIGHT,directory,host['python'])
            state=transport.execute(START,directory,host['python'],control['run_id'],attempt,bundle['manifest_sha256'],host['gpus'])
            control.update(phase='starting',remote=state)
        except TrainingError as e:
            # A transport failure can occur after remote start. Do not mark an unknown process failed.
            control.update(connection='disconnected',error=str(e),phase='unknown')
        return service.put('controls',control,attempt,control['version'])


def sync(service,attempt,stop=False,factory=SSHTransport):
    with control_lock(service):
        control=service.get('controls',attempt);transport=factory(control['host'])
        try:
            if stop:transport.execute(STOP,control['directory'],control['host']['python'],attempt)
            previous_record=next((r for r in service.list('runs') if r['id']==attempt),None)
            previous=load_result(service,previous_record) if previous_record else None
            state=transport.execute(STATUS,control['directory'],len(previous.get('metrics',[])) if previous else 0,len(previous.get('strategy_metrics',[])) if previous else 0,previous.get('log_end_offset',-1) if previous else -1)
            if state.get('delta'):state['result']=merge_delta(previous,state['result'],state['delta'])
            control.update(connection='connected',last_observed_at=now(),error='')
            result=state.get('result')
            if result:
                if result['attempt_id']!=attempt or result['run_id']!=control['run_id'] or result['input_manifest_sha256']!=control['manifest_sha256']:raise TrainingError('远程结果身份冲突',409)
                imported=import_result(service,result);control.update(phase=imported['status'],sequence=imported['sequence'])
                if state.get('process_alive') is False and imported['status'] not in ['completed','failed','stopped']:
                    control.update(phase='unknown',error='runner 身份不再匹配，训练子进程退出尚未确认；需要核对远端记录')
            elif state.get('process'):
                control['phase']='starting'
            else:
                # No process record after interrupted staging: safe to close this attempt without signalling anything.
                control['phase']='failed';control['error']='远端没有进程记录；本次准备未完成，可用新 attempt 重试'
        except TrainingError as e:
            control.update(connection='disconnected' if e.status==503 else 'connected',error=str(e))
        return service.put('controls',control,attempt,control['version'])

PROBE="""import json,importlib.metadata as m,sys,os
versions={}
for name in ['torch','transformers','llamafactory','datasets','omegaconf']:
 try:versions[name]=m.version(name)
 except m.PackageNotFoundError:versions[name]=None
gpu={'available':False}
if versions.get('torch'):
 import torch
 gpu={'available':torch.cuda.is_available(),'cuda':torch.version.cuda,'device_count':torch.cuda.device_count()}
print(json.dumps({'python':sys.version,'platform':sys.platform,'versions':versions,'gpu':gpu,'environment_checked':True,'ready':all(versions.values()) and gpu['available'],'gpu_training':'NOT_RUN'}))
"""
MKDIR="""import pathlib,sys,json
p=pathlib.Path(sys.argv[1]);p.mkdir(parents=True,exist_ok=True)
if p.is_symlink():raise ValueError('Symlink run directory')
print(json.dumps({'staging':str(p)}))
"""
PUBLISH="""import sys,pathlib,hashlib,zipfile,stat,json,os
root=pathlib.Path(sys.argv[1]);archive=root/'input.zip'
if hashlib.sha256(archive.read_bytes()).hexdigest()!=sys.argv[2]:raise ValueError('Upload hash mismatch')
with zipfile.ZipFile(archive) as z:
 names=z.namelist()
 if len(names)!=len(set(names)) or sum(i.file_size for i in z.infolist())>536870912:raise ValueError('Invalid size/members')
 for i in z.infolist():
  p=pathlib.PurePosixPath(i.filename)
  if p.is_absolute() or '..' in p.parts or '\\\\' in i.filename or stat.S_ISLNK(i.external_attr>>16):raise ValueError('Unsafe member')
 if hashlib.sha256(z.read('manifest.json')).hexdigest()!=sys.argv[3]:raise ValueError('Manifest mismatch')
 manifest=json.loads(z.read('manifest.json'))
 if set(names)!=set(manifest['files'])|{'manifest.json'}:raise ValueError('Unmanifested member')
 for name,h in manifest['files'].items():
  if hashlib.sha256(z.read(name)).hexdigest()!=h:raise ValueError('Member hash mismatch')
 dest=root/'ready'
 if dest.exists():
  if hashlib.sha256((dest/'manifest.json').read_bytes()).hexdigest()!=sys.argv[3]:raise ValueError('Existing input conflict')
 else:
  staging=root/'staging';staging.mkdir(exist_ok=False);z.extractall(staging);os.rename(staging,dest)
print(json.dumps({'verified':True}))
"""
PREFLIGHT="""import subprocess,sys,json,pathlib
root=pathlib.Path(sys.argv[1])/'ready'
r=subprocess.run([sys.argv[2],str(root/'runner.py'),'preflight'],cwd=root,capture_output=True,text=True)
if r.returncode:raise ValueError(r.stderr[-1500:])
print(r.stdout)
"""
START="""import pathlib,sys,subprocess,os,json
root=pathlib.Path(sys.argv[1])/'ready'
if (root/'process.json').exists():print((root/'process.json').read_text(encoding='utf-8'))
else:
 env=os.environ.copy();env['CUDA_VISIBLE_DEVICES']=sys.argv[6]
 with (root/'runner.log').open('ab') as log:
  p=subprocess.Popen([sys.argv[2],str(root/'runner.py'),'run','--run-id',sys.argv[3],'--attempt',sys.argv[4],'--manifest',sys.argv[5]],cwd=root,stdout=log,stderr=log,start_new_session=True,env=env)
 print(json.dumps({'pid':p.pid,'attempt_id':sys.argv[4]}))
"""
STATUS="""import pathlib,sys,json,hashlib,base64
root=pathlib.Path(sys.argv[1])/'ready'
state={k:json.loads((root/(k+'.json')).read_text(encoding='utf-8')) if (root/(k+'.json')).exists() else None for k in ['process','result']}
if state['process']:
 try:
  import importlib.util
  spec=importlib.util.spec_from_file_location('dataflex_runner',root/'runner.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  state['process_alive']=module.identity(state['process']['pid'])==state['process']['identity']
 except Exception:state['process_alive']=False
r=state['result'];mc=int(sys.argv[2]);sc=int(sys.argv[3]);offset=int(sys.argv[4])
if r and mc<=len(r.get('metrics',[])) and sc<=len(r.get('strategy_metrics',[])):
 def h(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()).hexdigest()
 delta={'metrics_base':mc,'strategy_base':sc,'metrics_sha256':h(r.get('metrics',[])[:mc]),'strategy_sha256':h(r.get('strategy_metrics',[])[:sc]),'log_append':False}
 r['metrics']=r.get('metrics',[])[mc:];r['strategy_metrics']=r.get('strategy_metrics',[])[sc:]
 if r.get('log_base64') and r.get('log_start_offset',0)<=offset<=r.get('log_end_offset',0):
  raw=base64.b64decode(r['log_base64']);raw=raw[offset-r.get('log_start_offset',0):]
  r['log_base64']=base64.b64encode(raw).decode();r.pop('log',None);delta['log_append']=True;delta['log_base_offset']=offset
 state['delta']=delta
print(json.dumps(state))
"""


def merge_delta(previous,result,delta):
    previous=previous or {'metrics':[],'strategy_metrics':[]}
    for key,count,hashkey in [('metrics','metrics_base','metrics_sha256'),('strategy_metrics','strategy_base','strategy_sha256')]:
        values=previous.get(key,[])
        if len(values)!=delta[count] or digest(canonical(values))!=delta[hashkey]:raise TrainingError('远程指标前缀与已保存结果冲突',409)
        result[key]=values+result.get(key,[])
    if delta.get('log_append'):
        if previous.get('log_end_offset')!=delta['log_base_offset']:raise TrainingError('远程日志偏移冲突',409)
        raw=(base64.b64decode(previous.get('log_base64',''))+base64.b64decode(result['log_base64']))[-1024*1024:]
        result['log_base64']=base64.b64encode(raw).decode();result['log']=raw.decode(errors='replace');result['log_start_offset']=result['log_end_offset']-len(raw)
    return result

STOP="""import pathlib,sys,subprocess
root=pathlib.Path(sys.argv[1])/'ready'
r=subprocess.run([sys.argv[2],str(root/'runner.py'),'stop','--attempt',sys.argv[3]],cwd=root,capture_output=True,text=True)
if r.returncode:raise ValueError(r.stderr[-1500:])
print(r.stdout)
"""
