"""Independent, fail-closed training metadata. Dataset stores are read-only inputs."""
import hashlib
import json
import sqlite3
import uuid
from contextlib import closing, contextmanager
from functools import wraps
from datetime import datetime, timezone
from pathlib import Path
from app.schemas.model_training import TrainingPlan
from app.services.dataset_persistence import dataset_lock


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


class TrainingError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class ModelTraining:
    def __init__(self, root, library=None):
        self.root = Path(root)
        self.library = library
        self.path = self.root / 'training.sqlite3'
        self.marker = self.root / '.initialized'
        with dataset_lock(self.root):
            self.root.mkdir(parents=True, exist_ok=True)
            if self.marker.exists() and not self.path.is_file():
                raise TrainingError('训练数据库缺失，请恢复备份；不会创建空库', 503)
            if not self.path.exists():
                with closing(sqlite3.connect(self.path)) as db, db:
                    db.executescript('CREATE TABLE meta(version INTEGER NOT NULL); INSERT INTO meta VALUES(1); CREATE TABLE records(kind TEXT NOT NULL,id TEXT NOT NULL,version INTEGER NOT NULL,body TEXT NOT NULL,PRIMARY KEY(kind,id));')
            with self.connect() as db:
                version = db.execute('SELECT version FROM meta').fetchone()
                if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or version != (1,):
                    raise TrainingError('训练数据库版本或完整性错误', 503)
            self.marker.touch()

    @contextmanager
    def connect(self):
        with dataset_lock(self.root):
            if not self.path.is_file():
                raise TrainingError('训练数据库缺失，请恢复备份', 503)
            try:
                # as_uri escapes spaces, # and % and handles Windows drive letters.
                with closing(sqlite3.connect(self.path.resolve().as_uri() + '?mode=rw', uri=True, timeout=30)) as db:
                    with db:
                        db.execute('BEGIN IMMEDIATE')
                        yield db
            except sqlite3.Error as exc:
                raise TrainingError('训练数据库损坏或不可用，请检查原文件或恢复备份', 503) from exc

    def list(self, kind):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT body FROM records WHERE kind=? ORDER BY rowid DESC', (kind,))]

    def get(self, kind, key):
        with self.connect() as db:
            row = db.execute('SELECT body FROM records WHERE kind=? AND id=?', (kind,key)).fetchone()
        if not row:
            raise TrainingError('训练记录不存在', 404)
        return json.loads(row[0])

    def put(self, kind, body, key=None, expected=None):
        key = key or uuid.uuid4().hex
        with self.connect() as db:
            row = db.execute('SELECT version FROM records WHERE kind=? AND id=?', (kind,key)).fetchone()
            if row and expected != row[0]:
                raise TrainingError('记录已更新，请重开后再编辑', 409)
            if not row and expected is not None:
                raise TrainingError('记录不存在或已被删除', 409)
            version = (row[0] if row else 0) + 1
            result = dict(body, id=key, version=version, updated_at=now())
            db.execute('INSERT OR REPLACE INTO records VALUES(?,?,?,?)', (kind,key,version,canonical(result).decode()))
        return result

    def save_plan(self, body, key=None, expected=None):
        plan = TrainingPlan.model_validate(body).model_dump()
        if plan['group_id']:
            self.get('groups', plan['group_id'])
        return self.put('plans', {'plan':plan}, key, expected)

    def releases(self):
        return self.library.db.list('releases') if self.library else []

    def check(self, plan):
        errors=[]
        if not plan['model'].strip(): errors.append('model: 请填写模型引用')
        if not any(b['role']=='train' for b in plan['data']): errors.append('data: 请绑定训练数据')
        releases={r['id']:r for r in self.releases()}
        for i,b in enumerate(plan['data']):
            if not b['ref']: errors.append(f'data[{i}].ref: 缺少数据引用')
            if b['kind']=='draft': errors.append(f'data[{i}]: 草稿需在生成数据集页面明确发布后重新绑定')
            if b['kind']=='release':
                if b['ref'] not in releases:errors.append(f'data[{i}]: 发布版本不存在')
                elif releases[b['ref']].get('modality','text')!=plan['modality'] or releases[b['ref']].get('training_type','sft')!=plan['task']:errors.append(f'data[{i}]: 发布版本与任务/模态不兼容')
            if b['kind']=='huggingface' and not __import__('re').fullmatch('[0-9a-f]{40,64}',b['revision']): errors.append(f'data[{i}]: HF 数据需要固定 revision')
        return {'structure': 'passed', 'compatibility':'failed' if errors else 'passed','errors':errors,'environment':'not_checked','runtime':'NOT_RUN'}

    def backup(self):
        with dataset_lock(self.root):
            if not self.path.is_file():
                raise TrainingError('训练数据库缺失，请恢复备份', 503)
            target = self.root / 'backups' / (uuid.uuid4().hex + '.sqlite3')
            target.parent.mkdir(exist_ok=True)
            with closing(sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True)) as reader:
                with closing(sqlite3.connect(target)) as dest:
                    reader.backup(dest)
            return target


def training_transaction(function):
    """Serialize metadata checks and related artifact writes, including backups."""
    @wraps(function)
    def wrapped(service, *args, **kwargs):
        with dataset_lock(service.root):
            return function(service, *args, **kwargs)
    return wrapped
