"""Audit an owned stopped container's read-only upper layer against a saved image.

Run only in the reviewed helper container: /retired-layer is the target's
read-only UpperDir; /archive is a new private archive directory. No model is
loaded and the original containers are never started. JSON inventory includes
deletions/special entries; unique regular files and links are archived and
read back before a verified receipt is emitted.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import tarfile
import time


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def attributes(path):
    return {name: os.getxattr(str(path), name, follow_symlinks=False).hex()
            for name in os.listxattr(str(path), follow_symlinks=False)}


def audit(config):
    os.umask(0o077)
    upper, archive = Path('/retired-layer'), Path('/archive')
    assert upper.is_dir() and archive.is_dir()
    assert not (archive / 'layer-result.json').exists()
    inventory, selected = [], []
    counts = {}
    comparison_bytes = archived_bytes = 0
    for parent, dirs, files in os.walk(str(upper), followlinks=False):
        for name in sorted(dirs + files):
            p = Path(parent) / name
            rel = str(p.relative_to(upper))
            # The preflight rejects SSH private-key paths before any content read.
            assert '.ssh' not in p.relative_to(upper).parts
            s = p.lstat()
            e = {'path': rel, 'mode': stat.S_IMODE(s.st_mode), 'uid': s.st_uid,
                 'gid': s.st_gid, 'mtime_ns': s.st_mtime_ns, 'xattrs': attributes(p)}
            ref = Path('/') / rel
            rs = ref.lstat() if os.path.lexists(str(ref)) else None
            meta_equal = bool(rs and stat.S_IMODE(rs.st_mode) == e['mode']
                              and rs.st_uid == e['uid'] and rs.st_gid == e['gid'])
            if stat.S_ISREG(s.st_mode):
                e.update(kind='file', bytes=s.st_size, sha256=sha(p))
                matches = bool(meta_equal and stat.S_ISREG(rs.st_mode)
                               and rs.st_size == s.st_size and sha(ref) == e['sha256']
                               and attributes(ref) == e['xattrs'])
                e['disposition'] = 'covered_by_retained_image' if matches else 'unique_archived'
                if matches:
                    comparison_bytes += s.st_size
                else:
                    selected.append(e)
                    archived_bytes += s.st_size
            elif stat.S_ISLNK(s.st_mode):
                e.update(kind='symlink', target=os.readlink(str(p)))
                matches = bool(meta_equal and stat.S_ISLNK(rs.st_mode)
                               and os.readlink(str(ref)) == e['target']
                               and attributes(ref) == e['xattrs'])
                e['disposition'] = 'covered_by_retained_image' if matches else 'unique_archived'
                if not matches:
                    selected.append(e)
            elif stat.S_ISDIR(s.st_mode):
                e.update(kind='directory', disposition='directory_metadata_recorded')
            else:
                e.update(kind='special', rdev=s.st_rdev,
                         disposition='special_or_whiteout_metadata_recorded')
            inventory.append(e)
            key = e['kind'] + ':' + e['disposition']
            counts[key] = counts.get(key, 0) + 1
    tar_path = archive / 'unique-files.tar.gz'
    with tarfile.open(str(tar_path), 'w:gz') as bundle:
        for e in selected:
            p = upper / e['path']
            info = tarfile.TarInfo(e['path'])
            info.mode, info.uid, info.gid = e['mode'], e['uid'], e['gid']
            info.mtime = e['mtime_ns'] / 1e9
            if e['kind'] == 'file':
                info.size = e['bytes']
                with p.open('rb') as stream:
                    bundle.addfile(info, stream)
            else:
                info.type, info.linkname = tarfile.SYMTYPE, e['target']
                bundle.addfile(info)
    expected = {e['path']: e for e in selected}
    seen = set()
    with tarfile.open(str(tar_path), 'r:gz') as bundle:
        for member in bundle:
            assert not member.name.startswith('/') and '..' not in Path(member.name).parts
            e = expected[member.name]
            assert member.name not in seen
            assert (member.mode, member.uid, member.gid) == (e['mode'], e['uid'], e['gid'])
            if e['kind'] == 'file':
                h = hashlib.sha256()
                stream = bundle.extractfile(member)
                assert stream is not None and member.size == e['bytes']
                for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
                    h.update(block)
                assert h.hexdigest() == e['sha256'], member.name
            else:
                assert member.issym() and member.linkname == e['target']
            seen.add(member.name)
    assert seen == set(expected)
    record = {'container': config['name'], 'base_image': config['base_image'],
              'reference_image': config['reference_image'], 'entries': inventory,
              'deleted_paths': config['deleted_paths'],
              'recovery_note': 'Base image and reference image retained. Manifest records original upper-layer metadata, image-covered paths, unique archive paths, deletions and whiteouts. No full container reconstruction or training was performed.'}
    manifest = archive / 'filesystem-inventory.json'
    manifest.write_text(json.dumps(record, ensure_ascii=True, indent=2) + '\n')
    result = {'status': 'UNIQUE_FILES_ARCHIVED_AND_READBACK_VERIFIED',
              'container': config['name'], 'container_id': config['id'],
              'reference_image': config['reference_image'], 'base_image': config['base_image'],
              'upper_entries': len(inventory), 'counts': counts,
              'image_covered_file_bytes': comparison_bytes, 'unique_file_bytes': archived_bytes,
              'archive_members_verified': len(selected), 'deleted_paths_recorded': len(config['deleted_paths']),
              'archive_bytes': tar_path.stat().st_size, 'archive_sha256': sha(tar_path),
              'filesystem_inventory_bytes': manifest.stat().st_size,
              'filesystem_inventory_sha256': sha(manifest),
              'gpu_access': 'disabled', 'network': 'none', 'source_mount': 'read-only',
              'completed_unix': time.time()}
    (archive / 'layer-result.json').write_text(json.dumps(result, indent=2) + '\n')
    # Only newly created archive files are assigned to the requesting host user.
    for p in [tar_path, manifest, archive / 'layer-result.json']:
        os.chown(str(p), config['uid'], config['gid'])
        os.chmod(str(p), 0o600)
    print(json.dumps(result), flush=True)


def verify_existing(config):
    upper, archive = Path('/retired-layer'), Path('/archive')
    result = json.loads((archive / 'layer-result.json').read_text())
    assert sha(archive / 'unique-files.tar.gz') == result['archive_sha256']
    assert sha(archive / 'filesystem-inventory.json') == result['filesystem_inventory_sha256']
    inventory = json.loads((archive / 'filesystem-inventory.json').read_text())['entries']
    seen = set()
    for parent, dirs, files in os.walk(str(upper), followlinks=False):
        seen.update(str((Path(parent) / name).relative_to(upper)) for name in dirs + files)
    assert seen == {e['path'] for e in inventory}
    regular = 0
    for e in inventory:
        p = upper / e['path']
        s = p.lstat()
        assert (stat.S_IMODE(s.st_mode), s.st_uid, s.st_gid) == (e['mode'], e['uid'], e['gid'])
        assert attributes(p) == e['xattrs'], e['path']
        if e['kind'] == 'file':
            assert stat.S_ISREG(s.st_mode) and s.st_size == e['bytes']
            assert sha(p) == e['sha256'], e['path']
            regular += 1
        elif e['kind'] == 'symlink':
            assert stat.S_ISLNK(s.st_mode) and os.readlink(str(p)) == e['target']
        elif e['kind'] == 'directory':
            assert stat.S_ISDIR(s.st_mode)
        else:
            assert not stat.S_ISREG(s.st_mode) and s.st_rdev == e['rdev']
    print(json.dumps({'status': 'ARCHIVE_AND_STOPPED_LAYER_REVERIFIED',
                      'container': config['name'], 'regular_files_reverified': regular}), flush=True)


if __name__ == '__main__':
    {'archive': audit, 'verify': verify_existing}[CONFIG['mode']](CONFIG)
