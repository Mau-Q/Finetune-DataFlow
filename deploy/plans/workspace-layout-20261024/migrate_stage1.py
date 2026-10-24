"""Frozen stage-1 migration: rename locally, retain relative compatibility links.

Execute plan/apply only against the reviewed batch. No models, app state or
active parser/batch directories are selected. Audit files live outside moved
directories. JSON plans and per-item receipts make partial execution visible.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import time


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            h.update(data)
    return h.hexdigest()


def snapshot(root):
    result = {}
    for parent, dirs, files in os.walk(str(root), followlinks=False):
        for name in sorted(dirs + files):
            path = Path(parent) / name
            rel = str(path.relative_to(root))
            info = path.lstat()
            entry = {'mode': stat.S_IMODE(info.st_mode)}
            if path.is_symlink():
                entry.update(kind='symlink', target=os.readlink(str(path)))
            elif path.is_dir():
                entry.update(kind='directory')
            elif path.is_file():
                entry.update(kind='file', bytes=info.st_size, sha256=digest(path))
            else:
                raise RuntimeError('Unsupported filesystem entry: ' + str(path))
            result[rel] = entry
    return result


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    temporary.replace(path)


def run(config, mode):
    root, audit = Path(config['root']), Path(config['audit'])
    audit.mkdir(parents=True, exist_ok=True)
    plan_path = audit / (config['location'] + '-migration-plan.json')
    if mode == 'plan':
        assert not plan_path.exists(), 'Review existing plan before rerunning'
        entries = []
        for item in config['entries']:
            old, new = root / item['source'], root / item['physical_target']
            assert old.is_dir() and not old.is_symlink(), str(old)
            assert not os.path.lexists(str(new)), str(new)
            assert root.resolve() in new.resolve().parents
            snap = snapshot(old)
            entry = dict(item)
            entry.update(snapshot=snap, root_mode=stat.S_IMODE(old.stat().st_mode),
                         files=sum(e['kind'] == 'file' for e in snap.values()),
                         bytes=sum(e.get('bytes', 0) for e in snap.values()))
            entries.append(entry)
            print('Planned', item['source'], entry['files'], flush=True)
        save(plan_path, {'status': 'FROZEN_PREMOVE', 'root': str(root), 'entries': entries,
                         'created_unix': time.time(), 'location': config['location']})
        return
    assert mode == 'apply'
    plan = json.loads(plan_path.read_bytes().decode('utf-8'))
    assert plan['root'] == str(root)
    receipt_path = audit / (config['location'] + '-migration-result.json')
    assert not receipt_path.exists(), 'Already applied'
    # Preflight the complete batch before the first mutation.
    for item in plan['entries']:
        old, new = root / item['source'], root / item['physical_target']
        assert old.is_dir() and not old.is_symlink()
        assert snapshot(old) == item['snapshot'], item['source']
        assert not os.path.lexists(str(new))
        if item.get('canonical_entry'):
            assert not os.path.lexists(str(root / item['canonical_entry']))
    receipts = []
    for item in plan['entries']:
        old, new = root / item['source'], root / item['physical_target']
        new.parent.mkdir(parents=True, exist_ok=True)
        assert old.stat().st_dev == new.parent.stat().st_dev, 'Cross-device rename not allowed'
        old.rename(new)
        try:
            old.symlink_to(os.path.relpath(str(new), str(old.parent)), target_is_directory=True)
            assert old.resolve() == new.resolve()
            assert snapshot(new) == item['snapshot'], str(new)
            assert snapshot(old) == item['snapshot'], str(old)
            assert stat.S_IMODE(new.stat().st_mode) == item['root_mode']
        except BaseException:
            if old.is_symlink():
                old.unlink()
            if not os.path.lexists(str(old)):
                new.rename(old)
            raise
        if item.get('canonical_entry'):
            canonical = root / item['canonical_entry']
            canonical.parent.mkdir(parents=True, exist_ok=True)
            canonical.symlink_to(os.path.relpath(str(new), str(canonical.parent)), target_is_directory=True)
            assert canonical.resolve() == new.resolve()
            assert snapshot(canonical) == item['snapshot']
        receipt = {k: v for k, v in item.items() if k != 'snapshot'}
        receipt.update(status='RENAMED_AND_COMPATIBILITY_VERIFIED',
                       old_link_target=os.readlink(str(old)))
        receipts.append(receipt)
        save(audit / (config['location'] + '-completed-items.json'), receipts)
        print('Migrated', item['source'], flush=True)
    result = {'status': 'STAGE1_RENAME_AND_COMPATIBILITY_VERIFIED', 'location': config['location'],
              'entries': receipts, 'files_verified': sum(x['files'] for x in receipts),
              'bytes_verified': sum(x['bytes'] for x in receipts),
              'plan_sha256': digest(plan_path), 'completed_unix': time.time(),
              'file_verification': 'All regular file SHA-256, sizes, modes, symlink text and directory entries match before navigation updates.'}
    save(receipt_path, result)
    print(json.dumps({k: v for k, v in result.items() if k != 'entries'}), flush=True)


if __name__ == '__main__':
    config = json.loads(Path(sys.argv[1]).read_text())
    run(config, sys.argv[2])
