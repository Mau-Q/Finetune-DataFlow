import asyncio
import copy
import io
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
import pytest
from pypdf import PdfWriter
from app.core.container import container
from app.core.config import settings
from app.services.data_library import DataLibrary, LibraryError, _hash
from app.services.task_registry import TaskRegistry
from app.services.task_store import patch_task
from app.services.task_artifacts import finalize_artifacts, capture_responses
from app.services.text_generation import TextGeneration, template
from app.services.training_lifecycle import TrainingLifecycle
from app.schemas.data_library import DraftCreate


@pytest.fixture
def platform(tmp_path, monkeypatch):
    library=DataLibrary(tmp_path/'library')
    tasks=TaskRegistry(str(tmp_path/'tasks.json'))
    source=tmp_path/'paper.pdf'
    writer=PdfWriter();writer.add_blank_page(width=100,height=100)
    with source.open('wb') as handle:writer.write(handle)
    manifest=tmp_path/'source.jsonl';manifest.write_text(json.dumps({'source':str(source)})+'\n')
    config=template()['config'];config['input_dataset']={'id':'input','location':[0,0]}
    for op in config['operators']:
        for param in op['params']['init']:
            if param['name']=='llm_serving':param['value']='service'
            if param['name'] in {'mineru_script','tokenizer_path'}:param['value']=str(tmp_path)
    config['execution_options']={'additional_retries':0}
    info={'id':'service','cls_name':'APILLMServing_request','params':[{'name':k,'value':v} for k,v in {'api_url':'https://offline.invalid/v1/chat/completions','api_key':'TEST_ONLY','model_name':'offline-fixture','max_retries':9}.items()]}
    monkeypatch.setattr(settings,'CACHE_DIR',str(tmp_path/'cache'))
    monkeypatch.setattr(container,'dataset_registry',SimpleNamespace(get=lambda _: {'root':str(manifest)}))
    monkeypatch.setattr(container,'data_library',library)
    monkeypatch.setattr(container,'task_registry',tasks)
    monkeypatch.setattr(container,'serving_registry',SimpleNamespace(_get=lambda sid:copy.deepcopy(info) if sid=='service' else None))
    monkeypatch.setattr(container,'pipeline_registry',SimpleNamespace(path=str(tmp_path/'pipelines.json'),get_pipeline=lambda _: {'id':'pipeline','config':copy.deepcopy(config),'tags':['platform-text']}))
    return TextGeneration(),config,tasks,library,source,info


def submitter(monkeypatch):
    from app.services.dataflow_engine import DataFlowEngine
    from app.services.ray_pipeline_executor import ray_executor
    seen=[]
    monkeypatch.setattr(DataFlowEngine,'decode_hashed_arguments',lambda config,tid: {'fixture':True})
    async def submit(config,runtime,tid,*args):
        seen.append((copy.deepcopy(config),tid))
    monkeypatch.setattr(ray_executor,'submit_execution',submit)
    return seen


def test_preflight_missing_service_does_not_queue(platform,monkeypatch):
    service,config,tasks,*_=platform
    seen=submitter(monkeypatch)
    for op in config['operators']:
        for p in op['params']['init']:
            if p['name']=='llm_serving':p['value']=''
    with pytest.raises(LibraryError,match='未配置文本服务'):
        asyncio.run(service.submit(pipeline_id='pipeline'))
    assert not tasks.list_executions() and not seen


def test_snapshot_submission_retry_and_nonsecret_config(platform,monkeypatch):
    service,config,tasks,lib,source,info=platform
    seen=submitter(monkeypatch)
    r=asyncio.run(service.submit(pipeline_id='pipeline'))
    task=tasks.get(r['task_id']);frozen=task['pipeline_config']
    options=frozen['execution_options']
    assert options['max_attempts']==1
    assert 'TEST_ONLY' not in json.dumps(task)
    assert frozen['operators']==seen[0][0]['operators']
    input_path=Path(options['input_snapshot']['path'])
    source.write_text('changed original')
    config['operators'][0]['params']['init'][2]['value']='premium'
    patch_task(tasks.path,r['task_id'],{'status':'failed'})
    retry=asyncio.run(service.submit(previous_id=r['task_id']))
    assert retry['task_id']!=r['task_id']
    retried=tasks.get(retry['task_id'])
    assert retried['retry_of']==r['task_id']
    assert retried['pipeline_config']['operators'][0]['params']['init'][2]['value']=='standard'
    assert retried['pipeline_config']['execution_options']['input_snapshot']==options['input_snapshot']
    assert tasks.get(r['task_id'])['status']=='failed'
    assert input_path.is_file()


def test_retry_rejects_missing_snapshot_or_changed_service(platform,monkeypatch):
    service,_,tasks,_,_,info=platform;submitter(monkeypatch)
    tid=asyncio.run(service.submit(pipeline_id='pipeline'))['task_id']
    patch_task(tasks.path,tid,{'status':'failed'})
    info['params'][2]['value']='changed-model'
    with pytest.raises(LibraryError,match='服务配置已变化'):
        asyncio.run(service.submit(previous_id=tid))
    info['params'][2]['value']='offline-fixture'
    Path(tasks.get(tid)['pipeline_config']['execution_options']['input_snapshot']['path']).unlink()
    with pytest.raises(LibraryError,match='固定的输入文件'):
        asyncio.run(service.submit(previous_id=tid))
    assert len(tasks.list_executions())==1


def test_submit_failure_is_persisted(platform,monkeypatch):
    service,_,tasks,*_=platform
    submitter(monkeypatch)
    from app.services.ray_pipeline_executor import ray_executor
    async def fail(*args):raise RuntimeError('fixture')
    monkeypatch.setattr(ray_executor,'submit_execution',fail)
    with pytest.raises(LibraryError,match='提交失败'):
        asyncio.run(service.submit(pipeline_id='pipeline'))
    task=tasks.list_executions()[0]
    assert task['status']=='failed' and task['output']['error']


@pytest.mark.parametrize('retries',[-1,6,'0',False])
def test_invalid_retries_preflight(platform,retries):
    service,config,*_=platform;config['execution_options']['additional_retries']=retries
    assert not service.preflight(config)['ready']


def test_order_boundary_preflight(platform):
    service,config,*_=platform;config['operators'].reverse()
    assert not service.preflight(config)['ready']


def test_atomic_task_merges_keep_other_tasks_and_cancelled(tmp_path):
    path=str(tmp_path/'tasks.json')
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i:patch_task(path,str(i),{'task_id':str(i),'status':'queued'},create=True),range(30)))
    tasks=TaskRegistry(path)
    assert len(tasks.list_executions())==30
    patch_task(path,'1',{'status':'cancelled'})
    patch_task(path,'1',{'status':'completed','output':{'unexpected':True}})
    assert tasks.get('1')['status']=='cancelled' and 'output' not in tasks.get('1')


@pytest.mark.parametrize('executor',['sync','ray'])
@pytest.mark.parametrize('outcome',['success','zero','failure'])
def test_both_production_loops_artifacts_capture_and_drafts(platform,monkeypatch,tmp_path,executor,outcome):
    service,_,tasks,lib,*_=platform
    from app.services import dataflow_engine,ray_pipeline_executor
    from app.services.serving_registry import SERVING_CLS_REGISTRY
    from dataflow.utils.registry import OPERATOR_REGISTRY
    calls=[]
    class FixtureServing:
        def __init__(self,**kwargs):
            calls.append(kwargs['max_retries'])
        def generate_from_input(self,*args,**kwargs):return ['exact model text']
    class FixtureOperator:
        def __init__(self,llm_serving):self.llm_serving=llm_serving
        def run(self,storage,input_key='source',output_key='output'):
            df=storage.read('dataframe')
            responses=self.llm_serving.generate_from_input(user_inputs=['test'])
            if outcome=='zero':df=df.iloc[0:0]
            df=df.assign(instruction='question',input='',output=responses[0])
            storage.write(df)
            return ['instruction','input','output']
    class FailingOperator:
        def run(self,storage):raise RuntimeError('intentional fixture failure')
    monkeypatch.setattr(OPERATOR_REGISTRY,'_get_all',lambda:None)
    monkeypatch.setattr(OPERATOR_REGISTRY,'get',lambda name:FixtureOperator if name=='FixtureOperator' else FailingOperator)
    monkeypatch.setitem(SERVING_CLS_REGISTRY,'APILLMServing_request',FixtureServing)
    monkeypatch.setattr(ray_pipeline_executor,'APILLMServing_request',FixtureServing)
    config={'input_dataset':'input','operators':[{'name':'FixtureOperator','params':{'init':[{'name':'llm_serving','value':'service'}],'run':[]}}],
            'execution_options':{'capture_responses':True,'training_output':True,'max_attempts':1}}
    if outcome=='failure':config['operators'].append({'name':'FailingOperator','params':{'init':[],'run':[]}})
    tid,frozen,_=tasks.start_execution(config=config)
    if executor=='sync':
        result=dataflow_engine.DataFlowEngine().run(frozen,tid,execution_path=tasks.path)
    else:
        runtime={'storage':{'first_entry_file_name':container.dataset_registry.get('input')['root'],'cache_path':str(Path(settings.CACHE_DIR)/f'{tid}_output'),'file_name_prefix':'dataflow_cache_step','cache_type':'jsonl'},
                 'serving_map':{'service':container.serving_registry._get('service')},'embedding_serving_map':{},'db_manager_map':{}}
        result=ray_pipeline_executor.dataflow_pipeline_execute(frozen,runtime,tid,tasks.path)
    assert result['status']==('failed' if outcome=='failure' else 'completed'), result
    assert calls==[1]
    artifacts=result['output']['artifacts']
    assert {'raw_response','candidate'} <= {a['kind'] for a in artifacts}
    raw=next(a for a in artifacts if a['kind']=='raw_response')
    assert json.loads(Path(raw['path']).read_text())['responses']==['exact model text']
    training=[a for a in artifacts if a['kind']=='training']
    if outcome=='failure':
        assert not training and result['output']['error']
        assert result['output']['execution_results'][0]['file_path']
    else:
        assert training[0]['row_count']==(0 if outcome=='zero' else 1)
        patch_task(tasks.path,tid,result)
        reused=asyncio.run(service.submit(previous_id=tid))
        assert reused['task_id']==tid and reused['reused']
        did=lib.create_draft(DraftCreate(name='From actual loop'))['id']
        life=TrainingLifecycle(lib)
        assert life.collect(did,result,training[0])['added']==(0 if outcome=='zero' else 1)
        if outcome=='success':
            rid=life.publish(did)['id']
            assert json.loads(life.download(rid,'jsonl').read_text())['output']=='exact model text'
        # Native cache mutation does not affect the owned task artifact.
        Path(result['output']['execution_results'][0]['file_path']).write_text('changed')
        assert Path(training[0]['path']).read_bytes()==(b'' if outcome=='zero' else Path(training[0]['path']).read_bytes())


def test_preview_uses_exact_task_step_not_global_cache(platform):
    _,_,tasks,*_=platform
    cache=Path(settings.CACHE_DIR);cache.mkdir()
    (cache/'dataflow_cache_step_step1.jsonl').write_text('{"wrong":true}\n')
    patch_task(tasks.path,'history',{'task_id':'history','output':{'execution_results':[{'index':0}]},'status':'completed'},create=True)
    assert tasks.get_execution_result('history')['sample_data']==[]


def test_save_normalizes_unassigned_service_and_preserves_canvas_options(platform,monkeypatch):
    service,config,*_=platform
    captured=[]
    monkeypatch.setattr(container.pipeline_registry,'create_pipeline',lambda body:captured.append(body) or {'id':'new',**body},raising=False)
    for op in config['operators']:
        for p in op['params']['init']:
            if p['name']=='llm_serving':p['value']=''
    result=service.save('Wizard',config)
    assert result['config']['execution_options']['max_attempts']==1
    assert all(p['value'] is None for op in result['config']['operators'] for p in op['params']['init'] if p['name']=='llm_serving')
    from app.schemas.pipelines import PipelineConfig
    assert PipelineConfig.model_validate(result['config']).model_dump()['execution_options']==result['config']['execution_options']


def test_complete_reuse_rejects_modified_artifact(platform,tmp_path):
    service,_,tasks,*_=platform
    path=tmp_path/'bad.jsonl';path.write_text('changed')
    patch_task(tasks.path,'done',{'task_id':'done','status':'completed','output':{'artifacts':[{'kind':'training','path':str(path),'sha256':'old'}]}},create=True)
    with pytest.raises(LibraryError,match='不能复用'):
        asyncio.run(service.submit(previous_id='done'))


def test_synchronous_serving_uses_fixed_parameters_and_effective_attempts(platform,monkeypatch):
    _,_,_,_,_,info=platform
    from app.services.dataflow_engine import DataFlowEngine
    from app.services.serving_registry import SERVING_CLS_REGISTRY
    captured=[]
    monkeypatch.setitem(SERVING_CLS_REGISTRY,'APILLMServing_request',lambda **kwargs:captured.append(kwargs) or object())
    DataFlowEngine().init_serving_instance('service',max_retries=1,snapshot={'parameters':{'api_url':'https://frozen.invalid','model_name':'frozen','max_retries':9}})
    assert captured[0]['model_name']=='frozen' and captured[0]['api_url']=='https://frozen.invalid' and captured[0]['max_retries']==1


def test_modified_input_is_rejected_before_execution(platform,monkeypatch,tmp_path):
    service,config,*_=platform
    from app.services.task_artifacts import with_task_artifacts
    snapshot=service._freeze_input(config)
    Path(snapshot['materials'][0]['path']).write_text('corrupt')
    called=[]
    @with_task_artifacts
    def run(pipeline_config,task_id):
        called.append(task_id)
    result=run({'execution_options':{'input_snapshot':snapshot}},'guarded')
    assert result['status']=='failed' and not called


@pytest.mark.parametrize('content',['broken','{"tasks":[]}'])
def test_corrupt_task_history_preserved(tmp_path,content):
    path=tmp_path/'tasks.json';path.write_text(content)
    with pytest.raises(ValueError):TaskRegistry(str(path))
    assert path.read_text()==content


def test_wizard_template_keeps_original_filter_and_dedup_semantics():
    config=template()['config']
    assert len(config['operators'])==13
    threshold=config['operators'][10]['params']['init'][0]['value']
    assert threshold.count('>= 4')==5
    assert config['operators'][11]['name']=='HashDeduplicateFilter'
    assert config['operators'][11]['params']['run'][0]['value']==['question','answer']


def test_synchronous_platform_endpoint_keeps_pipeline_identity_and_input_snapshot(platform,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.v1.endpoints import tasks as endpoints
    service,config,tasks,*_=platform
    config['execution_options']['capture_responses']=True
    observed=[]
    def execute(config,tid,execution_path):
        observed.append(config)
        return {'task_id':tid,'status':'completed','output':{},'logs':['offline endpoint fixture']}
    monkeypatch.setattr(endpoints.dataflow_engine,'run',execute)
    app=FastAPI();app.include_router(endpoints.router)
    with TestClient(app) as client:
        r=client.post('/execute?pipeline_id=pipeline').json()['data']
    saved=tasks.get(r['task_id'])
    assert r['pipeline_id']==saved['pipeline_id']=='pipeline'
    assert saved['pipeline_config']['execution_options']['input_snapshot']['sha256']
    output=next(p['value'] for p in observed[0]['operators'][0]['params']['init'] if p['name']=='output_dir')
    assert r['task_id']+'_output' in output


@pytest.mark.parametrize('route',['/execute','/execute-async'])
def test_canvas_platform_submission_rejects_missing_service_before_queued(platform,route):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.v1.endpoints import tasks as endpoints
    _,config,tasks,*_=platform
    config['execution_options']['capture_responses']=True
    for op in config['operators']:
        for p in op['params']['init']:
            if p['name']=='llm_serving':p['value']=None
    app=FastAPI();app.include_router(endpoints.router)
    with TestClient(app) as client:
        response=client.post(route+'?pipeline_id=pipeline')
    assert response.status_code==422
    assert not tasks.list_executions()
