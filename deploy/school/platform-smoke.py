"""Check the isolated school platform without model calls or training jobs."""
import argparse
import json
import os
from pathlib import Path
import secrets
import time


def initialize():
    from app.services.team_store import TeamStore
    credential = Path('/state/admin-bootstrap.json')
    if credential.exists():
        raise FileExistsError('Existing bootstrap preserved; do not initialize twice')
    admin = {'name': 'huruiqian', 'password': secrets.token_urlsafe(24)}
    # Create exclusively with private permissions; never print the credential.
    with open(credential, 'x', opener=lambda path, flags: os.open(path, flags, 0o600)) as stream:
        json.dump(admin, stream)
    TeamStore('/state/team').initialize(admin['name'], admin['password'], '/state/workspace')
    print('ADMIN_INITIALIZED_CREDENTIAL_STORED_PRIVATELY', flush=True)


def check(base, ca):
    import httpx
    verification = str(ca) if ca else True
    admin = json.loads(Path('/state/admin-bootstrap.json').read_text())
    started = time.time()
    with httpx.Client(base_url=base, trust_env=False, timeout=240, verify=verification) as client:
        for attempt in range(60):
            try:
                status = client.get('/team/status', timeout=3)
                break
            except httpx.TransportError:
                if attempt == 59:
                    raise
                time.sleep(.5)
        status.raise_for_status()
        assert status.json()['initialized'] and not status.json()['development']
        assert client.get('/').status_code == 200
        assert client.get('/api/v1/pipelines/').status_code == 401
        client.headers['Origin'] = base
        login = client.post('/team/login', json=admin)
        login.raise_for_status()
        if base.startswith('https://'):
            assert 'secure' in login.headers['set-cookie'].lower()
        client.headers['X-CSRF-Token'] = login.json()['csrf']
        client.post('/team/project', json={'project': 'default'}).raise_for_status()
        for route in ['/api/v1/operators/', '/api/v1/pipelines/']:
            response = client.get(route)
            response.raise_for_status()
        original = client.get('/api/v1/preferences/').json()['data']
        updated = dict(original, theme='dark' if original.get('theme') != 'dark' else 'light')
        client.post('/api/v1/preferences/', json=updated).raise_for_status()
        client.post('/team/logout').raise_for_status()
    # A fresh login must read persisted data, not an in-memory client value.
    with httpx.Client(base_url=base, trust_env=False, timeout=240, verify=verification,
                      headers={'Origin': base}) as client:
        login = client.post('/team/login', json=admin)
        login.raise_for_status()
        client.headers['X-CSRF-Token'] = login.json()['csrf']
        assert client.get('/api/v1/preferences/').json()['data'] == updated
        client.post('/api/v1/preferences/', json=original).raise_for_status()
        client.post('/team/logout').raise_for_status()
    receipt = {'status': 'PASSED_PLATFORM_HTTP_SMOKE', 'authenticated': True,
               'base_url': base, 'tls_verified': base.startswith('https://'),
               'api_lists': True, 'save_fresh_login_read': True,
               'generation_model_called': False, 'training_started': False,
               'seconds': time.time() - started}
    Path('/work/platform-smoke.json').write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['init', 'check'])
    parser.add_argument('--base-url', default='http://127.0.0.1:8001')
    parser.add_argument('--ca', type=Path)
    args = parser.parse_args()
    initialize() if args.command == 'init' else check(args.base_url.rstrip('/'), args.ca)
