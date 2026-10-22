"""Project-local collaboration endpoints, reachable only through the team gateway."""
from fastapi import APIRouter, HTTPException, Request, Query
from app.core.container import container
from app.services.data_library import LibraryError
from app.services.source_progress import SourceProgress

router=APIRouter(tags=['team-data'])


def call(fn,*args,**kwargs):
    try:return fn(*args,**kwargs)
    except LibraryError as exc:raise HTTPException(exc.status,str(exc)) from exc
    except (TypeError,KeyError,AttributeError,ValueError) as exc:raise HTTPException(400,'请求字段无效，请检查数据和配置') from exc


@router.get('/sources')
def sources(offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=200),generated:bool|None=None,published:bool|None=None,active:bool|None=None,pending:bool|None=None,unknown_source:bool|None=None,source:str|None=None):
    service=SourceProgress(container.dataset_registry,container.data_library,container.task_registry)
    return call(service.page,offset,limit,dict(generated=generated,published=published,active=active,pending=pending,unknown_source=unknown_source),source)


async def object_body(request):
    try:
        value=await request.json()
    except ValueError as exc:raise HTTPException(400,'JSON 无效') from exc
    if not isinstance(value,dict):raise HTTPException(400,'请求必须为 JSON 对象')
    return value


def reviews():
    from app.services.data_reviews import DataReviews
    return DataReviews(container.data_library,container.task_registry)


def identity(request):
    # Team gateway supplies these on a private socket; single-user local mode is host owned.
    import os
    if os.environ.get('DATAFLOW_TEAM_WORKER') and not request.headers.get('x-team-user'):
        raise HTTPException(403,'请通过团队入口访问')
    return request.headers.get('x-team-user','local'),request.headers.get('x-team-roles','manage,develop,review').split(',')


@router.get('/reviews')
def list_reviews(request:Request):
    user,roles=identity(request)
    return call(reviews().list,user,roles)


@router.post('/reviews')
async def create_review(request:Request):
    user,roles=identity(request)
    if not set(roles)&{'manage','develop'}:raise HTTPException(403,'需要开发权限')
    return call(reviews().create,await object_body(request),user)


@router.get('/reviews/{bid}')
def review_detail(bid:str,request:Request):
    user,roles=identity(request)
    return call(reviews().detail,bid,user,roles)


@router.post('/reviews/{bid}/close')
async def close_review(bid:str,request:Request):
    user,roles=identity(request);body=await object_body(request)
    return call(reviews().close,bid,user,roles,body.get('version'))


@router.post('/reviews/{bid}/derive')
def derive_review(bid:str,request:Request):
    user,roles=identity(request)
    return call(reviews().derive,bid,user,roles)


@router.post('/reviews/{bid}/items/{iid}/{operation}')
async def review_action(bid:str,iid:str,operation:str,request:Request):
    user,roles=identity(request)
    return call(reviews().action,bid,iid,operation,await object_body(request),user,roles)


@router.get('/reviews/{bid}/items/{iid}/media/{mid}')
def review_media(bid:str,iid:str,mid:str,request:Request):
    from fastapi.responses import FileResponse
    user,roles=identity(request);batch=call(reviews().detail,bid,user,roles)
    item=next((i for i in batch['items'] if i['id']==iid),None)
    if not item:raise HTTPException(404,'评测项不存在')
    refs=call(container.data_library._validate_row,item['row'],batch['modality'],batch['training_type'])
    mids={batch['media_bindings'].get(ref) for ref in refs}
    if mid not in mids:raise HTTPException(404,'媒体不存在')
    path,meta=call(container.data_library.material_file,mid)
    return FileResponse(path,media_type=meta['mime_type'],headers={'X-Content-Type-Options':'nosniff'},content_disposition_type='inline')


def exports():
    from app.services.data_exports import DataExports
    return DataExports(container.data_library)


@router.get('/exports')
def list_exports(request:Request):
    user,roles=identity(request)
    if not set(roles)&{'manage','develop'}:raise HTTPException(403,'需要开发权限')
    return call(exports().list)


@router.post('/exports/preview')
async def preview_export(request:Request):
    user,roles=identity(request)
    if not set(roles)&{'manage','develop'}:raise HTTPException(403,'需要开发权限')
    return call(exports().preview,await object_body(request),user,roles)


@router.post('/exports')
async def create_export(request:Request):
    import os
    user,roles=identity(request)
    return call(exports().create,await object_body(request),user,roles,os.environ.get('DATAFLOW_PROJECT_ID','local'))


@router.get('/exports/{eid}/download')
def download_export(eid:str,request:Request):
    from fastapi.responses import FileResponse
    user,roles=identity(request)
    if not set(roles)&{'manage','develop'}:raise HTTPException(403,'需要开发权限')
    path=call(exports().download,eid)
    return FileResponse(path,filename=path.name)


@router.get('/reviews/{bid}/items/{iid}/context/{cid}')
def review_context(bid:str,iid:str,cid:str,request:Request):
    from pathlib import Path
    from fastapi.responses import FileResponse
    from app.services.data_library import _hash
    user,roles=identity(request);service=reviews()
    batch=call(service.detail,bid,user,roles)
    if not any(i['id']==iid for i in batch['items']):raise HTTPException(404,'评测项不存在')
    with service.db.reading() as c:row=c.execute('SELECT path,sha256,name FROM review_context WHERE id=? AND batch=? AND item=?',(cid,bid,iid)).fetchone()
    if not row:raise HTTPException(404,'上下文不存在')
    path=Path(row[0])
    if not path.is_file() or _hash(path.read_bytes())!=row[1]:raise HTTPException(409,'固定来源文件已缺失或变化')
    # Text/JSON are rendered as plain text; HTML/SVG and active formats are attachments.
    mime='application/pdf' if path.suffix.lower()=='.pdf' else 'text/plain; charset=utf-8'
    return FileResponse(path,filename=row[2],media_type=mime,content_disposition_type='inline',headers={'Content-Security-Policy':'sandbox','X-Content-Type-Options':'nosniff'})


@router.get('/drafts/{draft_id}/review-status')
def current_review_status(draft_id:str,request:Request):
    user,roles=identity(request)
    return call(reviews().current_status,draft_id,user,roles)


@router.post('/exports/{eid}/expire')
def expire_export(eid:str,request:Request):
    user,roles=identity(request)
    return call(exports().expire,eid,user,roles)
