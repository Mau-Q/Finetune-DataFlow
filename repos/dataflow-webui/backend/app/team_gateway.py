"""Same-origin gateway for authenticated LAN and opt-in local development."""
import asyncio
from contextlib import asynccontextmanager
import json
import re
import os
from pathlib import Path
import secrets
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from app.services.data_library import LibraryError
from app.services.team_store import TeamStore, digest, password_hash, verify
from app.services.project_workers import Workers
from app.services.development_access import require_local

BACKEND = Path(__file__).resolve().parents[1]
DIST = BACKEND.parent / 'frontend/dist'



def clean_secrets(obj):
    if isinstance(obj,list):return [clean_secrets(v) for v in obj]
    if isinstance(obj,dict):
        if str(obj.get('name','')).lower() in {'api_key','password','secret','token','access_token'}:
            return {k: ('****' if k in {'value','default_value'} and v else clean_secrets(v)) for k,v in obj.items()}
        return {k: ('****' if k.lower() in {'api_key','password','secret','token','access_token'} and v else clean_secrets(v)) for k,v in obj.items()}
    return obj


def policy(path, method, roles, *, local=False):
    """Fail closed. Adding a route requires updating the audited LAN inventory."""
    inventory=json.loads((BACKEND/'app/team_routes.json').read_text('utf-8'))
    def matches(route):
        pattern=re.sub(r'\{[^}]+\}', '[^/]+', route['path'])
        return re.fullmatch(pattern,path) and (route['method']==method or method=='HEAD' and route['method']=='GET')
    if not any(matches(route) for route in inventory):raise LibraryError('团队模式未开放此入口',403)
    if path.startswith('/api/v1/team-data/'):
        if '/reviews' in path and method=='GET':return
        if path.endswith('/reopen') and set(roles)&{'manage','develop'}:return
        if path.endswith('/release') and set(roles)&{'manage','develop'}:return
        if any(path.endswith('/'+s) for s in ('claim','release','save','submit','revise','reopen')):
            if 'review' in roles:return
        elif set(roles)&{'manage','develop'}:return
        raise LibraryError('无此操作权限',403)
    if not set(roles)&{'manage','develop'}:raise LibraryError('需要项目开发权限',403)
    route = path.removeprefix('/api/v1/').split('/')[0]
    if route not in {'library','datasets','operators','tasks','pipelines','prompts','serving','text2sql_database','text2sql_database_manager','json_schemas','generation','multimodal','training'}:
        raise LibraryError('团队模式未开放此入口',403)
    if local:
        return
    if any(part in path for part in ('choose-local','import-local','list_dir','/result-storage/choose','/materials/register','/results/import')) or (route=='datasets' and method=='POST' and path.rstrip('/')=='/api/v1/datasets'):
        raise LibraryError('请使用上传，团队模式不开放任意主机路径',403)
    if route in {'text2sql_database','text2sql_database_manager'}:
        raise LibraryError('团队模式未开放主机数据库入口',403)
    if path.startswith('/api/v1/training/host'):
        if 'manage' not in roles:raise LibraryError('需要项目管理权限',403)


def create_gateway(state=None, workers=None, secure=None, development=None, workspace=None):
    development = development if development is not None else os.environ.get("DATAFLOW_DEV_AUTO_LOGIN") == "1"
    workspace = Path(workspace or os.environ.get('DATAFLOW_WORKSPACE_DIR') or BACKEND).resolve()
    store=TeamStore(state or os.environ.get('DATAFLOW_TEAM_DIR',BACKEND/'data/collaboration'))
    workers=workers or Workers(store.root)
    secure=secure if secure is not None else os.environ.get('DATAFLOW_COOKIE_SECURE','1')=='1'
    @asynccontextmanager
    async def lifespan(app):
        yield
        await workers.close()
    app=FastAPI(title='DataFlow LAN',docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)
    app.state.store=store
    app.state.workers=workers
    app.state.write_locks={}

    @app.exception_handler(LibraryError)
    async def library_error(request,exc):
        return JSONResponse({'detail':str(exc)},status_code=exc.status)

    @app.middleware('http')
    async def security(request,call_next):
        if development:
            try:
                require_local(request)
            except LibraryError as exc:
                return JSONResponse({'detail':str(exc)},status_code=exc.status)
        # Mutations require an explicit same-origin Origin even on login/accept.
        if request.method not in {'GET','HEAD','OPTIONS'}:
            origin=request.headers.get('origin','')
            expected=str(request.base_url).rstrip('/')
            if origin!=expected:
                return JSONResponse({'detail':'写操作需要同源 Origin'},status_code=403)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='same-origin'
        response.headers['X-Frame-Options']='DENY'
        if request.url.path.startswith(('/api/','/team/')):response.headers['Cache-Control']='no-store'
        return response

    def actor(request,write=True):
        user=store.identity(request.cookies.get('df_session'))
        if not development and user['id'] == 'local-development':
            raise LibraryError('开发会话不可用于普通登录模式', 401)
        if write and request.method not in {'GET','HEAD'} and not secrets.compare_digest(request.headers.get('x-csrf-token',''),user['csrf']):
            raise LibraryError('会话校验失败，请刷新',403)
        return user

    async def object_body(request):
        try:value=await request.json()
        except ValueError as exc:raise LibraryError('JSON 无效',400) from exc
        if not isinstance(value,dict):raise LibraryError('请求必须为 JSON 对象',400)
        return value

    def personal_project(request):
        user = actor(request)
        project = store.access(user['id'], request.headers.get('x-project-id') or user['project'])
        if not set(project['roles']) & {'manage', 'develop'}:
            raise LibraryError('需要项目开发权限', 403)
        return user, project

    @app.post('/team/personal/claim')
    async def claim_personal(request: Request):
        import yaml
        from app.services.personal_execution import PersonalQueue, values
        user, project = personal_project(request)
        queue = PersonalQueue(project['root'])
        body = await object_body(request)
        mode = body.get('mode', 'mock')
        if mode not in {'mock', 'real'}:
            raise LibraryError('执行模式无效', 400)
        job = queue.claim(user['id'], mode)
        if job:
            task_id = job.get('task_id')
            if task_id:
                task_file = Path(project['root']) / 'data/task_registry.json'
                tasks = json.loads(task_file.read_text('utf-8')).get('tasks', {}) if task_file.exists() else {}
                task = tasks.get(task_id, {})
                if task.get('status') not in {'queued', 'running'}:
                    queue.complete(user['id'], job['id'], job['lease'], {'error': True})
                    return {'job': None}
            # Credentials are delivered only to their owner over the existing login.
            registry = Path(project['root']) / 'data/serving_registry.yaml'
            records = yaml.safe_load(registry.read_text('utf-8')) or {}
            info = records.get(job['serving'], {})
            if info.get('owner') != user['id'] or values(info).get('execution_location') != 'personal':
                queue.complete(user['id'], job['id'], job['lease'], {'error': True})
                raise LibraryError('个人 Serving 已删除或执行位置已变更', 409)
            config = values(info)
            key = config.get('api_key') or os.environ.get(config.get('key_name_of_api_key') or '', '')
            import hashlib
            fingerprint = hashlib.sha256(('Bearer '+key).encode()).hexdigest()
            if (config.get('personal_api_mode', 'mock') != mode
                    or config.get('api_url') != job.get('url')
                    or (mode == 'real' and not secrets.compare_digest(fingerprint, job.get('credential_fingerprint', '')))):
                queue.complete(user['id'], job['id'], job['lease'], {'error': True})
                raise LibraryError('Serving 已变更，请重新提交任务', 409)
            job.pop('credential_fingerprint', None)
            job['api_key'] = key if mode == 'real' else ''
        return {'job': job}

    @app.post('/team/personal/result')
    async def finish_personal(request: Request):
        from app.services.personal_execution import PersonalQueue
        user, project = personal_project(request)
        body = await object_body(request)
        try:
            PersonalQueue(project['root']).complete(user['id'], body.get('id'), str(body.get('lease', '')), body.get('result', {}))
        except (ValueError, TypeError) as exc:
            raise LibraryError(str(exc), 409) from exc
        return {'ok': True}

    @app.get('/team/status')
    def status():
        with store.tx() as c:initialized=bool(c.execute('SELECT 1 FROM users').fetchone())
        return {'mode':'lan','initialized':initialized,'development':development}

    @app.post('/team/dev-login')
    async def development_login(request:Request):
        if not development:
            raise LibraryError('开发自动登录未启用', 404)
        require_local(request)
        token, csrf = store.development_login(workspace)
        response = JSONResponse({'csrf':csrf})
        response.set_cookie('df_session',token,httponly=True,secure=secure,samesite='strict',max_age=43200)
        return response

    @app.post('/team/login')
    async def login(request:Request):
        body=await object_body(request)
        token,csrf=store.login(body.get('name'),body.get('password'),request.client.host)
        result=JSONResponse({'csrf':csrf})
        result.set_cookie('df_session',token,httponly=True,secure=secure,samesite='strict',max_age=43200)
        return result

    @app.post('/team/accept')
    async def accept(request:Request):
        body=await object_body(request);store.accept(body.get('invitation',''),body.get('password'));return {'ok':True}

    @app.get('/team/me')
    def me(request:Request):
        user=actor(request)
        return dict(user,projects=store.projects(user['id']))

    @app.post('/team/logout')
    def logout(request:Request):
        user=actor(request)
        with store.tx() as c:
            c.execute('DELETE FROM sessions WHERE token=?',(digest(request.cookies.get('df_session','')),))
            store.audit(c,user['id'],user['project'],'logout')
        response=JSONResponse({'ok':True});response.delete_cookie('df_session');return response

    @app.post('/team/password')
    async def password(request:Request):
        user=actor(request);body=await object_body(request);hashed=password_hash(body.get('password'))
        with store.tx() as c:
            old=c.execute('SELECT password FROM users WHERE id=?',(user['id'],)).fetchone()[0]
            if not verify(body.get('current'),old):raise LibraryError('当前密码无效',400)
            c.execute('UPDATE users SET password=? WHERE id=?',(hashed,user['id']))
            c.execute('DELETE FROM sessions WHERE user=?',(user['id'],))
            store.audit(c,user['id'],None,'change-password')
        return {'ok':True}

    @app.post('/team/project')
    async def select_project(request:Request):
        user=actor(request);body=await object_body(request);project=store.access(user['id'],body.get('project'))
        with store.tx() as c:c.execute('UPDATE sessions SET project=? WHERE token=?',(project['id'],digest(request.cookies.get('df_session',''))))
        return {'ok':True}

    @app.post('/team/projects')
    async def create_project(request:Request):
        user=actor(request)
        if not user['admin']:raise LibraryError('需要系统管理权限',403)
        body=await object_body(request);name=body.get('name','').strip()
        if not name or len(name)>120:raise LibraryError('项目名称无效')
        pid='p_'+secrets.token_hex(12);root=store.root/'projects'/pid;root.mkdir(parents=True,mode=0o700)
        with store.tx() as c:
            c.execute('INSERT INTO projects VALUES(?,?,?)',(pid,name,str(root)))
            c.execute('INSERT INTO members(project,user,roles) VALUES(?,?,?)',(pid,user['id'],'manage,develop,review'))
            store.audit(c,user['id'],pid,'create-project',pid)
        return {'id':pid,'name':name}

    @app.get('/team/admin/projects')
    def admin_projects(request:Request):
        user=actor(request)
        if not user['admin']:raise LibraryError('需要系统管理权限',403)
        with store.tx() as c:return [dict(r) for r in c.execute('SELECT id,name FROM projects')]

    @app.post('/team/admin/projects/{pid}/enter')
    def admin_enter(pid:str,request:Request):
        user=actor(request)
        if not user['admin']:raise LibraryError('需要系统管理权限',403)
        with store.tx() as c:
            if not c.execute('SELECT 1 FROM projects WHERE id=?',(pid,)).fetchone():raise LibraryError('项目不存在',404)
            c.execute("INSERT INTO members(project,user,roles) VALUES(?,?,'manage,develop,review') ON CONFLICT(project,user) DO UPDATE SET roles=excluded.roles,version=members.version+1",(pid,user['id']))
            c.execute('UPDATE sessions SET project=? WHERE token=?',(pid,digest(request.cookies.get('df_session',''))))
            store.audit(c,user['id'],pid,'system-admin-enter',pid)
        return {'ok':True}

    @app.get('/team/users')
    def users(request:Request):
        user=actor(request)
        if not user['admin']:raise LibraryError('需要系统管理权限',403)
        with store.tx() as c:return [dict(r) for r in c.execute('SELECT id,name,admin,enabled FROM users')]

    @app.post('/team/invitations')
    async def invite(request:Request):
        user=actor(request);body=await object_body(request)
        return store.invite(user,body.get('name'),body.get('admin',False),body.get('ttl',3600),body.get('reset'))

    @app.post('/team/users/{uid}/enabled')
    async def enabled(uid:str,request:Request):
        user=actor(request);body=await object_body(request)
        if not isinstance(body.get('enabled'),bool):raise LibraryError('状态无效')
        store.disable(user,uid,body['enabled']);return {'ok':True}

    @app.get('/team/projects/{pid}/reviewers')
    def eligible_reviewers(pid:str,request:Request):
        user=actor(request);project=store.access(user['id'],pid)
        if not set(project['roles'])&{'manage','develop'}:raise LibraryError('需要开发权限',403)
        with store.tx() as c:
            return [{'id':r['id'],'name':r['name']} for r in c.execute('SELECT u.id,u.name,m.roles FROM users u JOIN members m ON m.user=u.id WHERE m.project=? AND u.enabled=1',(pid,)) if 'review' in r['roles'].split(',')]

    @app.get('/team/projects/{pid}/members')
    def members(pid:str,request:Request):
        user=actor(request);project=store.access(user['id'],pid)
        if 'manage' not in project['roles']:raise LibraryError('需要项目管理权限',403)
        with store.tx() as c:return [dict(r,roles=r['roles'].split(',')) for r in c.execute('SELECT m.user,u.name,m.roles,m.version FROM members m JOIN users u ON u.id=m.user WHERE project=?',(pid,))]

    @app.put('/team/projects/{pid}/members/{uid}')
    async def member(pid:str,uid:str,request:Request):
        user=actor(request);body=await object_body(request);store.member(user,pid,uid,body.get('roles'),body.get('version'));return {'ok':True}

    @app.get('/team/audit')
    def audit(request:Request,project:str):
        user=actor(request);p=store.access(user['id'],project)
        if 'manage' not in p['roles']:raise LibraryError('需要项目管理权限',403)
        with store.tx() as c:return [dict(r) for r in c.execute('SELECT * FROM audit WHERE project=? ORDER BY id DESC LIMIT 200',(project,))]

    @app.api_route('/api/v1/preferences/',methods=['GET','POST'])
    async def preferences(request:Request):
        user=actor(request)
        with store.tx() as c:
            if request.method=='POST':
                body=await object_body(request);body={k:body[k] for k in ('language','theme') if k in body}
                c.execute('UPDATE users SET preferences=? WHERE id=?',(json.dumps(body),user['id']))
            row=c.execute('SELECT preferences FROM users WHERE id=?',(user['id'],)).fetchone()
            return {'code':200,'data':json.loads(row[0])}

    @app.api_route('/api/{rest:path}',methods=['GET','HEAD','POST','PUT','PATCH','DELETE'])
    async def proxy(rest:str,request:Request):
        user=actor(request);pid=request.headers.get('x-project-id') or user['project']
        if not pid:raise LibraryError('请选择项目',400)
        project=store.access(user['id'],pid)
        policy(request.url.path,request.method,project['roles'],local=development)
        body=await request.body()
        payload = {}
        # Host paths may only be referenced if they are managed by this project.
        if body and 'application/json' in request.headers.get('content-type',''):
            try:payload=json.loads(body)
            except ValueError:raise LibraryError('JSON 无效')
            def check_paths(value):
                if isinstance(value,dict):
                    for key,v in value.items():
                        if key in {'path','root','output_dir','output_root','output_path','file_path','local_path','working_dir','result_path'} and isinstance(v,str) and v:
                            path=Path(v).expanduser().resolve()
                            if not path.is_relative_to(Path(project['root']).resolve()):
                                raise LibraryError('路径必须属于当前项目受管目录，请使用上传',403)
                        check_paths(v)
                elif isinstance(value,list):
                    for v in value:check_paths(v)
            if not development:
                check_paths(payload)
        if request.url.path=='/api/v1/team-data/reviews' and request.method=='POST':
            for reviewer in payload.get('reviewers',[]):
                if 'review' not in store.access(reviewer,pid)['roles']:raise LibraryError('评测成员未获当前项目评测权限',400)
        if request.url.path.startswith('/api/v1/serving') and request.method not in {'GET', 'HEAD'} and 'manage' not in project['roles']:
            import yaml
            from app.services.personal_execution import values, personal
            registry_path = Path(project['root']) / 'data/serving_registry.yaml'
            records = yaml.safe_load(registry_path.read_text('utf-8')) or {} if registry_path.exists() else {}
            sid = request.url.path.removeprefix('/api/v1/serving/').split('/')[0]
            existing = records.get(sid)
            if existing and (not personal(existing) or existing.get('owner') != user['id']):
                raise LibraryError('只能修改或测试自己的个人 Serving', 403)
            proposed = values(existing or {})
            submitted = payload if isinstance(payload, list) else payload.get('params', [])
            if isinstance(submitted, list):
                proposed.update({p['name']: p.get('value') for p in submitted if isinstance(p, dict) and 'name' in p})
            if proposed.get('execution_location') != 'personal':
                raise LibraryError('服务器 Serving 需要项目管理权限', 403)
        headers={k:v for k,v in request.headers.items() if k.lower() in {'content-type','accept','if-match'}}
        headers.update({'x-team-user':user['id'],'x-team-roles':','.join(project['roles'])})
        # Serialize gateway writes per project; workers retain their own file/DB locks.
        async with app.state.write_locks.setdefault(pid,asyncio.Lock()):
            versioned = not request.url.path.startswith('/api/v1/team-data/')
            with store.tx() as c:
                row=c.execute("SELECT version FROM versions WHERE project=? AND object='*'",(pid,)).fetchone()
                version=row[0] if row else 0
            if versioned and request.method not in {'GET','HEAD'} and request.headers.get('if-match') != str(version):
                raise LibraryError('内容已更新，请刷新后保留并重新提交编辑',409)
            client=await workers.client(project)
            async with client:
                response=await client.request(request.method,request.url.path,params=request.query_params,content=body,headers=headers)
            effective_status=response.status_code
            if 'application/json' in response.headers.get('content-type',''):
                result=response.json()
                if isinstance(result,dict) and result.get('success') is False:
                    effective_status=int((result.get('meta') or {}).get('http_status') or 400)
            if versioned and request.method not in {'GET','HEAD'} and effective_status<400:
                version+=1
                with store.tx() as c:c.execute("INSERT INTO versions VALUES(?,'*',?) ON CONFLICT(project,object) DO UPDATE SET version=excluded.version",(pid,version))
        output=response.content
        # Scrub actual configured key values even when legacy errors embed them in text.
        known=[]
        try:
            import yaml
            configured=yaml.safe_load((Path(project['root'])/'data/serving_registry.yaml').read_text('utf-8')) or {}
            for serving in configured.values():
                for param in serving.get('params',[]):
                    if param.get('name') in {'api_key','password','secret','access_token'}:
                        known.extend(v for v in (param.get('value'),param.get('default_value')) if isinstance(v,str) and len(v)>=8)
        except (OSError,ValueError,AttributeError):pass
        response_headers={k:v for k,v in response.headers.items() if k.lower() in {'content-type','content-disposition','etag','x-resource-version'}}
        response_headers['X-Resource-Version']=str(version)
        if 'application/json' in response.headers.get('content-type',''):
            try:output=json.dumps(clean_secrets(response.json()),ensure_ascii=False).encode()
            except ValueError:pass
            for secret in known:output=output.replace(secret.encode(),b'****')
        if request.method not in {'GET','HEAD'}:
            with store.tx() as c:store.audit(c,user['id'],pid,request.method,request.url.path,str(effective_status))
        return Response(output,status_code=effective_status,headers=response_headers)

    @app.api_route('/mcp{rest:path}',methods=['GET','POST','DELETE'])
    async def no_mcp(rest:str):
        raise LibraryError('团队模式未开放 MCP',403)

    @app.websocket('/{rest:path}')
    async def no_websocket(websocket: WebSocket,rest):
        await websocket.close(code=1008)

    if DIST.exists():app.mount('/',StaticFiles(directory=DIST,html=True),name='ui')
    return app

app=create_gateway()
