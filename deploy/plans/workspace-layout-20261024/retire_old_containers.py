"""Node01-only archive/delete gate for two explicitly authorized stopped containers."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time

ROOT = Path('/sharedata/home/huruiqian/DataFlow')
AUDIT = ROOT / 'runs/maintenance/2026-10-24-retired-containers'
TARGETS = {'rui-dataflex-strategy-gpu2-20261023': 'rui/dataflex-strategy:20261024-gpu1-actual',
           'rui-qwen35-9b-smoke-20261022': 'rui/qwen35-training:20261022'}
KEEP = ['rui-dataflex-strategy-gpu1-20261024', 'rui-dataflow-platform-20261022',
        'rui-dataflow-https-20261022']


def output(args):
    return subprocess.check_output(args).decode()


def inspect(name, size=False):
    return json.loads(output(['docker', 'inspect'] + (['--size'] if size else []) + [name]))[0]


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for b in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def save(path, data):
    assert not path.exists(), str(path)
    with os.fdopen(os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as f:
        json.dump(data, f, ensure_ascii=True, indent=2)
        f.write('\n')


def resources():
    models = {}
    for p in sorted((ROOT / 'models').rglob('*')):
        if p.is_file():
            s = p.stat()
            models[str(p.relative_to(ROOT))] = [s.st_size, s.st_mtime_ns, s.st_ino]
    adapters = {}
    for i in range(8):
        p = ROOT / ('runs/dataflex/2026-10-24-core8-flow-check/G%02d/attempt1/output/adapter_model.safetensors' % i)
        adapters[str(p.relative_to(ROOT))] = sha(p)
    images = sorted(set(output(['docker', 'image', 'ls', '--no-trunc', '--format', '{{.Repository}}:{{.Tag}}|{{.ID}}']).splitlines()))
    volumes = {}
    for name in output(['docker', 'volume', 'ls', '-q']).splitlines():
        d = json.loads(output(['docker', 'volume', 'inspect', name]))[0]
        volumes[name] = {k: d.get(k) for k in ['Name', 'Driver', 'Mountpoint', 'Options', 'Labels']}
    keep = {n: inspect(n) for n in KEEP}
    return {'models': models, 'adapters': adapters, 'images': images, 'volumes': volumes, 'keep': keep}


def helper(name, d, reference, mode):
    upper = d['GraphDriver']['Data']['UpperDir']
    assert d['GraphDriver']['Name'] == 'overlay2' and upper.startswith('/home/docker-data_node01/overlay2/')
    diff = output(['docker', 'diff', name]).splitlines()
    assert not any('/.ssh' in x for x in diff), 'Private SSH paths require a separate handling decision'
    config = {'name': name, 'id': d['Id'], 'base_image': d['Image'],
              'reference_image': reference, 'uid': os.getuid(), 'gid': os.getgid(),
              'deleted_paths': [x[2:] for x in diff if x.startswith('D ')], 'mode': mode}
    payload = 'CONFIG=' + ascii(config) + '\n' + HELPER_SOURCE
    helper_name = 'rui-retired-layer-' + ('gpu2' if 'gpu2' in name else 'smoke') + '-' + mode + '-20261024'
    assert not output(['docker', 'ps', '-a', '--filter', 'name=^/' + helper_name + '$', '--format', '{{.Names}}']).strip()
    command = ['docker', 'run', '--rm', '-i', '--pull=never', '--name', helper_name,
               '--network', 'none', '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
               '-e', 'NVIDIA_VISIBLE_DEVICES=void', '-e', 'CUDA_VISIBLE_DEVICES=-1',
               '--mount', 'type=bind,source=' + upper + ',target=/retired-layer,readonly',
               '--mount', 'type=bind,source=' + str(AUDIT / name) + ',target=/archive' + (',readonly' if mode == 'verify' else ''),
               '--entrypoint', 'python', reference, '-']
    raw = subprocess.check_output(command, input=payload.encode('ascii'))
    assert not output(['docker', 'ps', '-a', '--filter', 'name=^/' + helper_name + '$', '--format', '{{.Names}}']).strip()
    return json.loads(raw.decode())


def archive():
    os.umask(0o077)
    AUDIT.mkdir(mode=0o700, exist_ok=False)
    before = resources()
    save(AUDIT / 'preservation-before.private.json', before)
    results = []
    for name, tag in TARGETS.items():
        d = inspect(name, size=True)
        assert d['State']['Status'] == 'exited'
        folder = AUDIT / name
        folder.mkdir(mode=0o700)
        save(folder / 'container-inspect.private.json', d)
        save(folder / 'docker-diff.json', output(['docker', 'diff', name]).splitlines())
        proc = subprocess.Popen(['docker', 'logs', '--timestamps', name], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        with gzip.open(str(folder / 'container-logs.private.gz'), 'wb') as f:
            shutil.copyfileobj(proc.stdout, f)
        assert proc.wait() == 0
        with gzip.open(str(folder / 'container-logs.private.gz'), 'rb') as f:
            h = hashlib.sha256()
            log_bytes = 0
            for b in iter(lambda: f.read(1024 * 1024), b''):
                h.update(b); log_bytes += len(b)
        reference = json.loads(output(['docker', 'image', 'inspect', tag]))[0]['Id']
        print('Auditing stopped upper layer:', name, flush=True)
        result = helper(name, d, reference, 'archive')
        assert result['status'] == 'UNIQUE_FILES_ARCHIVED_AND_READBACK_VERIFIED'
        result.update(writable_layer_bytes=d['SizeRw'], reference_tag=tag,
                      archive_directory=str(folder), inspect_sha256=sha(folder / 'container-inspect.private.json'),
                      log_archive_sha256=sha(folder / 'container-logs.private.gz'),
                      log_content_sha256=h.hexdigest(), log_content_bytes=log_bytes)
        results.append(result)
        print(json.dumps(result), flush=True)
    summary = {'status': 'BOTH_ARCHIVES_VERIFIED_NO_CONTAINERS_REMOVED', 'containers': results,
               'archive_root': str(AUDIT), 'private_records_not_for_git': True}
    save(AUDIT / 'archive-summary.json', summary)


def remove():
    before = json.loads((AUDIT / 'preservation-before.private.json').read_text())
    summary = json.loads((AUDIT / 'archive-summary.json').read_text())
    assert summary['status'] == 'BOTH_ARCHIVES_VERIFIED_NO_CONTAINERS_REMOVED'
    assert not (AUDIT / 'removal-result.json').exists()
    # Reverify both archives and stopped layers before removing either container.
    for item in summary['containers']:
        name = item['container']; folder = AUDIT / name
        d = inspect(name, size=True)
        original = json.loads((folder / 'container-inspect.private.json').read_text())
        assert d['Id'] == original['Id'] and d['Image'] == original['Image']
        assert d['State']['Status'] == 'exited'
        assert sha(folder / 'container-inspect.private.json') == item['inspect_sha256']
        assert sha(folder / 'container-logs.private.gz') == item['log_archive_sha256']
        result = helper(name, d, item['reference_image'], 'verify')
        assert result['status'] == 'ARCHIVE_AND_STOPPED_LAYER_REVERIFIED'
        print(json.dumps(result), flush=True)
    removed = []
    for item in summary['containers']:
        d = inspect(item['container'])
        assert d['Id'] == item['container_id'] and d['State']['Status'] == 'exited'
        # No force, no -v: images, bind mounts and named/anonymous volumes retained.
        output(['docker', 'rm', d['Id']])
        removed.append({'name': item['container'], 'id': d['Id']})
        save(AUDIT / ('removed-' + item['container'] + '.json'), removed[-1])
    after = resources()
    assert before['models'] == after['models']
    assert before['adapters'] == after['adapters']
    assert set(before['images']) <= set(after['images'])
    assert all(after['volumes'].get(n) == v for n, v in before['volumes'].items())
    for name, d in before['keep'].items():
        current = after['keep'][name]
        assert all(d[k] == current[k] for k in ['Id', 'Image'])
        assert d['State']['Status'] == current['State']['Status']
        canonical = lambda ms: sorted(json.dumps(m, sort_keys=True) for m in ms)
        assert canonical(d['Mounts']) == canonical(current['Mounts'])
    current_ids = set(output(['docker', 'ps', '-a', '--no-trunc', '--format', '{{.ID}}']).splitlines())
    assert all(x['id'] not in current_ids for x in removed)
    result = {'status': 'TWO_RETIRED_CONTAINERS_REMOVED_PRESERVATION_VERIFIED',
              'removed': removed, 'retained_containers': [{'name': n, 'id': d['Id'], 'status': d['State']['Status'], 'image': d['Image']} for n, d in after['keep'].items()],
              'image_references_preserved': len(before['images']), 'volumes_preserved': len(before['volumes']),
              'model_files_metadata_unchanged': len(before['models']), 'final_adapters_sha256_unchanged': after['adapters'],
              'writable_layer_bytes_removed': sum(x['writable_layer_bytes'] for x in summary['containers']),
              'archive_root': str(AUDIT), 'completed_unix': time.time(),
              'gpu_training_started': False, 'docker_rm_used_volume_flag': False, 'images_deleted': False}
    save(AUDIT / 'removal-result.json', result)
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    assert socket.gethostname() == 'node01' and output(['id', '-un']).strip() == 'huruiqian'
    {'archive': archive, 'remove': remove}[MODE]()
