"""Mac/Windows personal API executor; standard library only, mock by default."""
import argparse
import getpass
import ipaddress
import json
from pathlib import Path
import socket
import ssl
import time
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPCookieProcessor, HTTPSHandler, HTTPRedirectHandler
import http.cookiejar
from concurrent.futures import ThreadPoolExecutor


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def validate_endpoint(url):
    parts = urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
        raise ValueError('商业 API 必须使用无内嵌凭据的 HTTPS 地址')
    addresses = socket.getaddrinfo(parts.hostname, parts.port or 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError('个人执行器仅接受公网商业 API 地址')


class Platform:
    def __init__(self, url, ca_file=None):
        self.url = url.rstrip('/')
        parts = urlsplit(self.url)
        if parts.path or parts.query or parts.fragment or parts.username or parts.password:
            raise ValueError('平台地址应只包含协议、主机和端口')
        if parts.scheme != 'https' and not (parts.scheme == 'http' and parts.hostname in {'localhost', '127.0.0.1'}):
            raise ValueError('学校平台必须使用 HTTPS')
        self.opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()),
                                   HTTPSHandler(context=ssl.create_default_context(cafile=ca_file)), NoRedirect())
        self.csrf, self.project = '', ''

    def request(self, path, body=None):
        headers = {'Content-Type': 'application/json', 'Origin': self.url,
                   'X-CSRF-Token': self.csrf, 'X-Project-ID': self.project}
        request = Request(self.url+path, data=None if body is None else json.dumps(body).encode(), headers=headers)
        with self.opener.open(request, timeout=30) as response:
            return json.load(response)

    def login(self, name, password, project=None):
        self.csrf = self.request('/team/login', {'name': name, 'password': password})['csrf']
        user = self.request('/team/me')
        available = [p for p in user['projects'] if set(p['roles']) & {'manage', 'develop'}]
        self.project = project or user['project'] or (available[0]['id'] if available else None)
        if not any(p['id'] == self.project for p in user['projects']):
            raise ValueError('账号没有该项目的成员权限')
        self.request('/team/project', {'project': self.project})
        return user


def execute(job, real=False, opener=None):
    if real and job.get('mode') != 'real':
        raise ValueError('任务未允许真实 API 调用')
    if not real:
        return {'response': {'choices': [{'message': {'content': '个人执行器模拟响应；未调用商业 API'}}],
                             'model': job['body'].get('model'), 'mock': True}}
    validate_endpoint(job['url'])
    request = Request(job['url'], data=json.dumps(job['body']).encode(),
                      headers={'Content-Type': 'application/json', 'Authorization': 'Bearer '+job['api_key']})
    upstream = opener or build_opener(NoRedirect())
    with upstream.open(request, timeout=120) as response:
        raw = response.read(8*1024*1024+1)
    if len(raw) > 8*1024*1024:
        raise ValueError('模型响应超过大小限制')
    return {'response': json.loads(raw)}


def flush_results(platform, spool):
    # Only the coordinator uses the authenticated platform session.
    for path in sorted(spool.glob('*.json')):
        platform.request('/team/personal/result', json.loads(path.read_text('utf-8')))
        path.unlink()


def execute_and_spool(job, spool, real=False):
    try:
        result = execute(job, real)
    except Exception:
        result = {'error': True}
    record = {'id': job['id'], 'lease': job['lease'], 'result': result}
    # Persist only results, never API keys, request headers or login credentials.
    path = spool / (job['id']+'.json')
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
    try:
        temp.chmod(0o600)
    except OSError:
        pass
    temp.replace(path)
    return job['id']


def run_one(platform, spool, real=False):
    flush_results(platform, spool)
    job = platform.request('/team/personal/claim', {'mode': 'real' if real else 'mock'})['job']
    if not job:
        return False
    execute_and_spool(job, spool, real)
    flush_results(platform, spool)
    print('已回传任务 '+job['id']+('（真实调用）' if real else '（模拟）'))
    return True


class ConcurrentExecutor:
    """Bounded upstream workers; durable results, serialized claims and ACKs.

    Only already-claimed requests run in threads. An uncertain upstream outcome
    is never re-claimed or retried. A failed ACK leaves the original result on
    disk, and prevents this coordinator from accepting further requests.
    """
    def __init__(self, platform, spool, real=False, concurrency=1):
        if type(concurrency) is not int or not 1 <= concurrency <= 48:
            raise ValueError('执行器并发必须为 1–48 的整数')
        self.platform, self.spool, self.real = platform, spool, real
        self.concurrency = concurrency
        self.pool = ThreadPoolExecutor(max_workers=concurrency)
        self.pending = {}
        self.closed = False

    def step(self):
        if self.closed:
            raise RuntimeError('执行器已经关闭')
        flush_results(self.platform, self.spool)
        for call_id, future in list(self.pending.items()):
            if future.done():
                future.result()
                del self.pending[call_id]
        flush_results(self.platform, self.spool)
        dispatched = False
        while len(self.pending) < self.concurrency:
            job = self.platform.request('/team/personal/claim', {'mode': 'real' if self.real else 'mock'})['job']
            if not job:
                break
            if job['id'] in self.pending or (self.spool/(job['id']+'.json')).exists():
                raise RuntimeError('平台重复下发已领取请求；停止新增调用')
            self.pending[job['id']] = self.pool.submit(execute_and_spool, job, self.spool, self.real)
            dispatched = True
        return dispatched or bool(self.pending)

    def close(self):
        if self.closed:
            return
        self.closed = True
        # Do not interrupt billable calls. Workers persist their responses even
        # if the coordinator can no longer reach the school platform.
        self.pool.shutdown(wait=True)
        flush_results(self.platform, self.spool)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--user', required=True)
    parser.add_argument('--project')
    parser.add_argument('--ca-file')
    parser.add_argument('--execute', action='store_true', help='明确启用真实商业 API 调用；默认模拟')
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--concurrency', type=int, choices=range(1, 49), default=1,
                        metavar='1..48', help='同时执行的商业 HTTP 请求上限，默认 1')
    args = parser.parse_args()
    platform = Platform(args.url, args.ca_file)
    user = platform.login(args.user, getpass.getpass('平台密码: '), args.project)
    import hashlib
    scope = hashlib.sha256((args.url+user['id']+platform.project+str(args.execute)).encode()).hexdigest()[:24]
    spool = Path.home()/'.dataflow-personal'/scope
    spool.mkdir(parents=True, exist_ok=True, mode=0o700)
    print('已登录；'+('真实执行模式' if args.execute else '模拟模式，不调用商业 API'))
    executor = ConcurrentExecutor(platform, spool, args.execute, args.concurrency)
    try:
        while True:
            executor.step()
            if args.once:
                break
            time.sleep(.2 if executor.pending else 1)
    finally:
        try:
            executor.close()
        finally:
            platform.request('/team/logout', {})


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception:
        raise SystemExit('执行器已停止。请检查平台连接、证书、账号和待回传结果；不会自动重试商业 API。')
