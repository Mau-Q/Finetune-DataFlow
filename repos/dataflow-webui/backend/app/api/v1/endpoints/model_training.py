from fastapi import APIRouter, HTTPException, UploadFile, File
from app.api.v1.resp import ok
from app.core.container import container
from app.schemas.model_training import PlanSave, ExperimentGroup
from app.services.model_training import TrainingError
router=APIRouter(tags=['model_training'])

def service():
    if container.model_training is None:
        raise HTTPException(503, getattr(container,'model_training_error','训练存储未就绪'))
    return container.model_training

def call(fn,*args,**kwargs):
    try: return fn(*args,**kwargs)
    except TrainingError as e: raise HTTPException(e.status,str(e)) from e

@router.get('/plans')
def plans(): return ok(call(service().list,'plans'))
@router.post('/plans')
def create(body:PlanSave): return ok(call(service().save_plan,body.plan.model_dump()))
@router.get('/plans/{key}')
def get(key:str): return ok(call(service().get,'plans',key))
@router.put('/plans/{key}')
def save(key:str,body:PlanSave): return ok(call(service().save_plan,body.plan.model_dump(),key,body.expected_version))
@router.post('/plans/{key}/copy')
def copy(key:str):
    plan=call(service().get,'plans',key)['plan'];plan['name']+=' · 副本'
    return ok(call(service().save_plan,plan))
@router.post('/plans/{key}/check')
def check(key:str): return ok(call(service().check,call(service().get,'plans',key)['plan']))
@router.get('/releases')
def releases(): return ok(call(service().releases))
@router.get('/groups')
def groups(): return ok(call(service().list,'groups'))
@router.post('/groups')
def group(body:ExperimentGroup): return ok(call(service().put,'groups',body.model_dump()))

@router.get('/catalog')
def components():
    from app.services.training_compiler import catalog
    return ok(call(catalog,service()))
@router.post('/components')
def component(body:dict):
    from app.services.training_compiler import save_descriptor
    return ok(call(save_descriptor,service(),body))
@router.post('/plans/{key}/compile')
def compile(key:str):
    from app.services.training_compiler import compile_plan
    return ok(call(compile_plan,service(),call(service().get,'plans',key)['plan']))

@router.post('/plans/{key}/bundles')
def bundle(key:str):
    from app.services.training_bundles import export_bundle
    return ok(call(export_bundle,service(),key))
@router.get('/bundles')
def bundles(): return ok(call(service().list,'bundles'))
@router.get('/bundles/{key}/download')
def bundle_download(key:str):
    from pathlib import Path
    from fastapi.responses import FileResponse
    from app.services.model_training import digest
    r=call(service().get,'bundles',key);p=Path(r['path'])
    if not p.is_file() or digest(p.read_bytes())!=r['archive_sha256']:raise HTTPException(409,'运行包缺失或已改动')
    return FileResponse(p,filename='dataflex-'+key+'.zip',media_type='application/zip')

@router.get('/runs')
def runs(): return ok(call(service().list,'runs'))
@router.get('/runs/{attempt}')
def run_detail(attempt:str):
    from app.services.training_results import run_detail
    return ok(call(run_detail,service(),attempt))
@router.post('/results/import')
def import_result(body:dict):
    from app.services.training_results import import_result
    return ok(call(import_result,service(),body))
@router.post('/evaluations')
def evaluation(body:dict):
    from app.services.training_results import add_evaluation
    return ok(call(add_evaluation,service(),body))
@router.post('/compare')
def comparison(body:dict):
    from app.services.training_results import compare
    return ok(call(compare,service(),body.get('attempts',[]),body.get('include_synthetic',False)))

@router.get('/host')
def host():
    from app.services.training_ssh import host_config
    return ok(call(host_config,service()))
@router.put('/host')
def host_save(body:dict):
    from app.services.training_ssh import save_host
    return ok(call(save_host,service(),body))
@router.post('/host/probe')
def probe_host():
    from app.services.training_ssh import probe
    return ok(call(probe,service()))
@router.get('/controls')
def controls():return ok(call(service().list,'controls'))
@router.post('/start')
def start(body:dict):
    from app.services.training_ssh import start
    return ok(call(start,service(),body.get('bundle_id'),body.get('idempotency_key')))
@router.post('/controls/{attempt}/sync')
def sync(attempt:str):
    from app.services.training_ssh import sync
    return ok(call(sync,service(),attempt))
@router.post('/controls/{attempt}/stop')
def stop(attempt:str):
    from app.services.training_ssh import sync
    return ok(call(sync,service(),attempt,True))

@router.post('/backups')
def backup():
    from app.services.training_backups import backup
    path=call(backup,service())
    return ok({'id':path.stem,'filename':path.name})
@router.get('/backups/{key}/download')
def download_backup(key:str):
    import re
    from fastapi.responses import FileResponse
    from app.services.training_backups import verify
    if not re.fullmatch('[0-9a-f]{32}',key):raise HTTPException(404,'备份不存在')
    path=service().root/'backups'/(key+'.zip')
    if not path.is_file():raise HTTPException(404,'备份不存在')
    call(verify,path)
    return FileResponse(path,filename='dataflex-backup-'+key+'.zip',media_type='application/zip')


@router.post('/bundles/import')
def upload_bundle(file: UploadFile = File(...)):
    from app.services.training_bundles import import_bundle, MAX_BUNDLE
    blob=file.file.read(MAX_BUNDLE+1)
    if len(blob)>MAX_BUNDLE:raise HTTPException(400,'包超过 512 MiB')
    return ok(call(import_bundle,service(),blob))
