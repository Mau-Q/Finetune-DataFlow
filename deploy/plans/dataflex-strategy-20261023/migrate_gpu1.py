"""Host Python 3.6: snapshot our idle actual stack into a separate offline GPU1 container."""
import hashlib
import json
import subprocess
import time
from pathlib import Path

OLD = 'rui-dataflex-strategy-gpu2-20261023'
NEW = 'rui-dataflex-strategy-gpu1-20261024'
GPU = 'GPU-492f7b9f-5be1-64c0-58eb-9d3d582fcddc'
BASE = Path('/sharedata/home/huruiqian/DataFlow')
WORK = BASE/'environments/qwen35-9b/gpu1-unified-20261024'
IMAGE = 'rui/dataflex-strategy:20261024-gpu1-actual'


def out(args):
    return subprocess.check_output(args).decode().strip()


def main():
    evidence = WORK/'migration'; evidence.mkdir(exist_ok=False)
    assert out(['hostname']) == 'node01' and out(['id', '-un']) == 'huruiqian'
    top = out(['docker', 'top', OLD])
    assert len(top.splitlines()) == 2 and '/usr/bin/sleep infinity' in top
    old = json.loads(out(['docker', 'inspect', OLD]))[0]
    (evidence/'old-inspect.json').write_text(json.dumps(old, indent=2))
    (evidence/'gpu-before.txt').write_text(out(['nvidia-smi']))
    (evidence/'gpu-processes.txt').write_text(out(['nvidia-smi', '--query-compute-apps=gpu_uuid,pid,process_name,used_memory', '--format=csv']))
    free = int(out(['nvidia-smi', '--id='+GPU, '--query-gpu=memory.free', '--format=csv,noheader,nounits']))
    assert free >= 21000, free
    identity = """import hashlib,importlib.metadata,json,dataflex
from pathlib import Path
root=Path(dataflex.__file__).parent
print(json.dumps({'packages':{n:importlib.metadata.version(n) for n in ['dataflex','torch','triton','flash-linear-attention','transformers','peft','bitsandbytes','llamafactory']},'sources':{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob('*')) if p.suffix in ['.py','.yaml']}}))
"""
    before = json.loads(out(['docker', 'exec', OLD, 'python', '-c', identity]))
    assert len(before['sources']) == 75
    out(['docker', 'commit', '--pause=false', OLD, IMAGE])
    args = ['docker', 'run', '-d', '--name', NEW, '--network', 'none', '--gpus', 'device='+GPU,
            '--shm-size', '8g', '-v', str(WORK)+':/work/strategy-20261023:ro',
            '-v', str(BASE/'runs/qwen35-9b/20261022-smoke')+':/runs',
            '-v', str(BASE/'models/Qwen3.5-9B/c202236235762e1c871ad0ccb60c8ee5ba337b9a')+':/models/Qwen3.5-9B:ro',
            '-v', 'rui-dataflex-gpu1-cache-20261024:/cache']
    for item in old['Config']['Env']:
        key = item.split('=', 1)[0]
        if key in ['HF_HUB_OFFLINE', 'HF_DATASETS_OFFLINE', 'TORCHINDUCTOR_COMPILE_THREADS', 'PYTORCH_CUDA_ALLOC_CONF',
                   'TRITON_CACHE_DIR', 'TORCHINDUCTOR_CACHE_DIR', 'CUDA_VISIBLE_DEVICES', 'HF_HUB_DISABLE_TELEMETRY', 'DO_NOT_TRACK', 'HF_HOME']:
            args.extend(['-e', item])
    args.extend([IMAGE, 'infinity']); out(args)
    after = json.loads(out(['docker', 'exec', NEW, 'python', '-c', identity]))
    assert before == after
    gpu = out(['docker', 'exec', NEW, 'nvidia-smi', '--query-gpu=uuid', '--format=csv,noheader'])
    assert gpu == GPU, gpu
    receipt = {'status': 'ACTUAL_STACK_MATCHED_GPU1_ISOLATED', 'timestamp': time.time(),
               'identity': after, 'gpu_uuid': gpu, 'free_mib_at_migration': free,
               'old_container': OLD, 'new_container': NEW, 'image': IMAGE,
               'old_main_process': top, 'network': 'none', 'command': args}
    (evidence/'migration-receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    (evidence/'new-inspect.json').write_text(out(['docker', 'inspect', NEW]))
    print(json.dumps({'status': receipt['status'], 'packages': after['packages'], 'source_files': len(after['sources'])}))


if __name__ == '__main__':
    main()
