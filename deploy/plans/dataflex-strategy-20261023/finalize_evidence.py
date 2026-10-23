"""Bounded host finalizer for this already-authorized finite GPU experiment.

Waits for nine verified receipts, then collects CPU-only evidence and stops only
this task's verified telemetry PID. It never starts training or changes adapters.
"""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from collect_auxiliary import collect
from run_core8_suite import CONTAINER, HOST, HOST_RUN, require_evaluation, successful_folder
from summarize_results import summarize


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(args):
    return subprocess.check_output(args).decode('utf-8')


def main():
    root = HOST_RUN
    # 45-minute finite bound, with one model at a time in the existing coordinator.
    for _ in range(540):
        try:
            for name in ['BASE'] + ['G%02d' % i for i in range(8)]:
                require_evaluation(name, 64, root)
            break
        except (OSError, KeyError, ValueError, AssertionError):
            time.sleep(5)
    else:
        raise RuntimeError('Final receipts did not arrive inside finite wait; preserve all results')
    summary = summarize(root)
    (root/'results-summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    collect(root)
    examples = json.loads((root/'manual-review-examples.json').read_text(encoding='utf-8'))
    assert len(examples) == 2 and all(len(row['predictions']) == 9 for row in examples)
    expected = summary['core_runs']['G00']['source_files_sha256']
    source_code = """import hashlib,json,pathlib,dataflex
p=pathlib.Path(dataflex.__file__).parent
print(json.dumps({str(f.relative_to(p)):hashlib.sha256(f.read_bytes()).hexdigest() for f in p.rglob('*') if f.suffix in ['.py','.yaml']}))
"""
    installed = json.loads(command(['docker','exec','-e','CUDA_VISIBLE_DEVICES=',CONTAINER,'python','-c',source_code]))
    platform = Path('/sharedata/home/huruiqian/DataFlow/app/repos/dataflex/src/dataflex')
    platform_files = {str(path.relative_to(platform)): sha(path) for path in platform.rglob('*') if path.suffix in ['.py','.yaml']}
    assert installed == expected == platform_files and len(expected) == 75
    inspections = json.loads(command(['docker','inspect','--size',CONTAINER,'rui-qwen35-9b-smoke-20261022']))
    containers = []
    for item in inspections:
        containers.append({'name': item['Name'], 'id': item['Id'], 'image': item['Image'],
                           'running': item['State']['Running'], 'status': item['State']['Status'],
                           'network_mode': item['HostConfig']['NetworkMode'],
                           'gpu_requests': item['HostConfig'].get('DeviceRequests'),
                           'writable_bytes': item.get('SizeRw'), 'virtual_rootfs_bytes': item.get('SizeRootFs'),
                           'mounts': [{key: mount.get(key) for key in ['Source','Destination','RW']} for mount in item['Mounts']]})
    monitor = {'pid': 17225, 'action': 'ALREADY_EXITED_OR_IDENTITY_NOT_MATCHED'}
    proc = Path('/proc/17225/cmdline')
    if proc.exists():
        argv = proc.read_bytes().replace(b'\0',b' ').decode('utf-8',errors='replace')
        if any(str(HOST/name) in argv for name in ['driver_monitor.py', 'driver-monitor.py']):
            os.kill(17225, signal.SIGTERM)
            monitor = {'pid': 17225, 'action': 'STOPPED_OWN_VERIFIED_MONITOR', 'command': argv}
    state = {'captured_unix': time.time(), 'hostname': command(['hostname']).strip(),
             'account': command(['id','-un']).strip(), 'containers': containers,
             'gpu2_after': command(['nvidia-smi','-i','2','--query-gpu=uuid,memory.total,memory.used,memory.free','--format=csv,noheader']),
             'container_processes_after': command(['docker','top',CONTAINER]),
             'run_disk_usage': command(['du','-sh',str(root)]).strip(),
             'run_logical_bytes': int(command(['du','-sb',str(root)]).split()[0]),
             'environment_disk_usage': command(['du','-sh',str(HOST)]).strip(),
             'monitor': monitor, 'source_check': {'files': len(expected), 'installed_matches_run': True,
                                                 'platform_matches_run': True, 'files_sha256': installed},
             'task_script_sha256': {path.name: sha(path) for path in HOST.glob('*.py')},
             'compact_file_sha256': {name: sha(root/name) for name in
                 ['results-summary.json','auxiliary-accounting.json','runtime-provenance.json','manual-review-examples.json']}}
    (root/'final-state.json').write_text(json.dumps(state, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'status': summary['status'], 'optimizer_updates': summary['completed_core_optimizer_updates'],
                      'predictions': summary['completed_predictions'], 'source_files_checked': len(expected),
                      'monitor': monitor['action']}), flush=True)


if __name__ == '__main__':
    main()
