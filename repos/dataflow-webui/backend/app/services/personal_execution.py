"""Personal API transport. No fallback to server networking or automatic re-claim."""
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import json
import hashlib
import secrets
import sqlite3
import time

import requests

identity = ContextVar('personal_identity', default=None)


def values(info):
    return {p['name']: p.get('value') if p.get('value') is not None else p.get('default_value')
            for p in (info or {}).get('params', [])}


def personal(info):
    return values(info).get('execution_location', 'server') == 'personal'


def authorize(info, actor=None):
    if personal(info) and (not actor or info.get('owner') != actor):
        raise ValueError('个人 Serving 只能由所属用户使用')


def bind(config):
    # Never trust identity fields saved in a browser-supplied config.
    if identity.get():
        config.setdefault('execution_options', {})['personal_actor'] = identity.get()
    elif 'execution_options' in config:
        config['execution_options'].pop('personal_actor', None)
    return config


class PersonalQueue:
    def __init__(self, root):
        self.path = Path(root) / 'data' / 'personal_calls.sqlite3'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as c:
            c.execute('CREATE TABLE IF NOT EXISTS calls (id TEXT PRIMARY KEY, owner TEXT NOT NULL, serving TEXT NOT NULL, payload TEXT NOT NULL, deadline REAL NOT NULL, state TEXT NOT NULL, lease TEXT, result TEXT)')
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.path, timeout=15)
        c.row_factory = sqlite3.Row
        try:
            with c:
                yield c
        finally:
            c.close()

    def enqueue(self, owner, serving, payload, seconds=300):
        call_id = secrets.token_hex(16)
        with self.connect() as c:
            c.execute('INSERT INTO calls VALUES(?,?,?,?,?,?,NULL,NULL)',
                      (call_id, owner, serving, json.dumps(payload), time.time()+seconds, 'queued'))
        return call_id

    def claim(self, owner, mode="mock"):
        if mode not in {"mock", "real"}:
            raise ValueError("执行模式无效")
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute("UPDATE calls SET state='expired', payload='{}' WHERE deadline<? AND state IN ('queued','claimed')", (time.time(),))
            row = c.execute("SELECT * FROM calls WHERE owner=? AND state='queued' AND coalesce(json_extract(payload, '$.mode'), 'mock')=? ORDER BY rowid LIMIT 1", (owner, mode)).fetchone()
            if not row:
                return None
            lease = secrets.token_hex(24)
            c.execute("UPDATE calls SET state='claimed',lease=? WHERE id=?", (lease, row['id']))
            return dict(id=row['id'], serving=row['serving'], lease=lease, deadline=row['deadline'], **json.loads(row['payload']))

    def complete(self, owner, call_id, lease, result):
        if not isinstance(result, dict):
            raise ValueError('执行结果必须为对象')
        encoded = json.dumps(result)
        if len(encoded.encode()) > 8*1024*1024:
            raise ValueError('执行结果过大')
        if result.get('error') is not None:
            # Do not persist arbitrary upstream error strings containing credentials.
            result = {'error': '个人执行器调用失败，请在本机检查网络或服务配置'}
            encoded = json.dumps(result)
        elif not isinstance(result.get('response'), dict):
            raise ValueError('执行结果必须包含 response 对象')
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT * FROM calls WHERE id=? AND owner=?', (call_id, owner)).fetchone()
            if not row or not secrets.compare_digest(row['lease'] or '', lease):
                raise ValueError('任务不存在、已过期或不属于当前执行器')
            if row['state'] == 'done':
                if row['result'] != encoded:
                    raise ValueError('结果已提交，不能覆盖')
                return
            if row['deadline'] < time.time():
                raise ValueError('任务已过期；调用结果需要人工确认，不自动重新生成')
            if row['state'] != 'claimed':
                raise ValueError('任务不可提交')
            c.execute("UPDATE calls SET state='done',result=?,payload='{}' WHERE id=?", (encoded, call_id))

    def wait(self, call_id):
        while True:
            with self.connect() as c:
                row = c.execute('SELECT * FROM calls WHERE id=?', (call_id,)).fetchone()
                if not row:
                    raise RuntimeError('个人调用记录不存在')
                if row['state'] == 'done':
                    result = json.loads(row['result'])
                    if result.get('error'):
                        raise RuntimeError(result['error'])
                    return result['response']
                if row['state'] == 'expired':
                    c.execute("UPDATE calls SET state='expired',payload='{}' WHERE id=?", (call_id,))
                    raise TimeoutError('个人执行器未及时返回；调用结果未知，不自动重试')
            time.sleep(.1)


class PersonalSession:
    def __init__(self, root, owner, serving, mode="mock", task_id=None):
        self.queue = PersonalQueue(root)
        self.task_id = task_id
        self.owner, self.serving, self.mode = owner, serving, mode

    def post(self, url, headers=None, data=None, timeout=None, **kwargs):
        # Credentials stay in the existing registry, never in queued payloads.
        call_id = self.queue.enqueue(self.owner, self.serving,
                                     {'url': url, 'body': json.loads(data), 'timeout': timeout, 'mode': self.mode, 'task_id': self.task_id,
                                      'credential_fingerprint': hashlib.sha256((headers or {}).get('Authorization', '').encode()).hexdigest()})
        result = self.queue.wait(call_id)
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps(result).encode()
        return response

    def close(self):
        pass


def attach(instance, info, actor, task_id=None):
    if not personal(info):
        return instance
    authorize(info, actor)
    workers = values(info).get('max_workers', 1)
    if type(workers) is not int or not 1 <= workers <= 48:
        raise ValueError('个人 Serving 并发必须为 1–48 的整数')
    from app.core.config import settings
    instance.session.close()
    instance.session = PersonalSession(settings.BASE_DIR, actor, info['id'], values(info).get('personal_api_mode', 'mock'), task_id)
    # An uncertain commercial request must never be automatically repeated.
    instance.max_retries = 1
    instance.max_workers = workers
    return instance
