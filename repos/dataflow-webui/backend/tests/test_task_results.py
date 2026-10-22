"""Isolated final-result acceptance: no production DB, cache, serving or model calls."""
import io
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import pytest
from PIL import Image
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.v1.endpoints import tasks, data_library
from app.api.v1.handlers import install_exception_handlers
from app.core.container import container
from app.schemas.data_library import DraftCreate
from app.services.data_library import DataLibrary, LibraryError, _hash, _json_bytes
from app.services.task_results import TaskResults


def row(output='answer'):
    return {'instruction': 'question', 'input': '', 'output': output}


@pytest.fixture
def setup(tmp_path):
    lib = DataLibrary(tmp_path/'data'/'library')
    records = {}
    c = SimpleNamespace(data_library=lib, task_registry=SimpleNamespace(get=records.get))
    return TaskResults(c), records, tmp_path


def task(setup, rows=None, task_id='isolated-task', artifact=False, status='completed'):
    service, records, root = setup
    path = root/(task_id+'.jsonl')
    path.write_bytes(b''.join(_json_bytes(r)+b'\n' for r in (rows if rows is not None else [row()])))
    rec = dict(task_id=task_id, pipeline_id='isolated-pipeline', name='隔离验收 Pipeline', status=status,
               pipeline_config={'operators': [{'name': 'Test'}]}, output={'execution_results': [{'index': 0, 'file_path': str(path), 'status': 'completed'}]})
    if artifact:
        rec['output']['artifacts'] = [dict(id='training_'+task_id, kind='training', path=str(path), step=0, sha256=_hash(path.read_bytes()))]
    records[task_id] = rec
    return rec, path


def collect(service, tid='isolated-task', **kwargs):
    digest = service.detail(tid)['artifact']['sha256']
    return service.collect(tid, digest, **kwargs)


def test_preview_does_not_collect_and_new_is_persistent(setup):
    service, records, root = setup
    task(setup, artifact=True)
    detail = service.detail('isolated-task')
    assert detail['collectable'] and detail['sample_data']==[row()]
    assert not service.lib.list_drafts()
    result = collect(service, name='隔离 · 新建 SFT')
    assert result['added']==1 and result['duplicates_skipped']==0
    sources = result['sample_sources'][result['sample_ids'][0]]
    assert sources[0]['task_id']=='isolated-task' and sources[0]['pipeline_id']=='isolated-pipeline'
    assert service.detail('isolated-task')['collections'][0]['id']==result['id']
    reloaded = DataLibrary(service.lib.root).get_draft(result['id'])
    assert reloaded['rows']==[row()]
    assert records['isolated-task']['output']['artifacts'][0]['kind']=='training'


def test_new_and_append_replay_concurrently_without_duplicates(setup):
    service, _, _ = setup
    task(setup, [row(), row()])
    digest = service.detail('isolated-task')['artifact']['sha256']
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: service.collect('isolated-task', digest, name='隔离 · 并发新建'), range(4)))
    assert len({r['id'] for r in results})==1
    assert sum(r['added'] for r in results)==1
    assert len(service.lib.list_drafts())==1
    assert results[0]['row_count']==1
    assert len(results[0]['sample_sources'][results[0]['sample_ids'][0]])==2
    did = results[0]['id']
    task(setup, [row(), row('new')], task_id='second-task')
    second = collect(service, tid='second-task', draft_id=did)
    assert second['added']==1 and second['duplicates_skipped']==1
    sid=second['sample_ids'][0]
    assert {s['task_id'] for s in second['sample_sources'][sid]}=={'isolated-task','second-task'}
    replay=collect(service, tid='second-task', draft_id=did)
    assert replay['reused'] and replay['added']==0 and replay['row_count']==2
    assert service.detail('second-task')['collections'][0]['id']==did


@pytest.mark.parametrize('status', ['running', 'queued', 'failed', 'cancelled'])
def test_incomplete_cannot_collect(setup, status):
    service, _, _ = setup
    task(setup, status=status)
    assert not service.detail('isolated-task')['available']
    with pytest.raises(LibraryError):
        service.collect('isolated-task', 'a'*64, name='不得创建')
    assert not service.lib.list_drafts()


@pytest.mark.parametrize('rows', [[], [{'text':'plain text'}], [row(), {'instruction':'broken'}], [None]])
def test_invalid_contract_or_empty_cannot_create(setup, rows):
    service, _, _ = setup
    task(setup, rows)
    detail=service.detail('isolated-task')
    assert detail['available'] and not detail['collectable']
    with pytest.raises(LibraryError):
        collect(service, name='不得创建')
    assert not service.lib.list_drafts()


def test_changed_hash_and_missing_file_rejected(setup):
    service, _, _ = setup
    _, path = task(setup)
    digest=service.detail('isolated-task')['artifact']['sha256']
    path.write_bytes(_json_bytes(row('changed'))+b'\n')
    with pytest.raises(LibraryError, match='已变化'):
        service.collect('isolated-task', digest, name='不得创建')
    path.unlink()
    assert not service.detail('isolated-task')['available']
    assert not service.lib.list_drafts()


def test_fixed_training_tamper_rejected(setup):
    service, _, _ = setup
    _, path=task(setup, artifact=True)
    path.write_bytes(_json_bytes(row('changed')))
    assert not service.detail('isolated-task')['available']


def test_legacy_snapshot_survives_cache_removal_and_dataset_edits(setup):
    service, _, _ = setup
    _, path=task(setup)
    result=collect(service, name='隔离 · 固定结果')
    path.unlink()
    from app.services.training_lifecycle import TrainingLifecycle
    TrainingLifecycle(service.lib).edit(result['id'], result['sample_ids'][0], row('edited'))
    assert service.detail('isolated-task')['sample_data']==[row()]
    assert service.download('isolated-task').is_file()
    assert collect(service, name='重试')['reused']
    assert service.lib.get_draft(result['id'])['rows']==[row('edited')]


def test_type_mismatch_rolls_back_append(setup):
    service, _, _ = setup
    task(setup)
    did=service.lib.create_draft(DraftCreate(name='隔离 DPO', training_type='dpo'))['id']
    with pytest.raises(LibraryError, match='类型或模态'):
        collect(service, draft_id=did)
    assert service.lib.get_draft(did)['row_count']==0


def test_image_binding_failure_rolls_back_new_then_binding_works(setup):
    service, _, _ = setup
    sample=dict(row(), images=['images/test.png'])
    task(setup, [sample])
    assert service.detail('isolated-task')['media_refs']==['images/test.png']
    with pytest.raises(LibraryError, match='媒体缺失'):
        collect(service, name='隔离图文')
    assert not service.lib.list_drafts()
    buffer=io.BytesIO();Image.new('RGB',(4,4),'red').save(buffer,format='PNG')
    image=service.lib.add_material('test.png',buffer.getvalue(),{'name':'隔离红色图片'})
    result=collect(service, name='隔离图文', media_bindings={'images/test.png':image['id']})
    assert result['modality']=='image_text' and result['row_count']==1
    task(setup, [dict(sample, output='other')], task_id='second-task')
    appended=collect(service, tid='second-task', draft_id=result['id'])
    assert appended['added']==1


def test_dpo_can_be_collected(setup):
    service, _, _ = setup
    task(setup,[{'prompt':'Q','chosen':'good','rejected':'bad'}])
    result=collect(service,name='隔离 DPO')
    assert result['training_type']=='dpo'


def test_real_endpoints_use_only_isolated_library(setup, monkeypatch):
    service, records, _ = setup
    task(setup, artifact=True)
    monkeypatch.setattr(container,'data_library',service.lib)
    monkeypatch.setattr(container,'task_registry',SimpleNamespace(get=records.get))
    app=FastAPI();app.include_router(tasks.router,prefix='/api/v1/tasks');app.include_router(data_library.router,prefix='/api/v1/library')
    install_exception_handlers(app)
    with TestClient(app) as client:
        base='/api/v1/tasks/execution/isolated-task/final-result'
        detail=client.get(base).json()['data']
        response=client.post(base+'/collect',json={'expected_sha256':detail['artifact']['sha256'],'name':'隔离 API'})
        result=response.json()['data'];assert result['added']==1
        assert client.post(base+'/collect',json={'expected_sha256':detail['artifact']['sha256'],'name':'隔离 API'}).json()['data']['reused']
        assert client.get(base+'/download').content==_json_bytes(row())+b'\n'
        did=result['id']
        assert client.get('/api/v1/library/drafts/'+did).json()['data']['rows']==[row()]
        invalid=client.post(base+'/collect',json={'expected_sha256':detail['artifact']['sha256'],'name':'new','draft_id':did}).json()
        assert not invalid['success'] and invalid['meta']['http_status']==422


def auto_result(setup, rows=None, status='completed', task_id='auto-task'):
    from app.services.auto_collection import collect_completed_result
    service, records, root = setup
    rec, path = task(setup, rows, task_id=task_id, status=status)
    rec['pipeline_config']['execution_options']={'collection_library_root':str(service.lib.root)}
    registry=root/'auto-tasks.json'
    registry.write_bytes(_json_bytes({'tasks':records}))
    result=collect_completed_result(rec['pipeline_config'],rec,registry)
    records[task_id]=result
    return result,registry


@pytest.mark.parametrize('sample', [row(), {'prompt':'Q','chosen':'right','rejected':'wrong'}])
def test_any_completed_training_pipeline_auto_collects_without_ui_and_replays_once(setup,sample):
    from app.services.auto_collection import collect_completed_result
    service,records,_=setup
    result,registry=auto_result(setup,[sample])
    assert result['output']['auto_collection']['status']=='collected'
    did=result['output']['auto_collection']['dataset_id']
    assert service.detail('auto-task')['collections'][0]['id']==did
    repeated=collect_completed_result(result['pipeline_config'],result,registry)
    assert repeated['output']['auto_collection']['reused']
    assert len(service.lib.list_drafts())==1
    assert service.lib._get('drafts',did)['rows']==[sample]


@pytest.mark.parametrize('status',['running','queued','failed','cancelled'])
def test_auto_collection_never_imports_unfinished_outputs(setup,status):
    result,_=auto_result(setup,status=status)
    assert 'auto_collection' not in result['output']
    assert not setup[0].lib.list_drafts()


@pytest.mark.parametrize('rows',[[],[{'text':'not a training sample'}]])
def test_empty_and_nontraining_outputs_are_skipped_with_reason(setup,rows):
    result,_=auto_result(setup,rows)
    assert result['status']=='completed'
    assert result['output']['auto_collection']['status']=='skipped'
    assert result['output']['auto_collection']['reason']
    assert not setup[0].lib.list_drafts()


def test_auto_collection_failure_preserves_generated_file_and_is_visible(setup,monkeypatch):
    monkeypatch.setattr(TaskResults,'collect',lambda *args,**kwargs: (_ for _ in ()).throw(OSError('fixture database unavailable')))
    result,_=auto_result(setup)
    assert result['status']=='completed'
    assert result['output']['auto_collection']['status']=='failed'
    assert 'fixture database unavailable' in result['output']['auto_collection']['reason']
    assert setup[0].detail('auto-task')['available']
    assert not setup[0].lib.list_drafts()


def test_concurrent_completion_callbacks_auto_collect_only_once(setup):
    import copy
    from app.services.auto_collection import collect_completed_result
    result,registry=auto_result(setup)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda _:collect_completed_result(result['pipeline_config'],copy.deepcopy(result),registry),range(8)))
    assert all(r['output']['auto_collection']['status']=='collected' for r in results)
    assert len(setup[0].lib.list_drafts())==1
    assert setup[0].lib.list_drafts()[0]['row_count']==1


def test_polling_status_exposes_auto_collection_without_full_output(setup):
    from app.services.task_registry import TaskRegistry
    from app.services.task_store import patch_task
    result,_=auto_result(setup)
    registry=TaskRegistry(str(setup[2]/'polling-tasks.json'))
    patch_task(registry.path,result['task_id'],result,create=True)
    status=registry.get_execution_status(result['task_id'])
    assert status['auto_collection']['status']=='collected'
    assert 'output' not in status


@pytest.mark.parametrize('mode',['new','append'])
def test_selected_target_is_frozen_remembered_and_used_without_ui(setup,mode):
    from app.services.auto_collection import freeze_collection_target, collect_completed_result, target_preferences
    service,records,root=setup
    existing=service.lib.create_draft(DraftCreate(name='existing',modality='text',training_type='sft'))
    rec,_=task(setup,task_id='selected-target')
    target=dict(mode=mode,name='  user selected  ' if mode=='new' else '',draft_id=existing['id'] if mode=='append' else None)
    config=rec['pipeline_config']
    config['execution_options']=dict(simple_training=dict(modality='text',training_type='sft'),collection_target=target)
    freeze_collection_target(config,service.lib)
    remembered=target_preferences(DataLibrary(service.lib.root))['text:sft']
    assert remembered['mode']==mode
    assert remembered['name']==('user selected' if mode=='new' else '')
    # Later preferences do not redirect an already submitted task.
    other={'execution_options':{'collection_target':dict(mode='new',name='later')}}
    freeze_collection_target(other,service.lib)
    registry=root/'selected-tasks.json';registry.write_bytes(_json_bytes({'tasks':records}))
    result=collect_completed_result(config,rec,registry)
    target_id=result['output']['auto_collection']['dataset_id']
    assert service.lib._get('drafts',target_id)['name']==('user selected' if mode=='new' else 'existing')
    replay=collect_completed_result(config,result,registry)
    assert replay['output']['auto_collection']['reused']
    assert service.lib._get('drafts',target_id)['rows']==[row()]


@pytest.mark.parametrize('target', [dict(mode='new',name='  '),dict(mode='append'),dict(mode='append',draft_id='ds_'+'f'*32)])
def test_invalid_target_is_rejected_before_worker_dispatch(setup,target):
    from app.services.auto_collection import freeze_collection_target
    config={'execution_options':{'collection_target':target}}
    with pytest.raises(LibraryError):freeze_collection_target(config,setup[0].lib)
    assert not setup[0].lib.list_drafts()


def test_incompatible_target_rejected_before_run_and_preferences_kept(setup):
    from app.services.auto_collection import freeze_collection_target,target_preferences
    lib=setup[0].lib
    draft=lib.create_draft(DraftCreate(name='DPO',modality='text',training_type='dpo'))
    with pytest.raises(LibraryError,match='不一致'):
        freeze_collection_target({'execution_options':{'simple_training':dict(modality='text',training_type='sft'),
            'collection_target':dict(mode='append',draft_id=draft['id'])}},lib)
    assert target_preferences(lib)=={}


@pytest.mark.parametrize('route',['/execute','/execute-async'])
def test_invalid_collection_target_api_rejects_before_queuing(setup,monkeypatch,route):
    from app.services.task_registry import TaskRegistry
    lib=setup[0].lib
    registry=TaskRegistry(str(setup[2]/'api-tasks.json'))
    monkeypatch.setattr(container,'data_library',lib)
    monkeypatch.setattr(container,'task_registry',registry)
    monkeypatch.setattr(container,'pipeline_registry',SimpleNamespace(get_pipeline=lambda _:dict(name='test',config={'operators':[]})))
    app=FastAPI();app.include_router(tasks.router,prefix='/tasks')
    with TestClient(app) as client:
        response=client.post('/tasks'+route+'?pipeline_id=test',json={'collection_target':{'mode':'new','name':' '}})
    assert response.status_code==422
    assert not registry.list_executions()
    assert not lib.list_drafts()
