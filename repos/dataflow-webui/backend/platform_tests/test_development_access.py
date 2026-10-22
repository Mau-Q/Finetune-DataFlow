"""Development identity and real loopback-worker checks, also run on Windows CI."""
import asyncio
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.services.project_workers import Workers
from app.services.worker_auth import install_worker_auth
from app.team_gateway import create_gateway


class DevelopmentTests(unittest.TestCase):
    def test_local_identity_logout_and_existing_accounts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = create_gateway(root/'state', workers=EmptyWorkers(), secure=False,
                                 development=True, workspace=root/'workspace')
            store = app.state.store
            owner = store.initialize('owner', 'isolated-owner-password', root/'workspace')
            with TestClient(app, base_url='http://127.0.0.1', client=('127.0.0.1', 1234)) as client:
                client.headers['Origin'] = 'http://127.0.0.1'
                self.assertTrue(client.get('/team/status').json()['development'])
                self.assertEqual(client.get('/team/me').status_code, 401)
                first = client.post('/team/dev-login').json()
                identity = client.get('/team/me').json()
                self.assertEqual(identity['id'], 'local-development')
                self.assertNotEqual(identity['id'], owner)
                self.assertEqual(identity['project'], 'default')
                client.headers['X-CSRF-Token'] = first['csrf']
                self.assertEqual(client.post('/team/logout').status_code, 200)
                self.assertEqual(client.get('/team/me').status_code, 401)
                self.assertEqual(client.post('/team/dev-login').status_code, 200)
                with store.tx() as db:
                    self.assertEqual(db.execute('SELECT count(*) FROM users').fetchone()[0], 2)
                    self.assertEqual(db.execute('SELECT count(*) FROM projects').fetchone()[0], 1)
                    self.assertEqual(db.execute('SELECT enabled FROM users WHERE id=?', (owner,)).fetchone()[0], 1)

    def test_fresh_workspace_and_disabled_development(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = create_gateway(root/'state', workers=EmptyWorkers(), secure=False,
                                 development=True, workspace=root/'workspace')
            with TestClient(app, base_url='http://localhost', client=('127.0.0.1', 1)) as client:
                self.assertFalse(client.get('/team/status').json()['initialized'])
                self.assertEqual(client.post('/team/dev-login', headers={'Origin':'http://localhost'}).status_code, 200)
                self.assertEqual(client.get('/team/me').json()['projects'][0]['name'], '默认工作区')
            app = create_gateway(root/'other', workers=EmptyWorkers(), secure=False, development=False)
            with TestClient(app) as client:
                self.assertEqual(client.post('/team/dev-login', headers={'Origin':'http://testserver'}).status_code, 404)

    def test_development_session_cannot_cross_into_normal_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = create_gateway(root/'state', workers=EmptyWorkers(), secure=False,
                                 development=True, workspace=root/'workspace')
            token, _ = app.state.store.development_login(root/'workspace')
            regular = create_gateway(root/'state', workers=EmptyWorkers(), secure=False, development=False)
            with TestClient(regular) as client:
                client.cookies.set('df_session', token)
                self.assertEqual(client.get('/team/me').status_code, 401)

    def test_remote_host_and_foreign_origin_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            app = create_gateway(temp, workers=EmptyWorkers(), secure=False, development=True)
            for peer, host in [('192.168.1.9','127.0.0.1'), ('127.0.0.1','evil.example')]:
                with TestClient(app, base_url='http://'+host, client=(peer, 1)) as client:
                    self.assertEqual(client.get('/team/status').status_code, 403)
            with TestClient(app, base_url='http://127.0.0.1', client=('127.0.0.1', 1)) as client:
                self.assertEqual(client.post('/team/dev-login', headers={'Origin':'http://evil.example'}).status_code, 403)

    def test_worker_rejects_direct_access(self):
        app = FastAPI()
        install_worker_auth(app, 'private-test-token')
        with TestClient(app) as client:
            self.assertEqual(client.get('/_worker/ready').status_code, 403)
            self.assertEqual(client.get('/_worker/ready', headers={'X-Worker-Token':'wrong'}).status_code, 403)
            self.assertEqual(client.get('/_worker/ready', headers={'X-Worker-Token':'private-test-token'}).status_code, 200)

    def test_real_worker_start_reuse_and_cleanup_with_unicode_path(self):
        asyncio.run(self._worker_lifecycle())

    async def _worker_lifecycle(self):
        from app.services import worker_auth
        with tempfile.TemporaryDirectory(prefix='dataflow workspace ') as temp:
            root = Path(temp)/'中文 空格'
            (root/'app').mkdir(parents=True)
            (root/'app/__init__.py').touch()
            # Load the production auth adapter in a tiny real subprocess. No Core,
            # models or database fixtures are installed by this transport test.
            auth_path = str(Path(worker_auth.__file__).resolve())
            (root/'app/main.py').write_text(
                'import importlib.util, os\nfrom fastapi import FastAPI\n'
                f'spec=importlib.util.spec_from_file_location("auth", {auth_path!r})\n'
                'auth=importlib.util.module_from_spec(spec)\nspec.loader.exec_module(auth)\n'
                'app=FastAPI()\nauth.install_worker_auth(app,os.environ["DATAFLOW_WORKER_TOKEN"])\n', encoding='utf-8')
            workers = Workers(root/'state')
            project = {'id':'test', 'root':str(root)}
            try:
                # An inherited invalid proxy must not affect private transport.
                with patch('app.services.project_workers.BACKEND', root), patch.dict(os.environ, {'HTTP_PROXY':'http://127.0.0.1:1'}):
                    client = await workers.client(project)
                    async with client:
                        self.assertEqual((await client.get('/_worker/ready')).status_code, 200)
                    process = workers.processes['test']
                    another = await workers.client(project)
                    await another.aclose()
                    self.assertIs(workers.processes['test'], process)
                    endpoint, _ = workers.endpoints['test']
                    async with httpx.AsyncClient(trust_env=False) as direct:
                        self.assertEqual((await direct.get(endpoint+'/_worker/ready')).status_code, 403)
            finally:
                await workers.close()
            self.assertIsNotNone(process.poll())
            self.assertEqual(workers.processes, {})


class EmptyWorkers:
    async def close(self):
        pass


class DesktopPickerTests(unittest.TestCase):
    def test_windows_picker_unicode_and_cancel(self):
        from types import SimpleNamespace
        from app.services import local_source_picker as picker
        with patch.object(picker.sys, 'platform', 'win32'), patch.object(picker.subprocess, 'run') as run:
            run.return_value = SimpleNamespace(stdout='["C:\\\\数据 空格"]')
            self.assertEqual(picker.pick_paths(directories_only=True), ['C:\\数据 空格'])
            command = run.call_args.args[0]
            self.assertEqual(command[0], 'powershell.exe')
            self.assertIn('-STA', command)
            self.assertIn('-DirectoriesOnly', command)
            self.assertEqual(run.call_args.kwargs['encoding'], 'utf-8')
            run.return_value = SimpleNamespace(stdout='[]')
            self.assertEqual(picker.pick_paths(), [])
