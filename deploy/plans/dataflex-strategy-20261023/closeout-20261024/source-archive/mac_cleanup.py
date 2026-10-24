"""Keep baseline and newest three backup ZIPs; retain all other backup evidence."""
import hashlib
import json
from pathlib import Path
import sys
import time
import zipfile

ROOT = Path('/Users/rui/Documents/DataFlow/repos/dataflow-webui/backend/backups/datasets')
AUDIT = Path('/Users/rui/Documents/DataFlow/outputs/closeout-20261024')


def entry(p):
    assert p.is_file() and not p.is_symlink() and p.resolve() == p
    h = hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda: f.read(4 * 1024 * 1024), b''):
            h.update(b)
    return {'path': str(p.relative_to(ROOT)), 'bytes': p.stat().st_size, 'sha256': h.hexdigest()}


def save(name, value):
    (AUDIT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def plan():
    assert not (AUDIT / 'mac-plan.json').exists()
    snapshots = sorted(ROOT.glob('snapshot-*.zip'))
    keep = set(snapshots[-3:] + [p for p in snapshots if 'baseline' in p.name])
    assert len(snapshots) == 25 and len(keep) == 4
    for p in keep:
        with zipfile.ZipFile(p) as z:
            assert z.testzip() is None, p.name
    remove = set(snapshots) - keep
    data = {'status': 'PREDELETE_VERIFIED', 'created_unix': time.time(),
            'root': str(ROOT), 'delete': [entry(p) for p in sorted(remove)],
            'preserved': [entry(p) for p in sorted(ROOT.rglob('*')) if p.is_file() and p not in remove],
            'kept_zip_integrity_verified': [p.name for p in sorted(keep)]}
    data['delete_bytes'] = sum(e['bytes'] for e in data['delete'])
    save('mac-plan.json', data)
    print(json.dumps({'delete_count': len(data['delete']), 'delete_bytes': data['delete_bytes'],
                      'keep': data['kept_zip_integrity_verified']}))


def apply():
    assert not (AUDIT / 'mac-result.json').exists()
    data = json.loads((AUDIT / 'mac-plan.json').read_text())
    expected = set(e['path'] for e in data['delete'] + data['preserved'])
    assert {str(p.relative_to(ROOT)) for p in ROOT.rglob('*') if p.is_file()} == expected
    for e in data['delete'] + data['preserved']:
        assert entry(ROOT / e['path']) == e, e['path']
    with (AUDIT / 'mac-deleted.jsonl').open('x') as log:
        for e in data['delete']:
            (ROOT / e['path']).unlink()
            log.write(json.dumps(e) + '\n')
            log.flush()
    for e in data['preserved']:
        assert entry(ROOT / e['path']) == e, e['path']
    assert all(not (ROOT / e['path']).exists() for e in data['delete'])
    data = {'status': 'CLEANUP_AND_PRESERVATION_VERIFIED', 'completed_unix': time.time(),
            'deleted_files': len(data['delete']), 'deleted_bytes': data['delete_bytes'],
            'preserved_files_verified': len(data['preserved']),
            'kept_zip_integrity_verified': data['kept_zip_integrity_verified']}
    save('mac-result.json', data)
    print(json.dumps(data))


if __name__ == '__main__':
    {'plan': plan, 'apply': apply}[sys.argv[1]]()
