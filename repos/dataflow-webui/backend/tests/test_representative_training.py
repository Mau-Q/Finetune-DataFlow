import asyncio
import copy
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from PIL import Image
from app.core.container import container
from app.core.config import settings
from app.services.data_library import DataLibrary, LibraryError
from app.services.json_schema_manager import JsonSchemaManager
from app.services.user_prompt_registry import UserPromptRegistry
from app.services.operator_registry import OperatorRegistry
from app.services.pipeline_registry import PipelineRegistry
from app.services.task_registry import TaskRegistry
from app.services.task_store import patch_task
from app.services.task_results import TaskResults
from app.services.text_generation import TextGeneration
from app.services.representative_training import definitions, resources, install_templates, LEGACY_IDS, remove_scoring
from app.services.representative_training_operators import TrainingReviewParser, TrainingPreferenceBuilder, TrainingQAExpander

SOURCE = ('某实验室的数据采集器每隔两秒记录一次温度，记录频率在本次实验期间保持不变。'
          '实验连续采集五分钟，按每分钟六十秒计算，不额外增加端点记录。'
          '每条记录占用八个字节，其中已经包含温度值和时间信息。'
          '存储量只统计记录本身，不计算文件头、索引和文件系统开销。'
          '所有记录都成功写入，期间没有丢包、重复记录或压缩。')
ORIGINAL = '\n  '+SOURCE.replace('。','。   \n')+'  \n'
QUESTION = '五分钟共采集多少条记录？'
ANSWER_A = '每两秒一条，五分钟为300秒，共采集150条记录。'
ANSWER_B = '共采集100条记录。'


@pytest.fixture
def platform(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings,'CACHE_DIR',str(tmp_path/'cache'))
    monkeypatch.setattr(settings,'BASE_DIR',str(tmp_path))
    monkeypatch.setattr(settings,'DATAFLOW_CORE_DIR',str(tmp_path/'core'))
    (tmp_path/'core'/'api_pipelines').mkdir(parents=True)
    library=DataLibrary(tmp_path/'library')
    monkeypatch.setattr(container,'data_library',library)
    monkeypatch.setattr(container,'operator_registry',OperatorRegistry())
    monkeypatch.setattr(container,'user_prompt_registry',UserPromptRegistry(tmp_path/'prompts.json'))
    monkeypatch.setattr(container,'json_schema_manager',JsonSchemaManager(tmp_path/'schemas.json'))
    pipelines=tmp_path/'pipelines.json'
    pipelines.write_text(json.dumps({'pipelines':{'keep':dict(id='keep',name='用户自己的流程',config={'file_path':'','input_dataset':'','operators':[]},
                                                            tags=[],created_at='',updated_at='',status='queued')}}))
    monkeypatch.setattr(container,'pipeline_registry',PipelineRegistry(str(pipelines)))
    monkeypatch.setattr(container,'task_registry',TaskRegistry(str(tmp_path/'tasks.json')))
    original=ORIGINAL
    manifest=tmp_path/'text.jsonl'
    text_rows=[dict(id='original',text=original),dict(id='duplicate',text=original),dict(id='short',text='太短。'),dict(id='blank',text='  ')]
    manifest.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in text_rows))
    buffer=io.BytesIO();Image.new('RGB',(32,32),'red').save(buffer,'PNG')
    material=library.add_material('test.png',buffer.getvalue(),{'name':'测试图片'})
    path,_=library.material_file(material['id'])
    images=tmp_path/'images.jsonl'
    # A repeated manifest record exercises source deduplication without importing
    # a second material or changing the actual production database.
    images.write_text((json.dumps(dict(source=str(path),material_id=material['id']))+'\n')*2)
    datasets={'text':dict(root=str(manifest)),'image_text':dict(root=str(images))}
    monkeypatch.setattr(container,'dataset_registry',SimpleNamespace(get=lambda key:datasets.get(key),
        get_columns=lambda key:['id','text'] if key=='text' else ['source','material_id']))
    service=dict(id='offline',cls_name='APILLMServing_request',params=[{'name':k,'value':v} for k,v in dict(
        api_url='https://offline.invalid/v1/chat/completions',model_name='fixture',api_key='TEST_ONLY',max_workers=1).items()])
    monkeypatch.setattr(container,'serving_registry',SimpleNamespace(_get=lambda key:copy.deepcopy(service) if key=='offline' else None))
    install_templates(container)
    return container,tmp_path,material


def ready_config(c, definition):
    config=copy.deepcopy(c.pipeline_registry.get_pipeline(definition['id'])['config'])
    config['input_dataset']['id']=config['execution_options']['simple_training']['modality']
    for op in config['operators']:
        for param in op['params']['init']:
            if param['name']=='llm_serving':param['value']='offline'
    return config


def serving_fixture(calls, reject=False, tie=False, malformed=False, failure=False):
    class Serving:
        def __init__(self,**kwargs):
            assert kwargs.get('key_name_of_api_key')
            assert os.environ.get(kwargs['key_name_of_api_key'])=='TEST_ONLY'
        def cleanup(self):pass
        def generate_from_input(self,user_inputs,system_prompt='',**kwargs):
            return [self.respond(prompt) for prompt in user_inputs]
        def generate_from_conversations(self,conversations):
            outputs=[]
            for conversation in conversations:
                blocks=conversation[0]['content']
                assert blocks[1]['image_url']['url'].startswith('data:image/png;base64,')
                outputs.append(self.respond(blocks[0]['text']))
            return outputs
        def respond(self,prompt):
            calls.append(prompt)
            if failure:
                raise ValueError("API response {'error': 'fixture failure'}")
            if '相邻事实' in prompt:
                return json.dumps(dict(question=QUESTION,answer=ANSWER_A,reasoning_steps=[{'step':'300/2=150'}],supporting_facts=[SOURCE.split('。')[0]],type='计算'))
            if '合成负例' in prompt:
                assert QUESTION in prompt
                return json.dumps(dict(question=QUESTION,answer=ANSWER_B))
            if '根据原始材料独立回答' in prompt:
                assert ANSWER_A not in prompt
                return json.dumps(dict(question=QUESTION,answer=ANSWER_B))
            if '两个未排序候选' in prompt:
                assert ANSWER_A in prompt and ANSWER_B in prompt
                return ('bad review' if malformed else json.dumps(dict(score_a=5,score_b=5 if tie else 2,
                    grounded_a=not reject,grounded_b=tie,reason='独立测试评价')))
            if '只问图片能确定' in prompt:
                return json.dumps(dict(question=QUESTION))
            if '依据图片独立回答' in prompt:
                assert QUESTION in prompt and ANSWER_A not in prompt
                return json.dumps(dict(question=QUESTION,answer=ANSWER_B if '简洁直接' in prompt else ANSWER_A))
            if '结合图片独立核对' in prompt:
                assert QUESTION in prompt and ANSWER_A in prompt
                return ('bad review' if malformed else json.dumps(dict(score=2 if reject else 5,grounded=not reject,reason='看图核验')))
            # Reuse the native Text2QA four-dimensional score parser.
            if 'Source context:' in prompt:
                assert ORIGINAL in prompt  # original whitespace preserved, not cleaned material
            return '**Grading**: '+('2' if reject else '5')+'\n**Feedback**: 测试评分'
    return Serving


def run_pipeline(platform, monkeypatch, definition, *, reject=False, tie=False, malformed=False, sync=False, change_resource=False, failure=False, cold_worker=False, collection_target=None):
    c,root,_=platform
    from app.services import ray_pipeline_executor as worker, dataflow_engine as engine
    calls=[]
    serving=serving_fixture(calls,reject,tie,malformed,failure)
    monkeypatch.setattr(worker,'APILLMServing_request',serving)
    monkeypatch.setattr(engine,'APILLMServing_request',serving)
    monkeypatch.setitem(engine.SERVING_CLS_REGISTRY,'APILLMServing_request',serving)
    config=ready_config(c,definition)
    valid=c.pipeline_registry.validate_pipeline_config(config)
    assert valid.valid, [e.message for e in valid.errors]
    assert not valid.warnings, [e.message for e in valid.warnings]
    saved=c.pipeline_registry.create_pipeline(dict(name=definition['name'],tags=['representative-training'],config=config))
    config=c.pipeline_registry.get_pipeline(saved['id'])['config']
    # Untouched native optional text inputs serialize as empty strings.
    for op in config['operators']:
        for part in ('init','run'):
            for p in op['params'][part]:
                if p.get('value') is None:
                    p['value']=''
    check=TextGeneration().preflight(config)
    assert check['ready'],check['errors']
    c.pipeline_registry.update_pipeline(saved['id'],dict(config=config))
    async def execute(frozen,runtime,tid,*args):
        if change_resource:
            c.user_prompt_registry.update('representative-image-question-v1',template='CHANGED AFTER SUBMISSION')
        task_path = c.task_registry.path
        if cold_worker == 'process':
            payload = root/'worker-input.json'
            result_file = root/'worker-result.json'
            payload.write_text(json.dumps(dict(config=frozen,runtime=runtime,task_id=tid,task_path=task_path,
                base_dir=str(root),cache_dir=settings.CACHE_DIR)))
            script = r'''
import json, runpy, sys
from pathlib import Path
fixture = runpy.run_path(sys.argv[1])
from app.core.container import container
from app.core.config import settings
from app.services import ray_pipeline_executor as worker
assert all(value is None for value in vars(container).values())
container.init = lambda: (_ for _ in ()).throw(AssertionError('full app initialization in worker'))
data = json.loads(Path(sys.argv[2]).read_text())
settings.BASE_DIR = data['base_dir']
settings.CACHE_DIR = data['cache_dir']
calls = []
worker.APILLMServing_request = fixture['serving_fixture'](calls)
result = worker.RayPipelineExecutor._execute_pipeline_remote._function(
    data['config'],data['runtime'],data['task_id'],str(Path(data['base_dir'])/'pipelines.json'),data['task_path'])
assert all(value is None for value in vars(container).values() if not callable(value))
Path(sys.argv[3]).write_text(json.dumps(dict(result=result,calls=calls)))
'''
            process = subprocess.run([sys.executable,'-c',script,str(Path(__file__).resolve()),str(payload),str(result_file)],
                                     capture_output=True,text=True,timeout=60)
            assert process.returncode == 0, process.stderr[-6000:]
            response = json.loads(result_file.read_text())
            result = response['result']
            calls.extend(response['calls'])
        elif cold_worker:
            # Match a fresh Ray process: submission has already frozen all
            # resources; no web-app registries exist in the executing process.
            with monkeypatch.context() as cold:
                for name in vars(c):
                    cold.setattr(c, name, None)
                cold.setattr(c, 'init', lambda: pytest.fail('worker must not initialize the full application'))
                result=worker.dataflow_pipeline_execute(frozen,runtime,tid,task_path)
                assert all(value is None for value in vars(c).values() if not callable(value))
        else:
            result=engine.DataFlowEngine().run(frozen,tid,task_path) if sync else worker.dataflow_pipeline_execute(frozen,runtime,tid,task_path)
        patch_task(task_path,tid,result)
    monkeypatch.setattr(worker.ray_executor,'submit_execution',execute)
    submitted=asyncio.run(TextGeneration().submit(pipeline_id=saved['id'],output_root=str(root/'chosen-results'),collection_target=collection_target))
    task=c.task_registry.get(submitted['task_id'])
    assert task['status']==('failed' if failure else 'completed'),task.get('output')
    if not failure:
        assert len(task['output']['execution_results'])==len(definition['config']['operators'])
    assert 'TEST_ONLY' not in json.dumps(task)
    return task,TaskResults(c).detail(task['task_id']),calls


@pytest.mark.parametrize('definition',definitions(),ids=lambda d:d['id'])
@pytest.mark.parametrize('sync',[False,True],ids=['native-worker','synchronous'])
def test_full_workflows_use_native_operators_and_collect(platform,monkeypatch,definition,sync):
    c,root,material=platform
    task,detail,calls=run_pipeline(platform,monkeypatch,definition,sync=sync)
    assert detail['available'] and detail['collectable'],detail
    assert detail['artifact']['row_count']==1
    final=Path(detail['artifact']['path'])
    row=json.loads(final.read_text())
    if detail['training_type']=='dpo':
        assert row['chosen']==ANSWER_A and row['rejected']==ANSWER_B
    if detail['modality']=='image_text':
        assert (final.parent/row['images'][0]).is_file()
        assert detail['artifact']['media_bindings'][row['images'][0]]==material['id']
    result=TaskResults(c).collect(task['task_id'],detail['artifact']['sha256'],name='隔离测试收录')
    assert task['output']['auto_collection']['status']=='collected'
    assert detail['collections']
    assert result['reused'] and result['added']==0
    assert TaskResults(c).collect(task['task_id'],detail['artifact']['sha256'],name='隔离测试收录')['reused']
    assert all('CHANGED AFTER' not in p for p in calls)
    counts=[s['sample_count'] for s in task['output']['operators_detail'].values() if s.get('status')=='completed']
    assert counts[-1]==1
    assert task['resource_snapshots']


@pytest.mark.parametrize('definition',definitions(),ids=lambda d:d['id'])
@pytest.mark.parametrize('cold_worker',[True,'process'],ids=['empty-container','fresh-process'])
def test_cold_worker_executes_frozen_workflow_without_app_initialization(platform,monkeypatch,definition,cold_worker):
    task,detail,calls=run_pipeline(platform,monkeypatch,definition,cold_worker=cold_worker)
    assert task['status']=='completed'
    assert task['output']['auto_collection']['status']=='collected'
    assert detail['collections']
    assert detail['collectable'] and detail['artifact']['row_count']==1
    assert calls
    assert len(task['output']['execution_results'])==len(definition['config']['operators'])


@pytest.mark.parametrize('definition',definitions(),ids=lambda d:d['id'])
def test_generation_does_not_call_scoring_or_drop_for_scores(platform,monkeypatch,definition):
    task,detail,calls=run_pipeline(platform,monkeypatch,definition,reject=True,tie=True,malformed=True)
    assert detail['collectable'] and detail['artifact']['row_count']==1
    assert all('Grading' not in prompt and '独立评价' not in prompt and '结合图片独立核对' not in prompt for prompt in calls)
    names=[op['name'] for op in definition['config']['operators']]
    assert 'Text2QASampleEvaluator' not in names and 'TrainingReviewParser' not in names
    assert 'question_score' not in json.dumps(task['pipeline_config'])


def test_input_filter_can_remove_everything_without_calling_model(platform,monkeypatch):
    c,root,_=platform
    (root/'text.jsonl').write_text(json.dumps({'text':'太短。'})+'\n')
    _,detail,calls=run_pipeline(platform,monkeypatch,definitions()[0])
    assert not calls and detail['artifact']['row_count']==0


def test_frozen_prompt_is_used_after_manager_edit(platform,monkeypatch):
    _,detail,calls=run_pipeline(platform,monkeypatch,definitions()[2],change_resource=True)
    assert detail['collectable'] and all('CHANGED AFTER' not in p for p in calls)



def test_http_transport_receives_actual_image_and_context_without_network(platform,monkeypatch):
    import requests
    from dataflow.serving import APILLMServing_request
    from app.services.simple_training_operators import APIImagePairGenerator,image_data
    c,_,material=platform
    path,_=c.data_library.material_file(material['id'])
    sent=[];written=[]
    def post(session,url,**kwargs):
        payload=json.loads(kwargs['data']);sent.append(payload)
        blocks=payload['messages'][0]['content']
        assert blocks[1]['image_url']['url']==image_data(path)
        assert QUESTION in blocks[0]['text']
        return SimpleNamespace(status_code=200,json=lambda:{'choices':[{'message':{'content':'{"answer":"fixture"}'}}]})
    monkeypatch.setattr(requests.Session,'post',post)
    monkeypatch.setenv('REPRESENTATIVE_TEST_KEY','TEST_ONLY')
    serving=APILLMServing_request(api_url='https://offline.invalid/v1/chat/completions',model_name='fixture',
        key_name_of_api_key='REPRESENTATIVE_TEST_KEY',max_workers=1,max_retries=1)
    storage=SimpleNamespace(read=lambda _:pd.DataFrame([dict(source=str(path),question=json.dumps({'question':QUESTION}))]),write=lambda f:written.append(f.copy()))
    APIImagePairGenerator(serving,SimpleNamespace(build_prompt=lambda:'看图回答')).run(storage,input_context_key='question')
    assert len(sent)==1 and len(written)==1


def test_bad_upstream_image_question_never_calls_next_model(platform):
    from app.services.simple_training_operators import APIImagePairGenerator
    c,_,material=platform
    path,_=c.data_library.material_file(material['id'])
    frame=pd.DataFrame([dict(source=str(path),question='not JSON')])
    serving=SimpleNamespace(generate_from_conversations=lambda _:pytest.fail('must not call model'))
    out=[]
    APIImagePairGenerator(serving,SimpleNamespace(build_prompt=lambda:'test')).run(
        SimpleNamespace(read=lambda _:frame,write=lambda f:out.append(f.copy())),input_context_key='question')
    assert out[0]['candidate'].tolist()==['']
    assert out[0]['_training_issues'][0]



def test_error_messages_with_json_braces_are_recorded_without_masking_failure(platform,monkeypatch):
    task,detail,_=run_pipeline(platform,monkeypatch,definitions()[2],failure=True)
    assert not detail['available']
    assert 'fixture failure' in json.dumps(task,ensure_ascii=False)
    assert 'KeyError' not in json.dumps(task,ensure_ascii=False)


def test_every_model_node_requires_service_before_queueing(platform,monkeypatch):
    c,root,_=platform
    for definition in definitions():
        config=ready_config(c,definition)
        llm=[p for op in config['operators'] for p in op['params']['init'] if p['name']=='llm_serving']
        assert len(llm)>=1
        llm[-1]['value']=None
        saved=c.pipeline_registry.create_pipeline(dict(name='未配置',config=config))
        with pytest.raises(LibraryError,match='未配置文本服务'):
            asyncio.run(TextGeneration().submit(pipeline_id=saved['id'],output_root=str(root/'unused')))
    assert not c.task_registry.list_executions() and not (root/'unused').exists()


def test_catalog_envelopes_live_details_and_restart_semantics(platform):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.v1.endpoints import pipelines,prompts,json_schemas,operators
    c,root,_=platform
    app=FastAPI()
    for name,module in [('pipelines',pipelines),('prompts',prompts),('json_schemas',json_schemas),('operators',operators)]:
        app.include_router(module.router,prefix='/'+name)
    client=TestClient(app)
    for route in ['/pipelines/templates','/prompts/user','/json_schemas']:
        r=client.get(route);assert r.status_code==200,r.text
    assert len(client.get('/pipelines/templates').json()['data'])==4
    for name in ('TrainingQAExpander','TrainingPreferenceBuilder','TrainingReviewParser'):
        assert client.get('/operators/details/'+name).status_code==200
    before=c.pipeline_registry._read()
    c.user_prompt_registry.update('representative-qa-v1',template='用户编辑 {text}')
    c.user_prompt_registry.delete('representative-image-review-v1')
    install_templates(c)
    assert c.pipeline_registry._read()==before
    assert c.user_prompt_registry.get('representative-qa-v1')['template']=='用户编辑 {text}'
    assert c.user_prompt_registry.get('representative-image-review-v1') is None
    # Even recreating a deleted default pipeline must respect resource deletion.
    data=c.pipeline_registry._read()
    del data['pipelines']['representative-image_text-sft-v1']
    c.pipeline_registry._write(data)
    install_templates(c)
    assert c.user_prompt_registry.get('representative-image-review-v1') is None


def test_replaces_only_legacy_templates_with_recoverable_backup(platform):
    c,root,_=platform
    data=c.pipeline_registry._read()
    for key in LEGACY_IDS:
        data['pipelines'][key]=dict(id=key,name='旧示例',config={'operators':[]},tags=['template','simple-training'])
    # A user copy references one old resource; its resource must survive.
    retained=sorted(LEGACY_IDS)[0]
    data['pipelines']['keep']['config']['note']='user_prompt:'+retained
    c.pipeline_registry._write(data)
    for manager in (c.user_prompt_registry,c.json_schema_manager):
        with manager.store.writing() as records:
            for key in LEGACY_IDS: records[key]=dict(id=key,name='旧资源',template='old',schema='{}')
    install_templates(c)
    data=c.pipeline_registry._read()
    assert not LEGACY_IDS.intersection(data['pipelines'])
    assert data['pipelines']['keep']['name']=='用户自己的流程'
    assert c.user_prompt_registry.get(retained)
    assert len(list((root/'backups'/'replaced-simple-training').glob('*.json')))==1
    assert not c.task_registry.list_executions()


@pytest.mark.parametrize('review', [None,'bad JSON',{'score_a':5,'score_b':5,'grounded_a':True,'grounded_b':True,'reason':'tie'},
    {'score_a':5,'score_b':2,'grounded_a':'true','grounded_b':False,'reason':'invalid bool'},
    {'score_a':99,'score_b':2,'grounded_a':True,'grounded_b':False,'reason':'out of range'}])
def test_invalid_or_tied_reviews_never_admit(review):
    schema=next(s['schema'] for s in resources()[1] if s['id']=='representative-dpo-review-v1')
    frame=pd.DataFrame([dict(review=review,alternatives=dict(question=QUESTION,answer_a=ANSWER_A,answer_b=ANSWER_B))])
    out=[];storage=SimpleNamespace(read=lambda _:frame,write=lambda f:out.append(f.copy()))
    TrainingReviewParser('dpo',schema).run(storage,input_candidate_key='alternatives',output_candidate_key='admitted_candidate')
    assert not out[0]['accepted'][0]


def test_preference_ranking_selects_b_when_b_is_better_and_preserves_raw_candidates():
    schema=next(s['schema'] for s in resources()[1] if s['id']=='representative-dpo-review-v1')
    review=dict(score_a=2,score_b=5,grounded_a=False,grounded_b=True,reason='B wins')
    original=dict(question=QUESTION,answer_a=ANSWER_B,answer_b=ANSWER_A)
    frame=pd.DataFrame([dict(review=review,alternatives=original)])
    out=[];storage=SimpleNamespace(read=lambda _:frame,write=lambda f:out.append(f.copy()))
    TrainingReviewParser('dpo',schema).run(storage,input_candidate_key='alternatives',output_candidate_key='admitted_candidate')
    assert out[0]['admitted_candidate'][0]['chosen']==ANSWER_A
    assert out[0]['alternatives'][0]==original


def test_candidate_question_mismatch_fails_before_ranking():
    frame=pd.DataFrame([dict(candidate_a=dict(question='Q1',answer='A'),candidate_b=dict(question='Q2',answer='B'))])
    out=[]
    TrainingPreferenceBuilder().run(SimpleNamespace(read=lambda _:frame,write=lambda f:out.append(f.copy())))
    assert out[0]['_training_issues'][0]
    assert out[0]['alternatives'][0]['question']==''



def test_qa_expansion_preserves_original_source():
    pair=dict(question=QUESTION,answer=ANSWER_A)
    frame=pd.DataFrame([dict(text=SOURCE,id='source',qa_pairs=[pair,pair])]);out=[]
    TrainingQAExpander().run(SimpleNamespace(read=lambda _:frame,write=lambda f:out.append(f.copy())))
    assert len(out[0])==2 and out[0]['text'].tolist()==[SOURCE,SOURCE]


@pytest.mark.parametrize('definition',definitions(),ids=lambda d:d['id'])
def test_scored_saved_copy_migrates_once_preserving_input_and_services(platform,definition):
    c,root,_=platform
    old=ready_config(c,definition)
    old['execution_options'].pop('scoring_policy')
    old['operators']=[op for op in old['operators'] if not (op['name']=='PandasOperator' and
        any(p.get('value')=='preference_candidate' for p in op['params']['run']))]
    old['operators'].insert(-2,dict(name='Text2QASampleEvaluator',params={'init':[], 'run':[]}))
    old['operators'].insert(-2,dict(name='GeneralFilter',params={'init':[{'name':'filter_rules','value':["lambda df: df['question_score'].ge(4)"]}], 'run':[]}))
    mode=old['execution_options']['simple_training']
    if mode['training_type']=='dpo' or mode['modality']=='image_text':
        old['operators'].insert(-2,dict(name='APIImagePairGenerator' if mode['modality']=='image_text' else 'FormatStrPromptedGenerator',
            params={'init':[], 'run':[{'name':'output_key','value':'review'}]}))
        old['operators'].insert(-2,dict(name='TrainingReviewParser',params={'init':[], 'run':[]}))
        old['operators'].insert(-2,dict(name='GeneralFilter',params={'init':[{'name':'filter_rules','value':["lambda df: df['accepted'].eq(True)"]}], 'run':[]}))
        for op in old['operators']:
            for param in op['params']['run']:
                if op['name']=='TrainingPairFormatter' and param['name']=='input_key':param['value']='admitted_candidate'
                if op['name']=='HashDeduplicateFilter' and isinstance(param.get('value'),list):
                    param['value']=['admitted_candidate' if v in ('candidate_a','preference_candidate') else v for v in param['value']]
    data=c.pipeline_registry._read()
    record=copy.deepcopy(data['pipelines'][definition['id']])
    record.update(id='saved-copy',name='我的既有配置',tags=['user'],config=old)
    data['pipelines']['saved-copy']=record;c.pipeline_registry._write(data)
    install_templates(c)
    migrated=c.pipeline_registry.get_pipeline('saved-copy')
    assert migrated['name']==record['name'] and migrated['tags']==record['tags']
    assert migrated['config']['input_dataset']==old['input_dataset']
    assert migrated['config']['execution_options']['scoring_policy']=='none'
    assert remove_scoring(migrated['config'])==migrated['config']
    assert [op['name'] for op in migrated['config']['operators']]==[op['name'] for op in definition['config']['operators']]
    assert all(p['value']=='offline' for op in migrated['config']['operators'] for p in op['params']['init'] if p['name']=='llm_serving')
    valid=c.pipeline_registry.validate_pipeline_config(migrated['config']);assert valid.valid,valid.errors
    before=c.pipeline_registry._read();install_templates(c);assert c.pipeline_registry._read()==before
    backups=list((root/'backups'/'removed-training-scoring').glob('*.json'))
    assert len(backups)==1 and json.loads(backups[0].read_text())['saved-copy']==record


@pytest.mark.parametrize('definition',definitions(),ids=lambda d:d['id'])
@pytest.mark.parametrize('mode',['new','append'])
def test_all_workflows_honor_selected_collection_target(platform,monkeypatch,definition,mode):
    from app.schemas.data_library import DraftCreate
    c,_,_=platform
    contract=definition['config']['execution_options']['simple_training']
    draft=c.data_library.create_draft(DraftCreate(name='existing target',**contract))
    target=dict(mode=mode,name='chosen new name' if mode=='new' else '',draft_id=draft['id'] if mode=='append' else None)
    task,detail,_=run_pipeline(platform,monkeypatch,definition,collection_target=target)
    assert detail['auto_collection']['status']=='collected'
    assert detail['collections'][0]['name']==('chosen new name' if mode=='new' else 'existing target')
    assert len(c.data_library.list_drafts())==(2 if mode=='new' else 1)
    if mode=='append':assert detail['collections'][0]['id']==draft['id']
