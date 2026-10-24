"""Finite GPU1 host driver, Python 3.6; each failed attempt remains untouched."""
import argparse
import hashlib
import json
import math
import subprocess
import time
from pathlib import Path

WORK = Path('/sharedata/home/huruiqian/DataFlow/environments/qwen35-9b/gpu1-unified-20261024')
HOST_RUN = Path('/sharedata/home/huruiqian/DataFlow/runs/qwen35-9b/20261022-smoke/strategy-20261023')
GPU = 'GPU-492f7b9f-5be1-64c0-58eb-9d3d582fcddc'
CONTAINER = 'rui-dataflex-strategy-gpu1-20261024'
SCRIPT = '/work/strategy-20261023/'
RUN = '/runs/strategy-20261023/'
LOG = WORK/'gpu1-logs'


def record(event, **fields):
    row = dict(timestamp=time.time(), event=event, **fields)
    with (LOG/'events.jsonl').open('a') as handle:
        handle.write(json.dumps(row)+'\n')
    print(json.dumps(row), flush=True)


def execute(label, script, args, cuda=True):
    path = LOG/(label+'.log')
    if path.exists():
        raise FileExistsError('Existing operation log must be inspected: '+str(path))
    command = ['docker', 'exec'] + ([] if cuda else ['-e', 'CUDA_VISIBLE_DEVICES='])
    command += [CONTAINER, 'python', SCRIPT+script]+args
    sources = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in WORK.glob('*.py')}
    source_path = LOG/(label+'-sources.json')
    source_path.write_text(json.dumps(sources, indent=2)+'\n')
    record('start', label=label, command=command)
    with path.open('x') as handle:
        result = subprocess.run(command, stdout=handle, stderr=subprocess.STDOUT)
    record('exit', label=label, returncode=result.returncode)
    if result.returncode:
        raise RuntimeError('Failed '+label+'; preserved '+str(path))


def guard(batch, evaluation=False):
    minimum = 12000 if evaluation else (21000 if batch == 2 else 16000)
    profile = HOST_RUN/'gpu1-gates-20261024'/('GATE2-B'+str(batch))/'attempt1/resource.json'
    if not evaluation and profile.exists():
        minimum = max(minimum, int(math.ceil(json.loads(profile.read_text())['peak_reserved_gib']*1024))+3072)
    free = int(subprocess.check_output(['nvidia-smi', '--id='+GPU, '--query-gpu=memory.free', '--format=csv,noheader,nounits']).decode().strip())
    record('resource_check', free_mib=free, minimum_free_mib=minimum, microbatch=batch, evaluation=evaluation)
    if free < minimum:
        raise RuntimeError('GPU1 resource guard failed: '+str(free)+' < '+str(minimum))


def main(stage):
    LOG.mkdir(exist_ok=True)
    assert subprocess.check_output(['hostname']).decode().strip() == 'node01'
    assert subprocess.check_output(['id', '-un']).decode().strip() == 'huruiqian'
    root = RUN+('gpu1-gates-20261024' if stage == 'gates' else 'gpu1-core8-20261024')
    execute(stage+'-prepare', 'prepare_gpu1_cohort.py', ['--root', root]+(['--gates'] if stage == 'gates' else []), False)
    if stage == 'gates':
        for batch in [1, 2]:
            name = 'GATE2-B'+str(batch)
            guard(batch)
            execute(name+'-train', 'gpu1_entry.py', ['train', '--root', root, '--name', name])
            execute(name+'-audit', 'gpu1_entry.py', ['audit', '--root', root, '--name', name], False)
            guard(batch, True)
            execute(name+'-reload', 'gpu1_entry.py', ['evaluate', '--root', root, '--name', name])
        for name in ['G01-A', 'G01-B', 'G02-A', 'G06-A', 'G06-B', 'G07-A']:
            guard(2 if name.startswith(('G06', 'G07')) else 1)
            execute('P-'+name, 'gpu1_entry.py', ['probe', '--root', root, '--name', 'P-'+name])
        execute('gates-verify', 'verify_gpu1_gates.py', ['--root', root], False)
    else:
        for i in range(8):
            name = 'G%02d'%i
            guard(2 if i >= 6 else 1)
            execute(name+'-train', 'gpu1_entry.py', ['train', '--root', root, '--name', name])
            execute(name+'-audit', 'gpu1_entry.py', ['audit', '--root', root, '--name', name], False)
        for name in ['BASE']+['G%02d'%i for i in range(8)]:
            guard(1, True)
            execute(name+'-evaluate', 'gpu1_entry.py', ['evaluate', '--root', root, '--name', name])
    record('stage_completed', stage=stage)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('stage', choices=['gates', 'core'])
    args = parser.parse_args()
    try:
        main(args.stage)
    except Exception as error:
        if LOG.exists():
            record('stopped', stage=args.stage, error=repr(error))
        raise
