import httpx
from fastapi import FastAPI,Request
from fastapi.testclient import TestClient
from app.team_gateway import create_gateway
from app.services.team_store import TeamStore

PASS='isolated-password-test-123'


class FakeWorkers:
    def __init__(self):self.calls=[];self.message="safe";self.error=False
    async def client(self,project):
        app=FastAPI()
        @app.api_route('/{path:path}',methods=['GET','POST','PUT','DELETE'])
        async def resource(path:str,request:Request):
            self.calls.append((project['id'],path))
            if self.error:return {'success':False,'message':'missing','meta':{'http_status':404}}
            return {'code':200,'data':{'project':project['id'],'api_key':'secret-that-must-not-leak','log_message':self.message}}
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://worker')
    async def close(self):pass


def login(client,name='owner'):
    r=client.post('/team/login',json={'name':name,'password':PASS},headers={'Origin':'http://testserver'})
    assert r.status_code==200,r.text
    client.headers.update({'Origin':'http://testserver','X-CSRF-Token':r.json()['csrf']})
    return client.get('/team/me').json()


def test_gateway_isolation_revocation_and_versions(tmp_path):
    workers=FakeWorkers();app=create_gateway(tmp_path/'state',workers,secure=False);s=app.state.store;s.initialize('owner',PASS,tmp_path/'legacy')
    with TestClient(app) as owner, TestClient(app) as reader, TestClient(app) as other:
        assert owner.get('/api/v1/library/drafts').status_code==401
        a=login(owner)
        inv=s.invite(a,'reader');s.accept(inv['invitation'],PASS);s.member(a,'default',inv['user_id'],['review'],0)
        inv2=s.invite(a,'other');s.accept(inv2['invitation'],PASS)
        p=owner.post('/team/projects',json={'name':'Second'}).json()['id']
        s.member(a,p,inv2['user_id'],['develop'],0)
        login(reader,'reader');login(other,'other')
        owner.headers['X-Project-ID']='default';reader.headers['X-Project-ID']='default';other.headers['X-Project-ID']=p
        assert owner.get('/api/v1/library/drafts').json()['data']['api_key']=='****'
        assert other.get('/api/v1/library/drafts').json()['data']['project']==p
        other.headers['X-Project-ID']='default'
        for path in ['/api/v1/library/drafts/foreign','/api/v1/tasks/execution/foreign/logs','/api/v1/generation/releases/foreign/download']:
            assert other.get(path).status_code==404
        for path in ['/api/v1/pipelines/','/api/v1/serving/','/api/v1/library/materials','/api/v1/datasets/list_dir?path=/etc']:
            assert reader.get(path).status_code==403
        assert reader.post('/api/v1/generation/drafts/x/publish',json={}).status_code==403
        assert owner.post('/api/v1/agent/start',json={}).status_code==403
        assert owner.get('/mcp').status_code==403
        assert owner.get('/data/datasets.sqlite3').status_code==404
        owner.headers['If-Match']='0'
        assert owner.put('/api/v1/pipelines/x',json={}).status_code==200
        assert owner.put('/api/v1/pipelines/x',json={}).status_code==409
        owner.headers['If-Match']='1'
        assert owner.post('/api/v1/library/materials/register',json={'path':'/etc/passwd'}).status_code==403
        assert owner.post('/api/v1/pipelines/',json={'config':{'output_dir':'/etc'}}).status_code==403
        reader.post('/api/v1/preferences/',json={'theme':'dark'})
        assert owner.get('/api/v1/preferences/').json()['data']['theme']=='light'
        assert reader.get('/api/v1/preferences/').json()['data']['theme']=='dark'
        assert owner.post('/team/logout',json={}).status_code==200
        assert owner.get('/team/me').status_code==401


def test_csrf_origin_and_login_rate_limit(tmp_path):
    app=create_gateway(tmp_path/'state',FakeWorkers(),secure=False);app.state.store.initialize('owner',PASS,tmp_path/'legacy')
    with TestClient(app) as client:
        assert client.post('/team/login',json={}).status_code==403
        assert client.post('/team/login',json={},headers={'Origin':'https://attacker'}).status_code==403
        login(client)
        assert client.post('/team/projects',json={'name':'x'},headers={'X-CSRF-Token':'wrong'}).status_code==403
        for _ in range(10):client.post('/team/login',json={'name':'bad','password':'wrong'},headers={'Origin':'http://testserver'})
        assert client.post('/team/login',json={'name':'bad','password':'wrong'},headers={'Origin':'http://testserver'}).status_code==429


def test_explicit_admin_entry_is_audited(tmp_path):
    app=create_gateway(tmp_path/'state',FakeWorkers(),secure=False);s=app.state.store;s.initialize('owner',PASS,tmp_path/'legacy')
    with TestClient(app) as client:
        a=login(client);pid=client.post('/team/projects',json={'name':'Project'}).json()['id']
        s.member(a,pid,a['id'],[],1)
        assert all(p['id']!=pid for p in client.get('/team/me').json()['projects'])
        assert client.post('/team/admin/projects/'+pid+'/enter',json={}).status_code==200
        assert client.get('/team/me').json()['project']==pid
        with s.tx() as c:assert c.execute("SELECT count(*) FROM audit WHERE action='system-admin-enter' AND project=?",(pid,)).fetchone()[0]==1


def test_nested_credentials_embedded_logs_and_legacy_http_status(tmp_path):
    import json
    workers=FakeWorkers();legacy=tmp_path/'legacy';(legacy/'data').mkdir(parents=True)
    secret='isolated-fixture-credential-value'
    (legacy/'data/serving_registry.yaml').write_text(json.dumps({'service':{'params':[{'name':'api_key','value':secret}]}}))
    app=create_gateway(tmp_path/'state',workers,secure=False);app.state.store.initialize('owner',PASS,legacy)
    with TestClient(app) as client:
        login(client);client.headers['X-Project-ID']='default';workers.message='Upstream error included '+secret
        r=client.get('/api/v1/serving/')
        assert secret not in r.text and '****' in r.text
        workers.error=True
        assert client.get('/api/v1/library/drafts/missing').status_code==404


def test_development_keeps_native_local_paths_and_csrf(tmp_path):
    app = create_gateway(tmp_path/'state', FakeWorkers(), secure=False,
                         development=True, workspace=tmp_path/'workspace')
    with TestClient(app, base_url='http://127.0.0.1', client=('127.0.0.1', 1)) as client:
        client.headers['Origin'] = 'http://127.0.0.1'
        result = client.post('/team/dev-login').json()
        client.headers.update({'X-CSRF-Token': result['csrf'], 'If-Match': '0'})
        # Local output directories may live outside the backend workspace.
        response = client.post('/api/v1/library/materials/register',
                               json={'path': str(tmp_path/'external source.txt')})
        assert response.status_code == 200, response.text
        client.headers['X-CSRF-Token'] = 'wrong'
        assert client.post('/api/v1/library/inputs/choose-local').status_code == 403
