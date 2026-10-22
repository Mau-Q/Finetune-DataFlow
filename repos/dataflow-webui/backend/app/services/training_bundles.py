"""Portable immutable run inputs. Export never creates a training run."""
from app.services.model_training import training_transaction
from app.services.dataset_persistence import atomic_write
import copy
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tempfile
import uuid
import zipfile
import yaml
from app.services.model_training import TrainingError, canonical, digest
from app.services.training_compiler import compile_plan, catalog

MAX_FILE=100*1024*1024
MAX_BUNDLE=512*1024*1024


def safe_read(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file():raise TrainingError('输入必须是普通文件，不接受符号链接: '+str(path))
    if path.stat().st_size>MAX_FILE:raise TrainingError('输入过大，请使用显式引用模式')
    return path.read_bytes()


def safe_members(blob):
    try:
        archive=zipfile.ZipFile(io.BytesIO(blob));names=archive.namelist()
        if len(names)!=len(set(names)) or sum(i.file_size for i in archive.infolist())>MAX_BUNDLE:raise TrainingError('包重复成员或解压大小超限')
        result={}
        for info in archive.infolist():
            p=PurePosixPath(info.filename)
            if p.is_absolute() or '..' in p.parts or '\\' in info.filename or stat.S_ISLNK(info.external_attr>>16):raise TrainingError('包包含不安全路径或符号链接')
            if not info.is_dir():result[info.filename]=archive.read(info)
        return result
    except zipfile.BadZipFile as e:raise TrainingError('无效 ZIP 包') from e


def snapshot_source(root, custom_files):
    root=Path(root)
    try:
        commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
        dirty=bool(subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=root))
        tracked=subprocess.check_output(['git','ls-files','-z','src/dataflex','pyproject.toml','setup.py','requirements.txt'],cwd=root).decode().split('\0')
    except (OSError,subprocess.CalledProcessError) as e:raise TrainingError('DataFlex 源码目录不可用，请设置 DATAFLEX_SOURCE_DIR') from e
    files={}
    if not isinstance(custom_files,list) or not all(isinstance(x,str) for x in custom_files):raise TrainingError('custom_sources 必须为源码相对路径列表')
    for name in [*filter(None,tracked),*custom_files]:
        p=PurePosixPath(name)
        if p.is_absolute() or '..' in p.parts or not (name.startswith('src/dataflex/') or name in ['pyproject.toml','setup.py','requirements.txt']):raise TrainingError('自定义源码必须显式位于 src/dataflex 下')
        path=root/name
        if not path.resolve().is_relative_to(root.resolve()):raise TrainingError('源码路径越界')
        if path.suffix not in ['.py','.yaml','.yml','.toml','.txt']:continue
        content=safe_read(path)
        # Fail closed on literal credential assignments, without echoing any value.
        if re.search(rb'(?im)^\s*(?:[\w]*api[_-]?key|[\w]*secret|[\w]*password|[\w]*token)\s*[:=]\s*[\'"][^\'"\s]{8,}[\'"]',content):raise TrainingError('源码包含疑似凭据字面值，请移除后重试')
        files['source/'+name]=content
    if 'source/src/dataflex/cli.py' not in files:raise TrainingError('DataFlex 入口缺失')
    return files,{'commit':commit,'dirty':dirty,'custom_files':custom_files,'files':{k:digest(v) for k,v in files.items()}}


@training_transaction
def export_bundle(service, key, options=None):
    options=options or {};record=service.get('plans',key);plan=copy.deepcopy(record['plan']);compiled=compile_plan(service,plan)
    if compiled['checks']['errors']:raise TrainingError('; '.join(compiled['checks']['errors']))
    root=Path(os.environ.get('DATAFLEX_SOURCE_DIR') or Path(__file__).resolve().parents[5].parent/'DataFlex')
    files,source=snapshot_source(root,plan.get('custom_sources',[]))
    source_hash=digest(canonical(source));refs=[];inputs=[];mapping=[];role_members={'train':set(),'validation':set(),'reference':set()}
    train=compiled['train'];info=compiled['dataset_info']
    for i,b in enumerate(plan['data']):
        name='dataset_'+str(i);content=None;sample_ids=None
        if b['kind']=='release':
            from app.services.training_lifecycle import TrainingLifecycle
            lifecycle=TrainingLifecycle(service.library);meta=service.library.db.get('releases',b['ref'])
            if meta.get('modality','text')!=plan['modality'] or meta.get('training_type','sft')!=plan['task']:raise TrainingError(f'data[{i}]: 任务/模态与发布版本不兼容')
            package=lifecycle.download(b['ref']);members=safe_members(safe_read(package))
            content=members.get('data.jsonl') or members.get('train.jsonl')
            if content is None:
                candidates=[k for k in members if k.endswith('.jsonl')]
                if len(candidates)!=1:raise TrainingError('发布包缺少唯一数据文件')
                content=members[candidates[0]]
            sample_ids=meta.get('sample_ids')
            for media,body in members.items():
                if media.startswith('media/'):
                    files['data/'+media]=body
        elif b['kind']=='file':
            path=Path(b['ref'])
            if path.suffix.lower() not in ['.jsonl','.json']:raise TrainingError('仅支持 JSONL/JSON 数据文件')
            if b.get('mode')=='reference':
                if path.is_symlink() or not path.is_file():raise TrainingError('引用必须为普通文件')
                import hashlib
                hasher=hashlib.sha256()
                with path.open('rb') as handle:
                    for block in iter(lambda:handle.read(1024*1024),b''):hasher.update(block)
                h=hasher.hexdigest()
                if b.get('sha256') and b['sha256']!=h:raise TrainingError('外部文件引用哈希不匹配')
                compiled['checks']['warnings'].append('外部文件引用只核验内容哈希，样本重叠与预处理索引未扫描')
                execution_ref=b.get('execution_ref') or str(path.resolve())
                # This path is consumed by the Linux training host, not this desktop.
                from pathlib import PurePosixPath
                if not PurePosixPath(execution_ref).is_absolute() or '\\' in execution_ref:raise TrainingError('执行引用必须为 Linux 绝对路径')
                refs.append(dict(b,ref=execution_ref,sha256=h));info[name]['file_name']=execution_ref;continue
            content=safe_read(path)
            if path.suffix.lower() not in ['.jsonl','.json']:raise TrainingError('仅支持 JSONL/JSON 数据文件')
            if b.get('sha256') and digest(content)!=b['sha256']:raise TrainingError(f'data[{i}]: 文件哈希不匹配')
            if b.get('mode')=='reference':
                refs.append(dict(b,sha256=digest(content)));info[name]['file_name']=str(path.resolve());content=None
        else:
            refs.append(b);continue
        if content is not None:
            try:
                rows=json.loads(content) if content.lstrip().startswith(b'[') else [json.loads(line) for line in content.splitlines() if line.strip()]
                if not isinstance(rows,list) or not all(isinstance(r,dict) for r in rows):raise ValueError('rows')
            except ValueError as e:raise TrainingError(f'data[{i}]: 数据不是 JSON 对象序列') from e
            original_rows=copy.deepcopy(rows)
            if plan['task']=='dpo':
                info[name].update(ranking=True,columns={'prompt':'prompt','chosen':'chosen','rejected':'rejected'})
            elif rows and all('messages' in row for row in rows):
                info[name].update(formatting='sharegpt',columns={'messages':'messages'},tags={'role_tag':'role','content_tag':'content','user_tag':'user','assistant_tag':'assistant','system_tag':'system'})
            if plan['modality']=='image_text':
                if b['kind']!='release':raise TrainingError('图文外部文件需先导入平台并发布，以核验媒体身份')
                for row in rows:
                    images=list(row.get('images',[]))
                    if row.get('image'):images.append(row.pop('image'))
                    for message in row.get('messages',[]):
                        if isinstance(message.get('content'),list):
                            text=[]
                            for block in message['content']:
                                if block.get('type')=='text':text.append(block.get('text',''))
                                elif block.get('type')=='image_url':
                                    ref=block['image_url'];images.append(ref.get('url') if isinstance(ref,dict) else ref);text.append('<image>')
                                else:raise TrainingError('不支持的图文消息块')
                            message['content']=''.join(text)
                    if not images:raise TrainingError('图文行缺少明确图片引用')
                    for ref in images:
                        if 'data/'+ref not in files:raise TrainingError('包内图片引用缺失')
                    row['images']=images
                info[name]['columns']['images']='images'
            for row in original_rows:
                role_members[b['role']].add(digest(canonical(row)))
            if not rows:raise TrainingError('训练数据文件为空')
            if plan['task']=='pt':
                field=b.get('columns',{}).get('prompt','text')
                if not all(isinstance(r.get(field),str) for r in rows):raise TrainingError('PT 需要 columns.prompt 显式指向文本字段')
            elif plan['task']=='sft' and info[name].get('formatting')!='sharegpt':
                cols=info[name]['columns']
                if not all(isinstance(r.get(cols.get('prompt','instruction')),str) and isinstance(r.get(cols.get('response','output')),str) for r in rows):raise TrainingError('SFT 字段与 columns 映射不匹配')
            files['data/'+name+'.jsonl']=b''.join(canonical(r)+b'\n' for r in rows)
            for index,row in enumerate(original_rows):mapping.append({'dataset':name,'source_index':index,'sample_id':sample_ids[index] if sample_ids and len(sample_ids)==len(rows) else None,'row_sha256':digest(canonical(row)),'preprocessed_index':None})
            inputs.append({'binding':b,'file':'data/'+name+'.jsonl','sha256':digest(files['data/'+name+'.jsonl']),'rows':len(rows)})
    if role_members['train'] & role_members['validation']:raise TrainingError('训练与验证集存在可识别的重复样本')
    if role_members['train'] & role_members['reference']:compiled['checks']['warnings'].append('策略参考集与训练集有重复成员，已披露')
    # Snapshot explicitly referenced parameter artifacts, never follow arbitrary directories.
    def rewrite(value,key=''):
        if isinstance(value,dict):return {k:rewrite(v,k) for k,v in value.items()}
        if isinstance(value,list):return [rewrite(v,key) for v in value]
        if isinstance(value,str) and key.endswith(('_path','_file')) and value and key not in ['reference_model_path']:
            p=Path(value)
            if not p.is_absolute():p=root/p
            content=safe_read(p);name='assets/'+digest(content)[:16]+p.suffix;files[name]=content;return name
        return value
    components=rewrite(compiled['components'])
    files.update({'component_descriptors.json':canonical(catalog(service)),'plan.json':canonical(plan),'train.yaml':yaml.safe_dump(train,allow_unicode=True,sort_keys=False).encode(),'components.yaml':yaml.safe_dump(components,allow_unicode=True,sort_keys=False).encode(),'data/dataset_info.json':canonical(info),'sample_map.json':canonical({'mapping':mapping,'preprocessing_mapping':'unknown until processor emits exact identity; packing disabled'}),'source_identity.json':canonical(source),'runner.py':(Path(__file__).parent/'training_runtime/runner.py').read_bytes()})
    files['run.sh']=b'#!/bin/sh\nset -eu\ncd "$(dirname "$0")"\nexec "${DATAFLEX_PYTHON:-python3}" runner.py "$@"\n'
    files['prepare_data.py']=PREPARE_DATA.encode()
    manifest={'schema_version':1,'format':'dataflex-run-bundle','bundle_id':uuid.uuid4().hex,'plan_id':key,'plan_version':record['version'],'source_sha256':source_hash,'source':{'commit':source['commit'],'dirty':source['dirty']},'inputs':inputs,'external_references':refs,'files':{k:digest(v) for k,v in files.items()},'limitations':compiled['checks'].get('warnings',[]),'model_included':False}
    files['manifest.json']=canonical(manifest)
    if sum(map(len,files.values()))>MAX_BUNDLE:raise TrainingError('运行包超过大小限制')
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for name,body in files.items():z.writestr(name,body)
    path=service.root/'bundles'/(manifest['bundle_id']+'.zip');path.parent.mkdir(exist_ok=True);atomic_write(path,out.getvalue())
    return service.put('bundles',{'manifest':manifest,'manifest_sha256':digest(files['manifest.json']),'archive_sha256':digest(out.getvalue()),'path':str(path),'plan_snapshot':plan},key=manifest['bundle_id'])

PREPARE_DATA='''"""Explicit HF materialization. Does not fetch model weights or install packages."""
import argparse,hashlib,json,uuid,zipfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--allow-dataset-download',action='store_true');a=p.parse_args()
if not a.allow_dataset_download:raise SystemExit('Pass --allow-dataset-download explicitly; prepare in an isolated training environment')
from datasets import load_dataset
root=Path(__file__).resolve().parent
manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'));info=json.loads((root/'data/dataset_info.json').read_text(encoding='utf-8'))
for index,b in enumerate(json.loads((root/'plan.json').read_text(encoding='utf-8'))['data']):
    if b['kind']!='huggingface':continue
    ds=load_dataset(b['ref'],b.get('subset') or None,revision=b['revision'],split=b['split'])
    path=root/'data'/('dataset_'+str(index)+'.jsonl');ds.to_json(str(path),force_ascii=False)
    info['dataset_'+str(index)]={'file_name':path.name,'columns':b['columns']}
(root/'data/dataset_info.json').write_text(json.dumps(info),encoding='utf-8')
# Materialization changes identity; create a derived input manifest, never claim the exported identity is unchanged.
manifest['bundle_id']=uuid.uuid4().hex
manifest['parent_manifest_sha256']=hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest()
manifest['external_references']=[b for b in manifest['external_references'] if b['kind']!='huggingface']
for path in (root/'data').glob('*'):
    if path.is_file():manifest['files'][path.relative_to(root).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
(root/'manifest.json').write_text(json.dumps(manifest,sort_keys=True),encoding='utf-8')
archive=root.parent/('prepared-'+manifest['bundle_id']+'.zip')
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
    for name in list(manifest['files'])+['manifest.json']:z.write(root/name,name)
print(str(archive))
print('Import this derived bundle into WebUI before starting.')
'''


@training_transaction
def import_bundle(service,blob):
    from app.schemas.model_training import TrainingPlan
    files=safe_members(blob)
    try:manifest=json.loads(files['manifest.json']);plan=TrainingPlan.model_validate_json(files['plan.json']).model_dump()
    except (KeyError,ValueError) as e:raise TrainingError('运行包缺少合法清单/方案') from e
    if manifest.get('format')!='dataflex-run-bundle' or manifest.get('schema_version')!=1 or not re.fullmatch('[0-9a-f]{32}',manifest.get('bundle_id','')):raise TrainingError('不支持的运行包格式/身份')
    if set(files)!=set(manifest.get('files',{}))|{'manifest.json'}:raise TrainingError('包成员与输入清单不一致')
    for name,h in manifest['files'].items():
        if digest(files[name])!=h:raise TrainingError('输入文件哈希不匹配')
    h=digest(files['manifest.json']);key=manifest['bundle_id']
    existing=next((b for b in service.list('bundles') if b['id']==key),None)
    if existing:
        if existing['manifest_sha256']!=h:raise TrainingError('运行包身份冲突',409)
        return dict(existing,idempotent=True)
    path=service.root/'bundles'/(key+'.zip');path.parent.mkdir(exist_ok=True);atomic_write(path,blob)
    return service.put('bundles',{'manifest':manifest,'manifest_sha256':h,'archive_sha256':digest(blob),'path':str(path),'plan_snapshot':plan},key)
