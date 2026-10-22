"""SQLite authority for dataset metadata; media and export blobs remain files."""
import json
from pathlib import Path
import sqlite3
import threading
from contextlib import contextmanager


_LOCALS = {}
_LOCALS_LOCK = threading.Lock()


class DatasetDatabase:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'datasets.sqlite3'
        with _LOCALS_LOCK:
            self._local = _LOCALS.setdefault(str(self.path), threading.local())
        if getattr(self._local, 'connection', None) is not None:
            return
        with self.transaction() as con:
            version = con.execute('PRAGMA user_version').fetchone()[0]
            if version == 2:
                return
            if version not in (0, 1):
                raise ValueError(f'Unsupported dataset database version: {version}')
            con.executescript('''
                CREATE TABLE IF NOT EXISTS migrations (key TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS source_datasets (
                    namespace TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL CHECK(json_valid(payload)),
                    PRIMARY KEY(namespace,id));
                CREATE TABLE IF NOT EXISTS materials (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL CHECK(json_valid(payload)));
                CREATE TABLE IF NOT EXISTS drafts (
                    id TEXT PRIMARY KEY, metadata TEXT NOT NULL CHECK(json_valid(metadata)));
                CREATE TABLE IF NOT EXISTS samples (
                    draft_id TEXT NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL, sample_id TEXT, payload TEXT NOT NULL CHECK(json_valid(payload)),
                    PRIMARY KEY(draft_id,position));
                CREATE TABLE IF NOT EXISTS draft_media (
                    draft_id TEXT NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
                    reference TEXT NOT NULL, material_id TEXT NOT NULL REFERENCES materials(id),
                    PRIMARY KEY(draft_id,reference));
                CREATE TABLE IF NOT EXISTS draft_imports (
                    draft_id TEXT NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL, payload TEXT NOT NULL CHECK(json_valid(payload)),
                    PRIMARY KEY(draft_id,position));
                CREATE TABLE IF NOT EXISTS releases (
                    id TEXT PRIMARY KEY, draft_id TEXT NOT NULL REFERENCES drafts(id),
                    payload TEXT NOT NULL CHECK(json_valid(payload)));
                CREATE TABLE IF NOT EXISTS source_members (
                    namespace TEXT NOT NULL, dataset_id TEXT NOT NULL, position INTEGER NOT NULL,
                    material_id TEXT REFERENCES materials(id), source_path TEXT NOT NULL,
                    payload TEXT NOT NULL CHECK(json_valid(payload)),
                    PRIMARY KEY(namespace,dataset_id,position),
                    FOREIGN KEY(namespace,dataset_id) REFERENCES source_datasets(namespace,id) ON DELETE CASCADE);
                PRAGMA user_version=2;
            ''')
        self.path.chmod(0o600)

    def connect(self):
        con = sqlite3.connect(self.path, timeout=30)
        con.execute('PRAGMA foreign_keys=ON')
        con.execute('PRAGMA journal_mode=WAL')
        con.execute('PRAGMA synchronous=FULL')
        return con

    @contextmanager
    def transaction(self):
        current = getattr(self._local, 'connection', None)
        if current is not None:
            yield current
            return
        con = self.connect()
        self._local.connection = con
        try:
            con.execute('BEGIN IMMEDIATE')
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            self._local.connection = None
            con.close()

    @contextmanager
    def reading(self):
        current = getattr(self._local, 'connection', None)
        if current is not None:
            yield current
        else:
            con = self.connect()
            try:
                con.execute('BEGIN')
                yield con
            finally:
                con.rollback()
                con.close()

    @staticmethod
    def encode(value):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)

    def import_registry(self, path):
        import yaml
        namespace = str(Path(path).resolve())
        key = 'registry:' + namespace
        with self.transaction() as con:
            if con.execute('SELECT 1 FROM migrations WHERE key=?', (key,)).fetchone():
                return
            data = yaml.safe_load(Path(path).read_text('utf-8'))
            if not isinstance(data, dict) or not isinstance(data.get('datasets'), dict):
                raise ValueError(f'Dataset registry is corrupt: {path}')
            for rid, rec in data['datasets'].items():
                if not isinstance(rec, dict) or rec.get('id') != rid:
                    raise ValueError(f'Invalid dataset record: {rid}')
                con.execute('INSERT INTO source_datasets VALUES (?,?,?)', (namespace, rid, self.encode(rec)))
            con.execute('INSERT INTO migrations VALUES (?)', (key,))

    def registry(self, path):
        namespace = str(Path(path).resolve())
        with self.reading() as con:
            rows = con.execute('SELECT id,payload FROM source_datasets WHERE namespace=? ORDER BY rowid', (namespace,)).fetchall()
        return {'datasets': {rid: json.loads(payload) for rid, payload in rows}}

    def replace_registry(self, path, records):
        namespace = str(Path(path).resolve())
        with self.transaction() as con:
            con.execute('DELETE FROM source_datasets WHERE namespace=?', (namespace,))
            con.executemany('INSERT INTO source_datasets VALUES (?,?,?)', [(namespace,rid,self.encode(rec)) for rid,rec in records.items()])
            self.refresh_source_members()

    def import_library(self, root):
        root = Path(root).resolve()
        key = 'library:' + str(root)
        with self.transaction() as con:
            if con.execute('SELECT 1 FROM migrations WHERE key=?', (key,)).fetchone():
                self.refresh_source_members()
                return
            for kind in ('materials', 'drafts', 'releases'):
                for path in sorted((root / kind).glob('*.json')):
                    self.put(kind, json.loads(path.read_text('utf-8')))
            con.execute('INSERT INTO migrations VALUES (?)', (key,))
            self.refresh_source_members()

    def put(self, kind, record):
        with self.transaction() as con:
            if kind == 'drafts':
                from app.services.data_library import _hash, _json_bytes
                ids = list(record.get('sample_ids', []))
                for i in range(len(ids), len(record['rows'])):
                    ids.append('sample_' + _hash(_json_bytes([record['id'], i, record['rows'][i], record.get('updated_at')])))
                record = dict(record, sample_ids=ids)
                metadata = {k:v for k,v in record.items() if k not in ('rows','media_bindings','imports')}
                con.execute('INSERT INTO drafts VALUES (?,?) ON CONFLICT(id) DO UPDATE SET metadata=excluded.metadata', (record['id'],self.encode(metadata)))
                ids = record.get('sample_ids', [])
                self._sync_rows(con, 'samples', record['id'], ('position', 'sample_id', 'payload'),
                                [(i, ids[i] if i < len(ids) else None, self.encode(row))
                                 for i, row in enumerate(record['rows'])])
                self._sync_rows(con, 'draft_media', record['id'], ('reference', 'material_id'),
                                list(record.get('media_bindings', {}).items()))
                self._sync_rows(con, 'draft_imports', record['id'], ('position', 'payload'),
                                [(i, self.encode(row)) for i, row in enumerate(record.get('imports', []))])
            elif kind == 'materials':
                con.execute('INSERT INTO materials VALUES (?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload', (record['id'],self.encode(record)))
            elif kind == 'releases':
                con.execute('INSERT INTO releases VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET draft_id=excluded.draft_id,payload=excluded.payload', (record['id'],record['draft_id'],self.encode(record)))
            else:
                raise ValueError(f'Unsupported dataset object: {kind}')

    @staticmethod
    def _sync_rows(con, table, draft_id, columns, rows):
        # Compare by stable table key and mutate only changed records.
        old = {row[0]: tuple(row) for row in con.execute(
            f"SELECT {','.join(columns)} FROM {table} WHERE draft_id=?", (draft_id,))}
        incoming = {row[0]: tuple(row) for row in rows}
        for key in old.keys() - incoming.keys():
            con.execute(f'DELETE FROM {table} WHERE draft_id=? AND {columns[0]}=?', (draft_id, key))
        names = ','.join(('draft_id', *columns))
        placeholders = ','.join('?' for _ in range(len(columns)+1))
        updates = ','.join(f'{name}=excluded.{name}' for name in columns[1:])
        for key, row in incoming.items():
            if old.get(key) != row:
                con.execute(f'INSERT INTO {table} ({names}) VALUES ({placeholders}) '
                            f'ON CONFLICT(draft_id,{columns[0]}) DO UPDATE SET {updates}', (draft_id, *row))

    def draft_summaries(self, rid=None):
        with self.reading() as con:
            query = 'SELECT id,metadata FROM drafts' + (' WHERE id=?' if rid else '')
            records = con.execute(query, (rid,) if rid else ()).fetchall()
            result = []
            for did, metadata in records:
                rec = json.loads(metadata)
                rec['row_count'] = con.execute('SELECT COUNT(*) FROM samples WHERE draft_id=?', (did,)).fetchone()[0]
                rec['fields'] = sorted(r[0] for r in con.execute(
                    'SELECT DISTINCT j.key FROM samples s, json_each(s.payload) j WHERE s.draft_id=?', (did,)))
                rec['media_bindings'] = dict(con.execute('SELECT reference,material_id FROM draft_media WHERE draft_id=?', (did,)))
                rec['imports'] = [json.loads(r[0]) for r in con.execute('SELECT payload FROM draft_imports WHERE draft_id=? ORDER BY position', (did,))]
                result.append(rec)
            return result

    def draft_page(self, rid, offset, limit):
        from app.services.data_library import _hash, _json_bytes
        with self.reading() as con:
            summaries = self.draft_summaries(rid)
            if not summaries:
                return None
            rec = summaries[0]
            rows = con.execute('SELECT position,sample_id,payload FROM samples WHERE draft_id=? ORDER BY position LIMIT ? OFFSET ?',
                               (rid, limit, offset)).fetchall()
            ids = rec.get('sample_ids', [])
            rec['rows'] = [json.loads(row[2]) for row in rows]
            rec['sample_ids'] = [ids[pos] if pos < len(ids) else sid or 'sample_' + _hash(_json_bytes(
                [rid, pos, json.loads(payload), rec.get('updated_at')])) for pos,sid,payload in rows]
            rec.setdefault('sample_sources', {})
            return dict(rec, offset=offset, limit=limit)

    def get(self, kind, rid):
        if kind not in ('materials','drafts','releases'):
            raise ValueError('Invalid kind')
        column = 'metadata' if kind=='drafts' else 'payload'
        with self.reading() as con:
            row = con.execute(f'SELECT {column} FROM {kind} WHERE id=?', (rid,)).fetchone()
            if row is None:
                return None
            record = json.loads(row[0])
            if kind == 'drafts':
                record['rows'] = [json.loads(r[0]) for r in con.execute('SELECT payload FROM samples WHERE draft_id=? ORDER BY position', (rid,))]
                record['media_bindings'] = dict(con.execute('SELECT reference,material_id FROM draft_media WHERE draft_id=?', (rid,)))
                record['imports'] = [json.loads(r[0]) for r in con.execute('SELECT payload FROM draft_imports WHERE draft_id=? ORDER BY position', (rid,))]
            return record

    def list(self, kind):
        if kind not in ('materials','drafts','releases'):
            raise ValueError('Invalid kind')
        with self.reading() as con:
            ids = [r[0] for r in con.execute(f'SELECT id FROM {kind} ORDER BY rowid')]
            return [self.get(kind, rid) for rid in ids]

    def backup(self, destination):
        # The SQLite backup API includes committed WAL pages in a consistent image.
        with self.reading() as source:
            target = sqlite3.connect(destination)
            try:
                source.backup(target)
                if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('SQLite backup integrity check failed')
            finally:
                target.close()


    def refresh_source_members(self):
        from app.services.data_library import IMAGE_TYPES
        with self.transaction() as con:
            records = con.execute('SELECT namespace,id,payload FROM source_datasets').fetchall()
            con.execute('DELETE FROM source_members')
            for namespace,rid,payload in records:
                root = Path(json.loads(payload)['root'])
                if root.suffix.lower() != '.jsonl' or not root.is_file() or root.stat().st_size > 2*1024*1024:
                    continue
                try:
                    rows = [json.loads(line) for line in root.read_text('utf-8-sig').splitlines() if line.strip()]
                except (ValueError,UnicodeError):
                    continue
                if not rows or any(not isinstance(row,dict) or set(row)-{'source','source_name','material_id'}
                                   or not isinstance(row.get('source'),str)
                                   or Path(row['source']).suffix.lower() not in {'.pdf', '.txt', '.md', '.json', '.jsonl', '.csv', '.parquet', *IMAGE_TYPES} for row in rows):
                    continue
                for i,row in enumerate(rows):
                    mid = row.get('material_id')
                    if mid and not con.execute('SELECT 1 FROM materials WHERE id=?',(mid,)).fetchone():
                        mid = None
                    con.execute('INSERT INTO source_members VALUES (?,?,?,?,?,?)',(namespace,rid,i,mid,row['source'],self.encode(row)))
