"""Find a training-length OOM interval while preserving shared-GPU headroom.

Each trial is a fresh process, with two optimizer updates and distinct output.
Only an actual CUDA OOM defines the upper bound. Other errors stop the sweep.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

os.environ.setdefault('PYTORCH_CUDA_ALLOC_CONF', 'expandable_segments:True')
import torch

root = Path('/runs/capacity-sweep')
root.mkdir(exist_ok=False)
free, total = torch.cuda.mem_get_info()
reserve = 3 * 2**30
budget = min(total * .80, free - reserve)
if budget <= 0:
    raise RuntimeError('No memory budget after reserving shared-GPU headroom')
fraction = budget / total
report = {'status': 'RUNNING', 'physical_card_maximum': False, 'synthetic': True,
          'gpu': torch.cuda.get_device_name(0), 'initial_free_gib': free / 2**30,
          'torch_total_gib': total / 2**30, 'reserve_gib': 3,
          'torch_budget_gib': budget / 2**30, 'torch_memory_fraction_limit': fraction,
          'cuda_allocator_config': os.environ['PYTORCH_CUDA_ALLOC_CONF'],
          'reserve_scope': 'Outside Torch allocator budget; CUDA runtime and other non-Torch allocations consume part of it',
          'micro_batch': 1, 'gradient_accumulation': 1, 'optimizer_steps_per_pass': 2,
          'precision_tokens': 1024, 'trials': []}


def save():
    (root / 'report.json').write_text(json.dumps(report, indent=2))


def trial(length):
    available, _ = torch.cuda.mem_get_info()
    # Ignore sub-GiB context/accounting fluctuations, but stop on a new workload.
    if available < budget + reserve - 512 * 2**20:
        raise RuntimeError('GPU free memory changed; stop instead of displacing another workload')
    folder = root / f'trial-{len(report["trials"]):02d}-{length}'
    folder.mkdir()
    command = [sys.executable, '/work/smoke.py']
    started = time.time()
    with (folder / 'prepare.log').open('w') as log:
        subprocess.run([*command, 'prepare', '--root', str(folder), '--only-length',
                        '--length', str(length)], stdout=log, stderr=subprocess.STDOUT,
                       check=True, timeout=180)
    with (folder / 'train.log').open('w') as log:
        process = subprocess.run([*command, 'train', '--root', str(folder),
                                  '--length', str(length), '--memory-fraction', str(fraction)],
                                 stdout=log, stderr=subprocess.STDOUT, timeout=1800)
    text = (folder / 'train.log').read_text(errors='replace')
    if process.returncode == 0:
        result = json.loads((folder / f'smoke-{length}.json').read_text())
        status = 'PASSED'
    elif 'cuda out of memory' in text.lower() or 'torch.OutOfMemoryError' in text:
        result = {'error_tail': text[-2500:]}
        failure = folder / f'oom-{length}.json'
        if failure.exists():
            result['memory_receipt'] = json.loads(failure.read_text())
        status = 'OOM'
    else:
        result = {'error_tail': text[-2500:]}
        status = 'ERROR'
    row = {'length': length, 'status': status, 'exit_code': process.returncode,
           'seconds': time.time() - started, 'directory': str(folder), 'result': result}
    report['trials'].append(row)
    save()
    print(json.dumps({'length': length, 'status': status, 'seconds': row['seconds']}), flush=True)
    if status == 'ERROR':
        raise RuntimeError('Non-OOM trial failure; inspect trial log')
    return status == 'PASSED'


save()
try:
    # Begin with the requested baseline using the same budget as all later trials.
    length = 8192
    lower, upper = 0, None
    while length <= 131072:
        if trial(length):
            lower = length
            length *= 2
        else:
            upper = length
            break
    if upper is not None:
        while upper - lower > 1024:
            midpoint = ((lower + upper) // 2048) * 1024
            midpoint = max(lower + 1024, midpoint)
            if trial(midpoint):
                lower = midpoint
            else:
                upper = midpoint
        report.update(status='COMPLETED_WITH_OOM_BOUND', max_pass_tokens=lower or None,
                      first_oom_tokens=upper)
    else:
        report.update(status='NO_OOM_WITHIN_TESTED_RANGE', max_pass_tokens=lower,
                      first_oom_tokens=None)
except BaseException as error:
    report.update(status='STOPPED_ON_ERROR', error=str(error))
    save()
    raise
save()
print(json.dumps({k: v for k, v in report.items() if k != 'trials'}), flush=True)
