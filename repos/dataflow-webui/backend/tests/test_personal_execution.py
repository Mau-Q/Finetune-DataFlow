"""All upstream responses are fixtures; tests must not reach a commercial API."""
import importlib.util
import json
from pathlib import Path
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from app.services.personal_execution import PersonalQueue, PersonalSession, identity, attach, bind
from app.services.serving_registry import ServingRegistry
from app.team_gateway import create_gateway

PASSWORD = 'personal-test-password-123'
spec = importlib.util.spec_from_file_location('personal_runner', Path(__file__).resolve().parents[4]/'tools/personal-executor/runner.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def login(client, name='owner'):
    response = client.post('/team/login', json={'name': name, 'password': PASSWORD}, headers={'Origin': 'http://testserver'})
    assert response.status_code == 200
    client.headers.update({'Origin': 'http://testserver', 'X-CSRF-Token': response.json()['csrf'], 'X-Project-ID': 'default'})
    return client.get('/team/me').json()


def params():
    return [{'name': k, 'value': v} for k, v in {'execution_location': 'personal', 'api_url': 'https://commercial.invalid/chat/completions', 'model_name': 'fixture-model', 'api_key': 'fixture-credential-not-real', 'max_workers': 1}.items()]


def test_queue_atomic_claim_expiry_and_result_identity(tmp_path):
    queue = PersonalQueue(tmp_path)
    call = queue.enqueue('a', 's', {'body': {'messages': ['fixture']}})
    assert queue.claim('b') is None
    with ThreadPoolExecutor(2) as pool:
        claims = list(pool.map(lambda _: queue.claim('a'), range(2)))
    job, = [c for c in claims if c]
    with pytest.raises(ValueError):
        queue.complete('b', call, job['lease'], {'response': {}})
    with pytest.raises(ValueError):
        queue.complete('a', call, 'wrong', {'response': {}})
    queue.complete('a', call, job['lease'], {'response': {'choices': []}})
    queue.complete('a', call, job['lease'], {'response': {'choices': []}})
    with pytest.raises(ValueError):
        queue.complete('a', call, job['lease'], {'response': {'different': True}})
    assert queue.wait(call) == {'choices': []}
    expired = queue.enqueue('a', 's', {}, seconds=-1)
    assert queue.claim('a') is None
    with pytest.raises(TimeoutError):
        queue.wait(expired)


def test_registry_ownership_and_binding(tmp_path):
    registry = ServingRegistry(str(tmp_path/'serving.yaml'))
    with pytest.raises(ValueError):
        registry._set('fixture', 'APILLMServing_request', params())
    token = identity.set('a')
    try:
        sid = registry._set('fixture', 'APILLMServing_request', params())
        assert registry._get(sid)['owner'] == 'a'
        assert bind({'execution_options': {'personal_actor': 'forged'}})['execution_options']['personal_actor'] == 'a'
    finally:
        identity.reset(token)
    with pytest.raises(ValueError):
        registry._update(sid, name='forbidden')
    with pytest.raises(ValueError):
        registry._delete(sid)
    with pytest.raises(ValueError):
        attach(SimpleNamespace(), registry._get(sid), 'b')


def test_gateway_real_serving_route_mock_runner_roundtrip(tmp_path, monkeypatch):
    from app.api.v1.endpoints.serving import router
    from app.core.container import container
    from app.core.config import settings
    legacy = tmp_path/'project'
    (legacy/'data').mkdir(parents=True)
    registry = ServingRegistry(str(legacy/'data/serving_registry.yaml'))
    monkeypatch.setattr(container, 'serving_registry', registry)
    monkeypatch.setattr(settings, 'BASE_DIR', str(legacy))
    backend = FastAPI()
    backend.include_router(router, prefix='/api/v1/serving')

    @backend.middleware('http')
    async def actor(request: Request, call_next):
        token = identity.set(request.headers.get('x-team-user'))
        try:
            return await call_next(request)
        finally:
            identity.reset(token)

    class Workers:
        async def client(self, project):
            return httpx.AsyncClient(transport=httpx.ASGITransport(app=backend), base_url='http://worker')
        async def close(self):
            pass

    app = create_gateway(tmp_path/'state', Workers(), secure=False)
    uid = app.state.store.initialize('owner', PASSWORD, legacy)
    # Guard the original network transport. The serving must use PersonalSession.
    import requests
    monkeypatch.setattr(requests.Session, 'post', lambda *a, **kw: pytest.fail('school backend attempted upstream HTTP'))
    with TestClient(app) as browser, TestClient(app) as executor, TestClient(app) as other:
        assert executor.post('/team/personal/claim', json={}).status_code == 403
        user = login(browser)
        inv = app.state.store.invite(user, 'other')
        app.state.store.accept(inv['invitation'], PASSWORD)
        app.state.store.member(user, 'default', inv['user_id'], ['develop'], 0)
        login(other, 'other')
        login(executor)
        browser.headers['If-Match'] = '0'
        response = browser.post('/api/v1/serving/', params={'name': 'personal fixture', 'cls_name': 'APILLMServing_request'}, json=params())
        assert response.status_code == 200, response.text
        sid = response.json()['data']['id']
        browser.headers['If-Match'] = '1'
        assert other.get('/api/v1/serving/').json()['data'] == []
        with ThreadPoolExecutor(1) as pool:
            pending = pool.submit(browser.post, '/api/v1/serving/'+sid+'/test', json={'prompt': 'fixture'})
            queue = PersonalQueue(legacy)
            for _ in range(100):
                with queue.connect() as c:
                    count = c.execute('SELECT count(*) FROM calls').fetchone()[0]
                if count:
                    break
                time.sleep(.02)
            assert count == 1
            assert other.post('/team/personal/claim', json={}).json()['job'] is None
            claim = executor.post('/team/personal/claim', json={})
            assert claim.status_code == 200, claim.text
            job = claim.json()['job']
            assert job['api_key'] == ''  # Mock execution needs no credential delivery.
            result = runner.execute(job)  # Default mode cannot send an upstream request.
            stolen = other.post('/team/personal/result', json={'id': job['id'], 'lease': job['lease'], 'result': result})
            assert stolen.status_code == 409
            assert executor.post('/team/personal/result', json={'id': job['id'], 'lease': job['lease'], 'result': result}).status_code == 200
            response = pending.result(timeout=10)
            assert response.status_code == 200, response.text
            assert '模拟响应' in response.json()['data']['response']
        executor.post('/team/logout', json={})
        assert executor.post('/team/personal/claim', json={}).status_code == 401
        assert 'fixture-credential-not-real' not in browser.get('/api/v1/serving/').text
        with queue.connect() as c:
            assert all('fixture-credential-not-real' not in str(tuple(r)) for r in c.execute('SELECT * FROM calls'))


def test_runner_spools_before_upload_and_never_reexecutes(tmp_path, monkeypatch):
    calls = []
    job = {'id': 'fixture', 'lease': 'lease', 'body': {'model': 'fixture'}, 'url': 'https://commercial.invalid', 'api_key': 'not-real'}
    class Platform:
        fail = True
        def request(self, path, body):
            calls.append(path)
            if path.endswith('/claim'):
                return {'job': job if calls.count(path) == 1 else None}
            if self.fail:
                raise ConnectionError()
            return {'ok': True}
    platform = Platform()
    with pytest.raises(ConnectionError):
        runner.run_one(platform, tmp_path)
    saved, = list(tmp_path.glob('*.json'))
    assert 'not-real' not in saved.read_text()
    platform.fail = False
    assert runner.run_one(platform, tmp_path) is False
    assert not list(tmp_path.glob('*.json'))
    assert calls == ['/team/personal/claim', '/team/personal/result', '/team/personal/result', '/team/personal/claim']
    with pytest.raises(ValueError):
        runner.validate_endpoint('http://127.0.0.1/private')


def test_48_concurrent_calls_are_unique_and_ack_recovery_never_rebills(tmp_path, monkeypatch):
    """All 48 must enter upstream before release; ACK failures cannot re-execute."""
    jobs = [{'id': str(i), 'lease': 'fixture-lease', 'api_key': 'fixture-secret',
             'body': {'model': 'fixture'}} for i in range(48)]
    barrier = threading.Barrier(49)
    release = threading.Event()
    executed, acknowledged = [], set()
    lock = threading.Lock()
    coordinator = threading.get_ident()

    def execute(job, real=False):
        with lock:
            executed.append(job['id'])
        barrier.wait(timeout=10)
        assert release.wait(10)
        if job['id'] == '0':
            raise TimeoutError('fixture unknown outcome')
        return {'response': {'choices': [], 'model': 'fixture'}}

    class Platform:
        fail_ack = True
        claims = 0
        def request(self, path, body):
            assert threading.get_ident() == coordinator
            if path.endswith('/claim'):
                self.claims += 1
                return {'job': jobs.pop(0) if jobs else None}
            if self.fail_ack:
                raise ConnectionError('fixture ACK unavailable')
            acknowledged.add(body['id'])
            return {'ok': True}

    monkeypatch.setattr(runner, 'execute', execute)
    platform = Platform()
    executor = runner.ConcurrentExecutor(platform, tmp_path, real=True, concurrency=48)
    try:
        assert executor.step()
        barrier.wait(timeout=10)
        assert len(executed) == len(set(executed)) == 48
        release.set()
        for future in executor.pending.values():
            future.result(timeout=10)
        assert len(list(tmp_path.glob('*.json'))) == 48
        assert all('fixture-secret' not in p.read_text() for p in tmp_path.glob('*.json'))
        with pytest.raises(ConnectionError):
            executor.step()
        assert platform.claims == 48
        platform.fail_ack = False
        assert executor.step() is False
        assert len(acknowledged) == 48 and len(executed) == 48
        assert not list(tmp_path.glob('*.json'))
    finally:
        release.set()
        platform.fail_ack = False
        executor.close()


def test_personal_transport_honors_48_workers_but_disables_retries(tmp_path, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, 'BASE_DIR', str(tmp_path))
    info = {'id': 'fixture', 'owner': 'owner', 'params': [
        {'name': 'execution_location', 'value': 'personal'},
        {'name': 'max_workers', 'value': 48}]}
    instance = SimpleNamespace(session=SimpleNamespace(close=lambda: None), max_workers=1, max_retries=5)
    assert attach(instance, info, 'owner').max_workers == 48
    assert instance.max_retries == 1
    info['params'][-1]['value'] = 49
    with pytest.raises(ValueError):
        attach(instance, info, 'owner')


@pytest.mark.parametrize('path', ['sync', 'ray'])
def test_pipeline_loops_use_personal_transport(tmp_path, monkeypatch, path):
    from app.core.container import container
    from app.core.config import settings
    from app.services.task_registry import TaskRegistry
    from app.services import dataflow_engine, ray_pipeline_executor
    from dataflow.utils.registry import OPERATOR_REGISTRY
    source = tmp_path/'input.jsonl'
    source.write_text('{"text":"fixture source"}\n')
    (tmp_path/'core/api_pipelines').mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(settings, 'CACHE_DIR', str(tmp_path/'cache'))
    monkeypatch.setattr(settings, 'DATAFLOW_CORE_DIR', str(tmp_path/'core'))
    monkeypatch.setattr(container, 'dataset_registry', SimpleNamespace(get=lambda _: {'root': str(source)}))
    monkeypatch.setattr(container, 'data_library', None)
    registry = ServingRegistry(str(tmp_path/'serving.yaml'))
    monkeypatch.setattr(container, 'serving_registry', registry)
    token = identity.set('a')
    try:
        sid = registry._set('fixture', 'APILLMServing_request', params())
        config = {'file_path': '', 'input_dataset': {'id': 'source'}, 'operators': [
            {'name': 'PersonalFixtureGenerator', 'params': {'init': [{'name': 'llm_serving', 'value': sid}], 'run': []}}]}
        tasks = TaskRegistry(str(tmp_path/'tasks.json'))
        tid, frozen, _ = tasks.start_execution(config=config)
        runtime = dataflow_engine.DataFlowEngine.decode_hashed_arguments(frozen, tid)
    finally:
        identity.reset(token)
    from dataflow.core import OperatorABC
    class Operator(OperatorABC):
        def __init__(self, llm_serving):
            super().__init__()
            self.llm_serving = llm_serving
        def run(self, storage):
            frame = storage.read('dataframe')
            frame['answer'] = self.llm_serving.generate_from_input(['fixture prompt'])
            storage.write(frame)
            return ['answer']
    monkeypatch.setattr(OPERATOR_REGISTRY, 'get', lambda _: Operator)
    monkeypatch.setattr(OPERATOR_REGISTRY, '_get_all', lambda: None)
    import requests
    monkeypatch.setattr(requests.Session, 'post', lambda *a, **kw: pytest.fail('pipeline attempted upstream network'))
    with ThreadPoolExecutor(1) as pool:
        if path == 'sync':
            pending = pool.submit(dataflow_engine.DataFlowEngine().run, frozen, tid, tasks.path)
        else:
            pending = pool.submit(ray_pipeline_executor.dataflow_pipeline_execute, frozen, runtime, tid, tasks.path)
        queue = PersonalQueue(tmp_path)
        for _ in range(200):
            job = queue.claim('a')
            if job:
                break
            if pending.done():
                pytest.fail(str(pending.result()))
            time.sleep(.02)
        assert job
        assert job['body']['messages'][-1]['content'] == 'fixture prompt'
        queue.complete('a', job['id'], job['lease'], runner.execute(job))
        result = pending.result(timeout=10)
    assert result['status'] == 'completed', result


def test_mock_cannot_claim_real_job(tmp_path):
    queue = PersonalQueue(tmp_path)
    queue.enqueue('a', 's', {'mode': 'real'})
    assert queue.claim('a', 'mock') is None
    assert queue.claim('a', 'real')


def test_standard_library_runner_login_claim_and_return_over_http(tmp_path):
    """Actual local HTTP + cookies/CSRF, without any commercial HTTP request."""
    import socket
    import uvicorn
    class Workers:
        async def close(self):
            pass
    app = create_gateway(tmp_path/'state', Workers(), secure=False)
    project = tmp_path/'project'
    uid = app.state.store.initialize('owner', PASSWORD, project)
    (project/'data').mkdir(parents=True)
    registry = ServingRegistry(str(project/'data/serving_registry.yaml'))
    token = identity.set(uid)
    try:
        sid = registry._set('fixture', 'APILLMServing_request', params())
    finally:
        identity.reset(token)
    queue = PersonalQueue(project)
    call = queue.enqueue(uid, sid, {'mode': 'mock', 'url': 'https://commercial.invalid/chat/completions', 'body': {'model': 'fixture'}})
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level='critical'))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(.01)
        platform = runner.Platform('http://127.0.0.1:'+str(port))
        user = platform.login('owner', PASSWORD)
        assert user['id'] == uid
        spool = tmp_path/'spool'
        spool.mkdir()
        assert runner.run_one(platform, spool)
        assert queue.wait(call)['mock'] is True
        (project/'data/task_registry.json').write_text(json.dumps({'tasks': {'cancelled-task': {'status': 'cancelled'}}}))
        cancelled = queue.enqueue(uid, sid, {'mode': 'mock', 'task_id': 'cancelled-task', 'url': 'https://commercial.invalid/chat/completions', 'body': {'model': 'fixture'}})
        assert runner.run_one(platform, spool) is False
        with pytest.raises(RuntimeError):
            queue.wait(cancelled)
        platform.request('/team/logout', {})
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
