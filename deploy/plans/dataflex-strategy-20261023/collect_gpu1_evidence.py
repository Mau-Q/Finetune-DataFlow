"""Host Python 3.6: compact receipts only; weights and full traces remain on school."""
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path
from run_gpu1_cohort import WORK, HOST_RUN, LOG, GPU, CONTAINER


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(8*1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def out(args):
    return subprocess.check_output(args).decode().strip()


def main():
    root = HOST_RUN/'gpu1-core8-20261024'
    gates = HOST_RUN/'gpu1-gates-20261024'
    result = json.loads((root/'results-summary.json').read_text())
    assert result['status'] == 'GPU1_FRESH_CORE8_AND_NINE_MODEL_EVALUATION_VERIFIED'
    assert out(['hostname']) == 'node01' and out(['id', '-un']) == 'huruiqian'
    destination = WORK/'final-compact'; destination.mkdir(exist_ok=False)
    copies = {
        root/'results-summary.json': 'results-summary.json', root/'report.md': 'report.md',
        root/'cohort-plan.json': 'cohort-plan.json', root/'prepare-source.py': 'source-archive/core-prepare.py',
        gates/'prepare-source.py': 'source-archive/gates-prepare.py', gates/'gate-verdict.json': 'gate-verdict.json',
        gates/'frozen-identity.json': 'frozen-identity.json', gates/'bootstrap-order.json': 'bootstrap-order.json',
        gates/'bootstrap-order-detail.json': 'bootstrap-order-detail.json',
        gates/'evaluation/GATE2-B2/score-batch-check.json': 'score-batch-check.json',
        gates/'evaluation/GATE2-B1/metrics.json': 'gate-b1-reload.json',
        gates/'evaluation/GATE2-B2/metrics.json': 'gate-b2-reload.json',
        WORK/'migration/migration-receipt.json': 'migration-receipt.json',
        WORK/'school-contracts-fixed.txt': 'school-contracts.txt', LOG/'events.jsonl': 'commands-events.jsonl',
        LOG/'gates-prepare-preflight-failed.log': 'failures/prepare-preflight-1.log',
        LOG/'gates-prepare-preflight-failed2.log': 'failures/prepare-preflight-2.log'}
    for source, name in copies.items():
        target = destination/name; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(source), str(target))
        assert sha(source) == sha(target)
    # Hash full evidence in place; never copy adapters or full predictions to Mac.
    full = {}
    for folder in [gates, root]:
        for path in sorted(folder.rglob('*')):
            if (path.is_file() and not path.is_symlink() and path.suffix in ['.json', '.jsonl', '.yaml', '.safetensors']
                    and not any(part.startswith('checkpoint-') for part in path.parts)):
                full[str(path)] = sha(path)
    for path in sorted(LOG.glob('*')):
        if path.is_file():
            full[str(path)] = sha(path)
    containers = {}
    for name in [CONTAINER, 'rui-dataflex-strategy-gpu2-20261023', 'rui-qwen35-9b-smoke-20261022']:
        inspected = json.loads(out(['docker', 'inspect', name]))[0]
        top = out(['docker', 'top', name])
        if name == CONTAINER:
            assert len(top.splitlines()) == 2 and 'sleep infinity' in top, top
        containers[name] = {'id': inspected['Id'], 'image_id': inspected['Image'], 'top': top,
                            'network': inspected['HostConfig']['NetworkMode'],
                            'gpu_requests': inspected['HostConfig']['DeviceRequests']}
    state = {'timestamp': time.time(), 'hostname': 'node01', 'account': 'huruiqian', 'containers': containers,
             'gpu': out(['nvidia-smi', '--query-gpu=index,uuid,memory.used,memory.free,utilization.gpu', '--format=csv']),
             'gpu_processes': out(['nvidia-smi', '--query-compute-apps=gpu_uuid,pid,process_name,used_memory', '--format=csv']),
             'preserved_old_models_and_containers': True, 'new_container_idle_no_model_process': True,
             'gpu_uuid': GPU, 'school_artifact_root': str(root)}
    (destination/'final-state.json').write_text(json.dumps(state, indent=2)+'\n')
    manifest = {'status': 'COMPACT_EVIDENCE_VERIFIED', 'school_artifact_root': str(root),
                'full_evidence_sha256': full,
                'script_sha256': {p.name: sha(p) for p in WORK.glob('*.py')},
                'compact_files': {str(p.relative_to(destination)): sha(p) for p in destination.rglob('*') if p.is_file()},
                'weights_full_predictions_and_raw_gradients_copied_to_mac': False}
    (destination/'evidence-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(json.dumps({'status': manifest['status'], 'compact_files': len(manifest['compact_files']),
                      'full_evidence_files_hashed': len(full), 'manifest_sha256': sha(destination/'evidence-manifest.json')}), flush=True)


if __name__ == '__main__':
    main()
