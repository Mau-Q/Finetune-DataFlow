"""LAN identities and project membership. Sessions are opaque, revocable and server-side."""
from contextlib import contextmanager
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from pathlib import Path
from app.services.data_library import LibraryError


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password, salt=None):
    if not isinstance(password, str) or len(password) < 12 or len(password) > 1024:
        raise LibraryError('密码需为 12–1024 个字符')
    salt = salt or secrets.token_hex(16)
    value = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return salt + ':' + value


def verify(password, stored):
    try:
        return hmac.compare_digest(password_hash(password, stored.split(':')[0]), stored)
    except (ValueError, TypeError):
        return False


class TeamStore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.root / 'team.sqlite3'
        with self.tx() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL,
              password TEXT NOT NULL, admin INTEGER NOT NULL DEFAULT 0, enabled INTEGER NOT NULL DEFAULT 1,
              preferences TEXT NOT NULL DEFAULT '{"language":"cn","theme":"light"}');
            CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, name TEXT NOT NULL, root TEXT UNIQUE NOT NULL);
            CREATE TABLE IF NOT EXISTS members(project TEXT REFERENCES projects(id), user TEXT REFERENCES users(id),
              roles TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(project,user));
            CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user TEXT REFERENCES users(id),
              csrf TEXT NOT NULL, expires REAL NOT NULL, project TEXT);
            CREATE TABLE IF NOT EXISTS invitations(token TEXT PRIMARY KEY, user TEXT REFERENCES users(id), expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS attempts(key TEXT PRIMARY KEY, count INTEGER NOT NULL, since REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, actor TEXT, project TEXT, action TEXT, object TEXT, time REAL, result TEXT);
            CREATE TABLE IF NOT EXISTS versions(project TEXT, object TEXT, version INTEGER, PRIMARY KEY(project,object));
            PRAGMA user_version=1;
            ''')
        self.path.chmod(0o600)

    @contextmanager
    def tx(self):
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('BEGIN IMMEDIATE')
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    @staticmethod
    def audit(c, actor, project, action, obj='', result='ok'):
        c.execute('INSERT INTO audit(actor,project,action,object,time,result) VALUES(?,?,?,?,?,?)',
                  (actor, project, action, str(obj)[:240], time.time(), result))

    def initialize(self, name, password, legacy_root):
        hashed = password_hash(password)
        preferences={'language':'cn','theme':'light'}
        legacy_preferences=Path(legacy_root)/'data/user_preferences.json'
        if legacy_preferences.is_file():
            saved=json.loads(legacy_preferences.read_text('utf-8'))
            preferences.update({k:saved[k] for k in ('language','theme') if k in saved})
        with self.tx() as c:
            if c.execute('SELECT 1 FROM users').fetchone():
                raise LibraryError('管理员已初始化', 409)
            uid = 'u_' + secrets.token_hex(12)
            c.execute('INSERT INTO users(id,name,password,admin,preferences) VALUES(?,?,?,1,?)', (uid, name, hashed, json.dumps(preferences)))
            c.execute('INSERT INTO projects VALUES(?,?,?)', ('default', '默认工作区', str(Path(legacy_root).resolve())))
            c.execute('INSERT INTO members(project,user,roles) VALUES(?,?,?)', ('default', uid, 'manage,develop,review'))
            self.audit(c, uid, 'default', 'migration-v1', 'legacy-import')
            return uid

    def development_login(self, workspace):
        """Idempotently create a dedicated local identity, preserving real accounts."""
        uid = 'local-development'
        root = str(Path(workspace).resolve())
        with self.tx() as c:
            c.execute("INSERT OR IGNORE INTO users(id,name,password,admin) VALUES(?,?,'unusable',1)",
                      (uid, '本地开发者'))
            user = c.execute('SELECT enabled FROM users WHERE id=?', (uid,)).fetchone()
            if not user or not user['enabled']:
                raise LibraryError('本地开发账号已禁用', 403)
            existing = c.execute("SELECT root FROM projects WHERE id='default'").fetchone()
            if existing and Path(existing['root']).resolve() != Path(root):
                raise LibraryError('默认工作区指向其他目录，请检查开发配置', 409)
            c.execute("INSERT OR IGNORE INTO projects VALUES('default','默认工作区',?)", (root,))
            c.execute("INSERT OR IGNORE INTO members(project,user,roles) VALUES('default',?,'manage,develop,review')", (uid,))
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
            c.execute('DELETE FROM sessions WHERE expires<?', (time.time(),))
            c.execute("INSERT INTO sessions VALUES(?,?,?,?,'default')", (digest(token), uid, csrf, time.time()+43200))
            self.audit(c, uid, 'default', 'development-login')
            return token, csrf

    def login(self, name, password, address):
        key = digest(address + ':' + str(name))
        with self.tx() as c:
            row = c.execute('SELECT * FROM attempts WHERE key=?', (key,)).fetchone()
            if row and row['since'] > time.time()-300 and row['count'] >= 10:
                raise LibraryError('登录尝试过多，请稍后重试', 429)
            c.execute('INSERT INTO attempts VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET count=CASE WHEN since<? THEN 1 ELSE count+1 END,since=CASE WHEN since<? THEN excluded.since ELSE since END',
                      (key, time.time(), time.time()-300, time.time()-300))
            user = c.execute('SELECT * FROM users WHERE name=?', (name,)).fetchone()
            valid = bool(user and user['enabled'] and verify(password, user['password']))
            if valid:
                c.execute('DELETE FROM attempts WHERE key=?', (key,))
                token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
                c.execute('INSERT INTO sessions VALUES(?,?,?,?,NULL)', (digest(token), user['id'], csrf, time.time()+43200))
                self.audit(c, user['id'], None, 'login')
                return token, csrf
        raise LibraryError('账号或密码无效', 401)

    def identity(self, token):
        with self.tx() as c:
            r = c.execute('SELECT u.id,u.name,u.admin,s.csrf,s.project FROM sessions s JOIN users u ON u.id=s.user WHERE s.token=? AND s.expires>? AND u.enabled=1', (digest(token or ''), time.time())).fetchone()
            if not r:
                raise LibraryError('请登录', 401)
            return dict(r)

    def projects(self, uid):
        with self.tx() as c:
            return [dict(r, roles=r['roles'].split(',')) for r in c.execute('SELECT p.id,p.name,m.roles,m.version FROM projects p JOIN members m ON m.project=p.id WHERE m.user=?', (uid,)) if r['roles']]

    def access(self, uid, project):
        with self.tx() as c:
            r = c.execute('SELECT p.*,m.roles FROM projects p JOIN members m ON p.id=m.project WHERE p.id=? AND m.user=?', (project, uid)).fetchone()
            if not r or not r['roles']:
                raise LibraryError('资源不存在', 404)
            return dict(r, roles=r['roles'].split(','))

    def invite(self, actor, name, admin=False, ttl=3600, reset=None):
        if not actor['admin']:
            raise LibraryError('需要系统管理权限', 403)
        with self.tx() as c:
            uid = reset or 'u_' + secrets.token_hex(12)
            if reset:
                if not c.execute('SELECT 1 FROM users WHERE id=?', (uid,)).fetchone():
                    raise LibraryError('账号不存在', 404)
                c.execute("UPDATE users SET password='unusable' WHERE id=?", (uid,))
                c.execute('DELETE FROM sessions WHERE user=?', (uid,))
                c.execute('DELETE FROM invitations WHERE user=?', (uid,))
            else:
                if not isinstance(name, str) or not name.strip() or len(name)>120:
                    raise LibraryError('账号名无效')
                if c.execute('SELECT 1 FROM users WHERE name=?', (name,)).fetchone():
                    raise LibraryError('账号名已存在',409)
                c.execute('INSERT INTO users(id,name,password,admin,preferences) VALUES(?,?,?,?,?)', (uid,name,'unusable',int(admin),json.dumps({'language':'cn','theme':'light'})))
            token = secrets.token_urlsafe(32)
            c.execute('INSERT INTO invitations VALUES(?,?,?)', (digest(token),uid,time.time()+max(1,min(ttl,86400))))
            self.audit(c, actor['id'], None, 'reset' if reset else 'invite', uid)
            return {'user_id':uid,'invitation':token,'expires_in':max(1,min(ttl,86400))}

    def accept(self, token, password):
        hashed = password_hash(password)
        with self.tx() as c:
            row = c.execute('SELECT * FROM invitations WHERE token=? AND expires>?', (digest(token), time.time())).fetchone()
            if not row:
                raise LibraryError('邀请无效或已过期', 400)
            c.execute('UPDATE users SET password=? WHERE id=?', (hashed,row['user']))
            c.execute('DELETE FROM invitations WHERE user=?', (row['user'],))
            c.execute('DELETE FROM sessions WHERE user=?', (row['user'],))
            self.audit(c, row['user'], None, 'accept-invitation')

    def member(self, actor, project, uid, roles, version):
        permissions = self.access(actor['id'], project)
        if 'manage' not in permissions['roles']:
            raise LibraryError('需要项目管理权限',403)
        if not isinstance(roles,list) or set(roles)-{'manage','develop','review'}:
            raise LibraryError('权限无效')
        with self.tx() as c:
            current = c.execute('SELECT * FROM members WHERE project=? AND user=?',(project,uid)).fetchone()
            if (current['version'] if current else 0) != version:
                raise LibraryError('内容已更新',409)
            if not c.execute('SELECT 1 FROM users WHERE id=?',(uid,)).fetchone():
                raise LibraryError('账号不存在',404)
            c.execute('INSERT INTO members VALUES(?,?,?,1) ON CONFLICT(project,user) DO UPDATE SET roles=excluded.roles,version=members.version+1',(project,uid,','.join(sorted(set(roles)))))
            self.audit(c,actor['id'],project,'membership',uid)

    def disable(self, actor, uid, enabled):
        if not actor['admin']:
            raise LibraryError('需要系统管理权限',403)
        with self.tx() as c:
            target=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
            if not target:raise LibraryError('账号不存在',404)
            if not enabled and target['admin'] and target['enabled'] and target['password']!='unusable' and c.execute("SELECT count(*) FROM users WHERE admin=1 AND enabled=1 AND password LIKE '%:%'").fetchone()[0]<=1:
                raise LibraryError('不能禁用最后一个管理员',409)
            c.execute('UPDATE users SET enabled=? WHERE id=?',(int(enabled),uid))
            c.execute('DELETE FROM sessions WHERE user=?',(uid,))
            self.audit(c,actor['id'],None,'enable' if enabled else 'disable',uid)
