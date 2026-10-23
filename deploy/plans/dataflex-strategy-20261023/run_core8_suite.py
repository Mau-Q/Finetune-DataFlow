"""Sequential host launcher with evidence gates; never silently rerun an old attempt.

Python 3.6 compatible because node01's host interpreter is Python 3.6.
The container remains Python 3.12. Each explicitly selected stage ends on its own.
"""
import hashlib
import json
import math
import re
import subprocess
import time
from pathlib import Path

HOST = Path('/sharedata/home/huruiqian/DataFlow/environments/qwen35-9b/strategy-20261023')
HOST_RUN = Path('/sharedata/home/huruiqian/DataFlow/runs/qwen35-9b/20261022-smoke/strategy-20261023')
LOG = HOST / 'core8-logs'
CONTAINER = 'rui-dataflex-strategy-gpu2-20261023'
WORK = '/work/strategy-20261023/'
RUN = '/runs/strategy-20261023/'
GPU = 'GPU-1f7d7941-5155-1c90-819d-5bf7dbec5b18'


def record(record):
    with (LOG / 'suite-events.jsonl').open('a') as handle:
        handle.write(json.dumps(dict(timestamp=time.time(), **record)) + '\n')


def successful_folder(name, root=None):
    root = HOST_RUN if root is None else root
    pointer = json.loads((root / name / 'successful-attempt.json').read_text())
    attempt = pointer['attempt']
    if not re.fullmatch(r'attempt[1-9][0-9]*', attempt):
        raise ValueError('Invalid attempt identity')
    # Container absolute paths must never be interpreted as host paths.
    return root / name / attempt


def require_mechanism(name, root=None):
    folder = successful_folder(name, root)
    audit = json.loads((folder / 'audit.json').read_text())
    if audit['status'] != 'MECHANISM_OBSERVED' or audit['name'] != name:
        raise ValueError('Mechanism evidence missing for ' + name)
    if name in ['G06', 'G07']:
        paired = audit.get('paired_control') or {}
        if not (paired.get('initial_adapter_tensor_sha256') and paired.get('snapshot_sha256')
                and paired.get('micro_rng_seed_base') == 420000):
            raise ValueError('Shared initialization and RNG evidence missing for ' + name)
        if name == 'G07':
            if paired.get('trajectory_status') == 'INCONCLUSIVE_WARMUP_MISMATCH':
                if paired.get('same_forward_diagnostic', {}).get('status') != 'SAME_FORWARD_WEIGHT_GRADIENT_VERIFIED':
                    raise ValueError('Inconclusive trajectory requires separate same-forward gradient evidence')
            elif not paired.get('first_weighted_gradient_norms'):
                raise ValueError('Paired warmup and weighted gradient evidence missing for G07')
    return audit


def evaluation_folder(name, root=None):
    root = HOST_RUN if root is None else root
    base = root / 'evaluation' / name
    pointer = base / 'successful-evaluation.json'
    if not pointer.exists():
        return base
    attempt = json.loads(pointer.read_text())['attempt']
    if attempt == 'initial':
        return base
    if not re.fullmatch(r'attempt[1-9][0-9]*', attempt):
        raise ValueError('Invalid evaluation attempt identity')
    return base / attempt


def require_evaluation(name, count, root=None):
    root = HOST_RUN if root is None else root
    result = json.loads((evaluation_folder(name, root) / 'metrics.json').read_text())
    if result['model'] != name or result['n'] != count:
        raise ValueError('Incomplete evaluation for ' + name)
    if (result.get('generation', {}).get('prompt_method') != 'hf_native_chat_template_enable_thinking_false'
            or result.get('reasoning_tag_outputs') != 0):
        raise ValueError('No-think generation evidence missing: ' + name)
    if count == 2 and result.get('empty_outputs') != 0:
        raise ValueError('Empty gate reload output: ' + name)
    expected_data = hashlib.sha256((root / 'data-manifest.json').read_bytes()).hexdigest()
    if result['data_manifest_sha256'] != expected_data:
        raise ValueError('Evaluation data identity changed: ' + name)
    if name != 'BASE':
        folder = successful_folder(name, root)
        adapter = folder / 'output/adapter_model.safetensors'
        actual = hashlib.sha256(adapter.read_bytes()).hexdigest()
        if not result['adapter_reloaded'] or result['adapter_sha256'] != actual:
            raise ValueError('Reload does not match saved adapter: ' + name)
    return result


def require_gates(root=None):
    root = HOST_RUN if root is None else root
    for batch in [1, 2]:
        name = 'GATE2-B' + str(batch)
        audit = require_mechanism(name, root)
        if not (len(audit['source_counts']) == 4 and audit['supervised_max'] >= 250
                and audit['length_max'] == 1024 and audit['optimizer_steps'] == 2):
            raise ValueError('Representative gate acceptance missing: ' + name)
        require_evaluation(name, 2, root)
    score = json.loads((evaluation_folder('GATE2-B2', root) / 'score-batch-check.json').read_text())
    singles, pairs = score['single'], score['batch2']
    if (len(singles) != 4 or len(pairs) != 4
            or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in singles + pairs)
            or not all(abs(a-b) <= .03 + .01 * abs(a) for a, b in zip(singles, pairs))):
        raise ValueError('Real Qwen scoring batch consistency gate missing')


def execute(label, script, args, cuda=True):
    command = ['docker', 'exec']
    if not cuda:
        command += ['-e', 'CUDA_VISIBLE_DEVICES=']
    command += [CONTAINER, 'python', WORK + script] + args
    record({'event': 'start', 'label': label, 'command': command})
    logfile = LOG / (label + '.log')
    if logfile.exists():
        logfile = LOG / (label + '-recheck-' + str(int(time.time())) + '.log')
    with logfile.open('x') as handle:
        result = subprocess.run(command, stdout=handle, stderr=subprocess.STDOUT)
    record({'event': 'exit', 'label': label, 'returncode': result.returncode})
    if result.returncode:
        raise RuntimeError(label + ' failed; inspect preserved log')


def free_check():
    value = subprocess.check_output([
        'nvidia-smi', '--id=' + GPU, '--query-gpu=memory.free',
        '--format=csv,noheader,nounits']).decode().strip()
    free = int(value)
    record({'event': 'resource_check', 'gpu2_free_mib': free})
    if free < 21000:
        raise RuntimeError('GPU2 resource gate: free MiB ' + value)


def main(stage):
    if stage == 'gates':
        free_check()
        if not (HOST_RUN / 'GATE2-B2/successful-attempt.json').exists():
            execute('GATE2-B2-attempt1', 'observed_run.py',
                    [RUN + 'GATE2-B2/train.yaml', RUN + 'GATE2-B2/attempt1'])
        for batch in [1, 2]:
            name = 'GATE2-B' + str(batch)
            execute(name + '-audit', 'audit_observations.py', [name], False)
            if (evaluation_folder(name) / 'metrics.json').exists():
                require_evaluation(name, 2)
            else:
                free_check()
                execute(name + '-reload', 'evaluate_frozen.py', [name])
        require_gates()
    elif stage == 'core':
        require_gates()
        for index in range(8):
            name = 'G%02d' % index
            if (HOST_RUN / name / 'successful-attempt.json').exists():
                execute(name + '-audit', 'audit_observations.py', [name], False)
                require_mechanism(name)
                continue
            free_check()
            execute(name + '-attempt1', 'observed_run.py',
                    [RUN + name + '/execution-v2.yaml', RUN + name + '/attempt1'])
            execute(name + '-audit', 'audit_observations.py', [name], False)
            require_mechanism(name)
    elif stage == 'evaluate':
        require_gates()
        for index in range(8):
            require_mechanism('G%02d' % index)
        for name in ['BASE'] + ['G%02d' % index for index in range(8)]:
            if (evaluation_folder(name) / 'metrics.json').exists():
                require_evaluation(name, 64)
                continue
            free_check()
            execute(name + '-evaluation', 'evaluate_frozen.py', [name])
            require_evaluation(name, 64)
    else:
        raise ValueError('Unknown stage: ' + stage)
    record({'event': 'stage_completed', 'stage': stage})


if __name__ == '__main__':
    import sys
    try:
        main(sys.argv[1])
    except Exception as error:
        record({'event': 'stopped', 'stage': sys.argv[1], 'error': repr(error)})
        raise
