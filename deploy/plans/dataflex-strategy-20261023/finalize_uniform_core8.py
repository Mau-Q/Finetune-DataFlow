"""Host CPU-only final identity check; no model execution or task interruption.

Python 3.6 compatible. Run only after the finite cohort controller completes.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import time
from run_core8_suite import HOST,HOST_RUN,CONTAINER,require_evaluation


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def command(args):return subprocess.check_output(args).decode('utf-8')


def main():
    root=HOST_RUN/'uniform-core8-20261023'
    summary=json.loads((root/'uniform-results-summary.json').read_text())
    assert summary['status']=='UNIFORM_PROTOCOL_CORE8_COMPLETE_WITH_REPRODUCIBILITY_LIMITATION'
    for name in ['BASE']+['G%02d'%i for i in range(8)]:require_evaluation(name,64,root)
    expected=summary['core_runs']['G00']['source_files_sha256']
    code="import pathlib,hashlib,json,dataflex;p=pathlib.Path(dataflex.__file__).parent;print(json.dumps({str(f.relative_to(p)):hashlib.sha256(f.read_bytes()).hexdigest() for f in p.rglob('*') if f.suffix in ['.py','.yaml']}))"
    installed=json.loads(command(['docker','exec','-e','CUDA_VISIBLE_DEVICES=',CONTAINER,'python','-c',code]))
    platform=Path('/sharedata/home/huruiqian/DataFlow/app/repos/dataflex/src/dataflex')
    platform_files={str(p.relative_to(platform)):sha(p) for p in platform.rglob('*') if p.suffix in ['.py','.yaml']}
    assert installed==expected==platform_files and len(expected)==75
    containers=[]
    for item in json.loads(command(['docker','inspect','--size',CONTAINER,'rui-qwen35-9b-smoke-20261022'])):
        containers.append({'name':item['Name'],'id':item['Id'],'running':item['State']['Running'],
            'network':item['HostConfig']['NetworkMode'],'gpu_requests':item['HostConfig']['DeviceRequests'],
            'writable_bytes':item['SizeRw'],
            'mounts':[{k:m.get(k) for k in ['Source','Destination','RW']} for m in item['Mounts']]})
    assert all(c['running'] for c in containers)
    state={'captured_unix':time.time(),'hostname':command(['hostname']).strip(),'account':command(['id','-un']).strip(),
        'containers':containers,'container_processes':command(['docker','top',CONTAINER]),
        'gpu2':command(['nvidia-smi','-i','2','--query-gpu=uuid,memory.used,memory.free','--format=csv,noheader']),
        'new_root_disk_usage':command(['du','-sh',str(root)]),
        'source_check':{'files':75,'installed_and_platform_match_all_training_runs':True},
        'task_script_sha256':{p.name:sha(p) for p in HOST.glob('*.py')},
        'summary_sha256':sha(root/'uniform-results-summary.json'),
        'cohort_plan_sha256':sha(root/'cohort-plan.json'),
        'preserved_initial_core8_summary_sha256':sha(HOST_RUN/'results-summary.json'),
        'preserved_pair_verdict_sha256':sha(HOST_RUN/'gradient-resolution-v2-20261023/resolution-verdict.json'),
        'preserved_pair_summary_sha256':sha(HOST_RUN/'gradient-resolution-v2-20261023/resolution-summary.json')}
    (HOST/'core8-logs/uniform-core8-final-state.json').write_text(json.dumps(state,indent=2)+'\n')
    print(json.dumps({'status':summary['status'],'source_files':75,'gpu2':state['gpu2']}),flush=True)


if __name__=='__main__':main()
