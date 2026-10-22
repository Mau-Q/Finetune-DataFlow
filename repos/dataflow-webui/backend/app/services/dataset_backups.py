"""Verified local snapshots, isolated restore and startup recovery for dataset storage."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import tempfile
import threading
import zipfile
from contextlib import closing
from datetime import datetime, timezone
from loguru import logger
from app.services.dataset_database import DatasetDatabase
from app.services.dataset_persistence import dataset_lock, register_backups, sync_directory, atomic_write


def digest(data):
    return hashlib.sha256(data).hexdigest()


def stamp():
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')


class DatasetBackups:
    def __init__(self, root, directory=None, keep=24, interval=3600):
        self.root = Path(root).resolve()
        self.directory = Path(directory or self.root.parent / 'backups/datasets').resolve()
        if self.directory.is_relative_to(self.root):
            raise ValueError('Backup directory must be outside the data directory')
        self.directory.mkdir(parents=True, exist_ok=True)
        self.directory.chmod(0o700)
        self.keep = max(2, keep)
        self.interval = interval
        self.last_error = None
        self.last_recovery = None
        self._stop = threading.Event()
        self._dirty = threading.Event()
        self._wake = threading.Event()
        self._thread = None

    @staticmethod
    def verify(archive):
        with zipfile.ZipFile(archive) as bundle:
            manifest = json.loads(bundle.read('manifest.json'))
            if manifest.get('format') != 1 or not isinstance(manifest.get('files'), dict):
                raise ValueError('Invalid dataset backup manifest')
            expected = set(manifest['files']) | {'manifest.json'}
            if set(bundle.namelist()) != expected or len(bundle.namelist()) != len(expected):
                raise ValueError('Backup members do not match the manifest')
            for name, metadata in manifest['files'].items():
                path = PurePosixPath(name)
                if len(path.parts)<2 or path.is_absolute() or '..' in path.parts or path.parts[0] not in ('data','external'):
                    raise ValueError('Unsafe backup path')
                info = bundle.getinfo(name)
                if info.file_size != metadata['size']:
                    raise ValueError(f'Backup size mismatch: {name}')
                if digest(bundle.read(name)) != metadata['sha256']:
                    raise ValueError(f'Backup hash mismatch: {name}')
            return manifest

    def archives(self):
        return sorted(self.directory.glob('snapshot-*.zip'), reverse=True)

    def latest(self, sqlite_only=False):
        for archive in self.archives():
            try:
                manifest = self.verify(archive)
                if sqlite_only and 'data/datasets.sqlite3' not in manifest['files']:
                    continue
                return archive, manifest
            except (ValueError, OSError, zipfile.BadZipFile, KeyError, TypeError):
                logger.warning('Skipping invalid dataset backup: {}', archive.name)
        return None, None

    def _files(self):
        # Dataset-owned blobs and the legacy import source only. Runtime templates,
        # model/service configuration and task history are outside dataset recovery.
        candidates = list((self.root / 'library').rglob('*'))
        candidates.append(self.root / 'data_registry.yaml')
        files = {p.resolve(): 'data/' + p.relative_to(self.root).as_posix()
                 for p in candidates if p.is_file()
                 and not p.name.endswith(('.lock', '-wal', '-shm'))
                 and not p.name.startswith('.pending-')}
        database = self.root / 'datasets.sqlite3'
        records = []
        self.unresolved_external = []
        if database.exists():
            with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)) as con:
                records = [json.loads(r[0]) for r in con.execute('SELECT payload FROM source_datasets')]
        else:
            import yaml
            path = self.root / 'data_registry.yaml'
            if path.exists():
                records = list(yaml.safe_load(path.read_text())['datasets'].values())
        def add(path):
            path = Path(path).resolve()
            if path not in files:
                if not path.is_file():
                    raise ValueError(f'Registered file is missing: {path}')
                files[path] = ('data/' + path.relative_to(self.root).as_posix() if path.is_relative_to(self.root)
                               else 'external/'+digest(str(path).encode())[:16]+'/'+path.name)
        for record in records:
            path = Path(record['root']).resolve()
            add(path)
            if path.suffix.lower() == '.jsonl':
                with path.open(encoding='utf-8-sig',errors='replace') as handle:
                    for line in handle:
                        try:
                            row = json.loads(line)
                        except ValueError:
                            continue
                        if isinstance(row,dict) and isinstance(row.get('source'),str):
                            source = Path(row['source'])
                            if source.is_absolute():
                                if source.is_file():
                                    add(source)
                                elif not source.is_relative_to(self.root):
                                    self.unresolved_external.append(str(source))
        return files

    def snapshot(self, reason='manual'):
        with dataset_lock(self.root):
            if not (self.root/'datasets.sqlite3').is_file():
                raise ValueError('Dataset database is missing; refusing an empty backup')
            self.validate(self.root)
            files = self._files()
            observed = {p:(p.stat().st_mtime_ns,p.stat().st_size) for p in files}
            temporary = self.directory / ('.pending-'+stamp()+'.zip')
            manifest = dict(format=1, created_at=stamp(), reason=reason, source_root=str(self.root),
                            unresolved_external=sorted(set(self.unresolved_external)), files={})
            try:
                with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as bundle:
                    for path,name in sorted(files.items(),key=lambda item:item[1]):
                        content = path.read_bytes()
                        bundle.writestr(name,content)
                        manifest['files'][name] = dict(sha256=digest(content),size=len(content),original_path=str(path))
                    if (self.root/'datasets.sqlite3').exists():
                        with tempfile.TemporaryDirectory(dir=self.directory) as temp:
                            copy = Path(temp)/'datasets.sqlite3'
                            DatasetDatabase(self.root).backup(copy)
                            content = copy.read_bytes()
                        bundle.writestr('data/datasets.sqlite3',content)
                        manifest['files']['data/datasets.sqlite3'] = dict(sha256=digest(content),size=len(content),original_path=str(self.root/'datasets.sqlite3'))
                    bundle.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,sort_keys=True))
                if files != self._files() or any((p.stat().st_mtime_ns,p.stat().st_size)!=state for p,state in observed.items()):
                    raise ValueError('Files changed during backup; retry required')
                self.verify(temporary)
                # Never copy an open SQLite/WAL file: the DB above is an online backup image.
                # Windows requires a writable descriptor for os.fsync.
                with temporary.open('r+b') as handle:
                    os.fsync(handle.fileno())
                target = self.directory / ('snapshot-'+manifest['created_at']+'.zip')
                os.replace(temporary,target)
                target.chmod(0o600)
                sync_directory(self.directory)
                self.last_error = None
                # Baseline and pre-recovery evidence are retained independently of rotation.
                rotating = [p for p in self.archives() if 'baseline' not in p.name]
                for old in rotating[self.keep:]:
                    old.unlink()
                return target
            finally:
                temporary.unlink(missing_ok=True)

    @staticmethod
    def validate(root, manifest=None, bundle_root=None):
        """Validate DB relations and every dataset's required media/exports at either location."""
        root = Path(root)
        original = Path(manifest['source_root']) if manifest else root
        copied = {m['original_path']:Path(bundle_root)/name for name,m in manifest['files'].items()} if manifest else {}
        def resolve(path):
            path = Path(path)
            if str(path) in copied:
                return copied[str(path)]
            if path.is_relative_to(original):
                return root/path.relative_to(original)
            # Isolation verification must not accidentally read the live external original.
            if manifest:
                raise ValueError(f'Backup is missing a referenced file: {path}')
            return path
        db = root/'datasets.sqlite3'
        if not db.exists():
            # Legacy baseline is kept for manual recovery; new automatic snapshots use SQLite.
            if manifest and 'data/datasets.sqlite3' in manifest['files']:
                raise ValueError('Dataset database is missing')
            return
        with closing(sqlite3.connect(db.resolve().as_uri() + '?mode=ro',uri=True)) as con:
            if con.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or con.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('Dataset database integrity check failed')
            materials = {rid:json.loads(payload) for rid,payload in con.execute('SELECT id,payload FROM materials')}
            for record in materials.values():
                blob = resolve(original/'library/materials'/record['blob_name'])
                if not blob.is_file() or digest(blob.read_bytes())!=record['sha256']:
                    raise ValueError(f'Material is missing or changed: {record["id"]}')
            from app.services.data_library import DataLibrary
            validator = DataLibrary.__new__(DataLibrary)
            for did,metadata in con.execute('SELECT id,metadata FROM drafts'):
                rec = json.loads(metadata)
                bindings = dict(con.execute('SELECT reference,material_id FROM draft_media WHERE draft_id=?',(did,)))
                for payload, in con.execute('SELECT payload FROM samples WHERE draft_id=?',(did,)):
                    refs = validator._validate_row(json.loads(payload),rec['modality'],rec.get('training_type','sft'))
                    if any(ref not in bindings or materials[bindings[ref]]['kind']!='image' for ref in refs):
                        raise ValueError(f'Draft has missing media: {did}')
            for payload, in con.execute('SELECT payload FROM source_datasets'):
                record = json.loads(payload)
                path = resolve(record['root'])
                if not path.is_file():
                    raise ValueError(f'Dataset input is missing: {record["id"]}')
                if path.suffix.lower()=='.jsonl':
                    for line in path.read_text('utf-8-sig',errors='replace').splitlines():
                        try:
                            row = json.loads(line)
                        except ValueError:
                            continue
                        if isinstance(row,dict) and isinstance(row.get('source'),str) and Path(row['source']).is_absolute():
                            suffix = Path(row['source']).suffix.lower()
                            if suffix in {'.pdf','.png','.jpg','.jpeg','.gif','.webp','.bmp'}:
                                if manifest and row['source'] in manifest.get('unresolved_external',[]):
                                    continue
                                required = manifest is not None or Path(row['source']).is_relative_to(original) or row.get('material_id')
                                if required and not resolve(row['source']).is_file():
                                    raise ValueError(f'Dataset source is missing: {record["id"]}')
            for payload, in con.execute('SELECT payload FROM releases'):
                rec = json.loads(payload)
                for suffix,expected in rec['files'].items():
                    blob = resolve(original/'library/releases'/(rec['id']+suffix))
                    if not blob.is_file() or digest(blob.read_bytes())!=expected:
                        raise ValueError(f'Release file is missing or changed: {rec["id"]}')

    def restore(self, archive, target):
        """Extract to a new directory only; preserve exact bytes, paths are resolved by verification."""
        manifest = self.verify(archive)
        target = Path(target).resolve()
        if target.exists():
            raise ValueError('Restore target already exists; choose a new directory')
        if target.is_relative_to(self.root) or target == self.directory:
            raise ValueError('Restore target overlaps live storage')
        target.parent.mkdir(parents=True,exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix='.dataset-restore-',dir=target.parent))
        try:
            with zipfile.ZipFile(archive) as bundle:
                for name in manifest['files']:
                    destination = staging/name
                    destination.parent.mkdir(parents=True,exist_ok=True)
                    atomic_write(destination,bundle.read(name))
                atomic_write(staging/'manifest.json',json.dumps(manifest,ensure_ascii=False).encode())
            self.validate(staging/'data',manifest,staging)
            os.replace(staging,target)
            sync_directory(target.parent)
            return target
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    def recover_if_needed(self, archive=None):
        explicit = archive is not None
        if explicit:
            archive = Path(archive)
            manifest = self.verify(archive)
        else:
            archive,manifest = self.latest(sqlite_only=True)
        try:
            if explicit:
                raise ValueError('Explicit restore of selected snapshot')
            if manifest and 'data/datasets.sqlite3' in manifest['files'] and not (self.root/'datasets.sqlite3').exists():
                raise ValueError('Dataset database is missing')
            self.validate(self.root)
            return None
        except (ValueError,OSError,sqlite3.DatabaseError,KeyError) as failure:
            # Select a fully verified snapshot, not merely a zip with a plausible filename.
            if archive is None or 'data/datasets.sqlite3' not in manifest['files']:
                raise RuntimeError('Dataset storage is damaged and no SQLite backup is available') from failure
            with dataset_lock(self.root):
                target = self.directory/('recovery-'+stamp())
                self.restore(archive,target)
                # Refuse to overwrite external originals that changed after this backup.
                for name,info in manifest['files'].items():
                    if name.startswith('external/'):
                        path = Path(info['original_path'])
                        if path.exists() and digest(path.read_bytes())!=info['sha256']:
                            raise RuntimeError(f'External file changed; preserved for manual recovery: {path}')
                # Recovery replaces dataset-owned paths, while preserving unrelated
                # runtime/config/history files absent from the scoped snapshot.
                if self.root.exists():
                    for existing in self.root.rglob('*'):
                        relative = existing.relative_to(self.root)
                        destination = target/'data'/relative
                        if (relative.parts[0] == 'library' or relative.as_posix() in
                                {'datasets.sqlite3', 'datasets.sqlite3-wal', 'datasets.sqlite3-shm', 'datasets.sqlite3-journal'}):
                            continue
                        if destination.exists() or destination.is_symlink():
                            continue
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        if existing.is_symlink():
                            # Preserve even broken links without following or copying
                            # external runtime trees into the dataset recovery scope.
                            destination.symlink_to(os.readlink(existing), target_is_directory=existing.is_dir())
                        elif existing.is_dir():
                            destination.mkdir(exist_ok=True)
                        elif existing.is_file():
                            shutil.copy2(existing, destination)
                quarantine = self.directory/('quarantine-'+stamp())
                if self.root.exists():
                    os.replace(self.root,quarantine)
                try:
                    os.replace(target/'data',self.root)
                except BaseException:
                    if quarantine.exists():
                        os.replace(quarantine,self.root)
                    raise
                for name,info in manifest['files'].items():
                    if name.startswith('external/') and not Path(info['original_path']).exists():
                        atomic_write(info['original_path'],(target/name).read_bytes())
                sync_directory(self.root.parent)
                self.validate(self.root)
                self.last_recovery = dict(snapshot=str(archive),quarantine=str(quarantine),reason=str(failure))
                atomic_write(self.directory/'last-recovery.json',json.dumps(self.last_recovery,ensure_ascii=False).encode())
                logger.warning('Dataset storage recovered; original damaged files retained in {}',quarantine)
                return self.last_recovery

    def request_snapshot(self):
        # Foreground writes only mark dirty; one periodic worker coalesces them.
        self._dirty.set()
        self._wake.set()

    def flush_pending(self):
        if self._dirty.is_set():
            self._dirty.clear()
            try:
                return self.snapshot(reason='mutation')
            except Exception:
                self._dirty.set()
                raise

    def start(self):
        self.snapshot(reason='startup')
        register_backups(self.root,self)
        def worker():
            while not self._stop.is_set():
                changed = self._wake.wait(self.interval)
                self._wake.clear()
                if self._stop.is_set():
                    break
                # Briefly coalesce a burst of successful foreground mutations.
                if changed and self._stop.wait(min(1.0, self.interval)):
                    break
                try:
                    if self._dirty.is_set():
                        self.flush_pending()
                    else:
                        self.snapshot(reason='periodic')
                except Exception as exc:
                    self.last_error = str(exc)
                    logger.error('Periodic dataset backup failed: {}',exc)
        self._thread = threading.Thread(target=worker,name='dataset-backups',daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=10)
        self.flush_pending()
