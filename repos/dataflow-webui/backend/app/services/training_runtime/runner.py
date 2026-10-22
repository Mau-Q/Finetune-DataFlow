"""Portable standard-library runner. Execute only in the independent training environment."""
import argparse
import base64
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def dump(path, value):
    temp=path.with_suffix('.pending')
    temp.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False),encoding='utf-8');os.replace(temp,path)


def sha(data):return hashlib.sha256(data).hexdigest()


def verify(root):
    manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    for name,h in manifest['files'].items():
        path=root/name
        if Path(name).is_absolute() or '..' in Path(name).parts or path.is_symlink() or not path.is_file() or sha(path.read_bytes())!=h:
            raise ValueError('Input hash/type mismatch: '+name)
    return manifest


def preflight(root, environment=True):
    manifest=verify(root)
    if not environment:return {'inputs':'verified','environment':'NOT_RUN'}
    import yaml
    config=yaml.safe_load((root/'train.yaml').read_text(encoding='utf-8'))
    sys.path.insert(0,str(root/'source/src'))
    versions={name:importlib.metadata.version(name) for name in ['torch','transformers','llamafactory','datasets','omegaconf']}
    import torch
    if not torch.cuda.is_available():raise ValueError('CUDA is unavailable')
    model=config['model_name_or_path']
    if not Path(model).is_dir():
        if not config.get('model_revision'):raise ValueError('Model must have a fixed revision or local directory')
        from huggingface_hub import snapshot_download
        snapshot_download(model,revision=config['model_revision'],local_files_only=True)
    for binding in manifest.get('external_references',[]):
        if binding['kind']=='file':
            p=Path(binding['ref'])
            if not p.is_file() or p.is_symlink() or sha(p.read_bytes())!=binding['sha256']:raise ValueError('External reference mismatch')
        else:raise ValueError('HF data must be materialized using prepare_data.py before training')
    import importlib
    buckets=yaml.safe_load((root/'components.yaml').read_text(encoding='utf-8')) or {}
    for bucket,module in [('selectors','selector'),('mixers','mixer'),('weighters','weighter'),('reorders','reorder')]:
        if buckets.get(bucket):
            importlib.import_module('dataflex.train.'+module)
            from dataflex.core.registry import REGISTRY
            for name,component in buckets[bucket].items():
                registered=component.get('params',{}).get('kind',name) if bucket=='reorders' else name
                REGISTRY.get(module,registered)
    model_metadata={}
    if Path(model).is_dir():
        for name in ['config.json','tokenizer_config.json']:
            p=Path(model)/name
            if p.is_file():model_metadata[name]=sha(p.read_bytes())
    return {'inputs':'verified','model_metadata_sha256':model_metadata,'versions':versions,'cuda':torch.version.cuda,'gpu_count':torch.cuda.device_count()}


def identity(pid):
    proc=Path('/proc')/str(pid)
    if proc.exists():
        # /proc stat comm can contain spaces and parentheses.
        start=(proc/'stat').read_text(encoding='utf-8').rsplit(')',1)[1].split()[19]
        return {'start':start,'cmd_sha256':sha((proc/'cmdline').read_bytes())}
    result=subprocess.run(['ps','-p',str(pid),'-o','lstart=','-o','command='],capture_output=True,check=True)
    if not result.stdout.strip():raise ProcessLookupError(pid)
    return {'ps_sha256':sha(result.stdout)}


def stop(root, attempt):
    result=root/'result.json'
    if result.exists():
        terminal=json.loads(result.read_text(encoding='utf-8'))
        if terminal.get('attempt_id')==attempt and terminal.get('status') in ['stopped','completed','failed']:return terminal
    record=json.loads((root/'process.json').read_text(encoding='utf-8'))
    if record['attempt_id']!=attempt or record['identity']!=identity(record['pid']):raise ValueError('PID identity mismatch; refusing signal')
    os.kill(record['pid'],signal.SIGTERM)
    for _ in range(100):
        result=root/'result.json'
        if result.exists() and json.loads(result.read_text(encoding='utf-8')).get('status') in ['stopped','completed','failed']:
            return json.loads(result.read_text(encoding='utf-8'))
        time.sleep(.1)
    raise TimeoutError('Stop requested; exit not confirmed')


def read_metrics(path):
    if not path.exists():return []
    rows=[]
    for line in path.read_text(encoding='utf-8',errors='replace').splitlines(keepends=True):
        if not line.endswith('\n'):break
        try:
            row=json.loads(line)
            # LlamaFactory trainer log has current_steps / loss / learning_rate.
            step=row.get('step',row.get('current_steps'))
            if step is not None:rows.append(dict(row,step=step))
        except (ValueError,TypeError):continue
    return rows


def run(root, attempt, run_id, expected_manifest):
    if sha((root/'manifest.json').read_bytes())!=expected_manifest:raise ValueError('Manifest identity mismatch')
    import fcntl
    lock=(root/'runner.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:return
    if (root/'process.json').exists():
        existing=json.loads((root/'process.json').read_text(encoding='utf-8'))
        if existing['attempt_id']!=attempt:raise ValueError('Run directory is bound to another attempt')
        # A previous terminal/partial execution must never be silently restarted.
        return
    host_lock=(root.parent.parent/'.training-active.lock').open('a')
    try:fcntl.flock(host_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise ValueError('Another training process holds the host lock')
    dump(root/'process.json',{'pid':os.getpid(),'attempt_id':attempt,'identity':identity(os.getpid())})
    result={'schema_version':1,'run_id':run_id,'attempt_id':attempt,'input_manifest_sha256':expected_manifest,'sequence':0,'synthetic':False,'status':'preflight','metrics':[],'strategy_metrics':[],'artifacts':[],'environment':{},'actual_config':{},'log':''}
    child=None;stopping=False
    def terminate(_sig,_frame):
        nonlocal stopping
        stopping=True
        if child and child.poll() is None:
            os.killpg(child.pid,signal.SIGTERM)
    signal.signal(signal.SIGTERM,terminate)
    def sync():
        result['sequence']+=1;result['observed_at']=time.time()
        result['metrics']=read_metrics(root/'output/trainer_log.jsonl')
        odm=root/'output/odm_weights.jsonl'
        result['strategy_metrics']=read_metrics(odm)
        log=root/'train.log'
        if log.exists():
            with log.open('rb') as handle:
                end=handle.seek(0,2);start=max(0,end-1024*1024);handle.seek(start);raw=handle.read(end-start)
            result.update(log=raw.decode(errors='replace'),log_base64=base64.b64encode(raw).decode(),log_start_offset=start,log_end_offset=end)
        dump(root/'result.json',result)
    try:
        result['environment']=preflight(root)
        import yaml
        result['actual_config']=yaml.safe_load((root/'train.yaml').read_text(encoding='utf-8'))
        if stopping:
            result['status']='stopped';return
        env=os.environ.copy();env['PYTHONPATH']=str(root/'source/src')+os.pathsep+env.get('PYTHONPATH','');env['HF_HUB_OFFLINE']='1';env['HF_DATASETS_OFFLINE']='1'
        with (root/'train.log').open('ab') as log:
            child=subprocess.Popen([sys.executable,'-c','from dataflex.cli import main; main()','train','train.yaml'],cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            process_record=json.loads((root/'process.json').read_text(encoding='utf-8'))
            try:child_identity=identity(child.pid);child_pgid=os.getpgid(child.pid)
            except (ProcessLookupError,subprocess.CalledProcessError):child_identity=None;child_pgid=child.pid
            process_record.update(child_pid=child.pid,child_pgid=child_pgid,child_identity=child_identity)
            dump(root/'process.json',process_record)
            result['status']='running';sync()
            deadline=None
            while child.poll() is None:
                if stopping:
                    deadline=deadline or time.monotonic()+10
                    if time.monotonic()>deadline:os.killpg(child.pid,signal.SIGKILL)
                sync();time.sleep(1)
            result['exit_code']=child.returncode
            result['status']='stopped' if stopping else 'completed' if child.returncode==0 else 'failed'
        # Register checkpoints without copying weights. Identity records hashes of config/adapter metadata only.
        for p in (root/'output').glob('**/adapter_config.json'):
            result['artifacts'].append({'id':sha(str(p.relative_to(root)).encode())[:24],'path':str(p.parent),'sha256':sha(p.read_bytes()),'identity_scope':'adapter_config','availability':'remote_registered'})
        if (root/'output/config.json').is_file():
            p=root/'output/config.json';result['artifacts'].append({'id':'final-model','path':str(p.parent),'sha256':sha(p.read_bytes()),'identity_scope':'config_only','availability':'remote_registered'})
    except Exception as e:
        result['status']='failed';result['error']=str(e)
    finally:sync()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['verify','preflight','run','stop']);parser.add_argument('--attempt');parser.add_argument('--run-id');parser.add_argument('--manifest');args=parser.parse_args();root=Path(__file__).resolve().parent
    if args.command=='verify':print(json.dumps(preflight(root,False)))
    elif args.command=='preflight':print(json.dumps(preflight(root)))
    elif args.command=='stop':print(json.dumps(stop(root,args.attempt)))
    else:
        if not all([args.attempt,args.run_id,args.manifest]):parser.error('run requires --attempt, --run-id and --manifest')
        run(root,args.attempt,args.run_id,args.manifest)
