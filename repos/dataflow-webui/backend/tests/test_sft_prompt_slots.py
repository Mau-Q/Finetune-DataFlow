"""Actual core consumers, immutable resolution and both production execution loops."""
import copy
from types import SimpleNamespace
import pytest
import pandas as pd
from app.core.container import container
from app.services.user_prompt_registry import UserPromptRegistry
from app.services.prompt_contracts import CONTRACTS, RUBRICS
from app.services.resource_resolution import resolve_pipeline_resources, instantiate_prompt, ResourceReferenceError
from app.services.operator_registry import _get_method_params
from dataflow.operators.knowledge_cleaning import KBCTextCleaner
from dataflow.operators.core_text import Text2MultiHopQAGenerator, Text2QASampleEvaluator
from dataflow.operators.text_sft import AlpagasusSampleEvaluator

CLASSES = {c.__name__:c for c in [KBCTextCleaner, Text2MultiHopQAGenerator, Text2QASampleEvaluator, AlpagasusSampleEvaluator]}
SLOTS = [(op,param) for op,slots in CONTRACTS.items() if op in CLASSES for param in slots]

@pytest.fixture
def env(tmp_path,monkeypatch):
    own=UserPromptRegistry(tmp_path/'prompts.json')
    def details(name):
        cls=CLASSES.get(name)
        if cls is None:return None
        return {'name':name,'allowed_prompts':[c.__name__ for c in cls.ALLOWED_PROMPTS], 'parameter':{'init':_get_method_params(cls.__init__,True),'run':_get_method_params(cls.run,True)}}
    monkeypatch.setattr(container,'user_prompt_registry',own)
    monkeypatch.setattr(container,'operator_registry',SimpleNamespace(get_op_details=details))
    return own,details

def config(op,param,ref):
    return {'file_path':'','input_dataset':{'id':'fixture'},'operators':[{'name':op,'params':{'init':[{'name':param,'value':{'ref':ref}}], 'run':[]}}]}

@pytest.mark.parametrize('op,param',SLOTS)
def test_all_seven_slots_freeze_compatible_content(env,op,param):
    own,_=env
    text='CUSTOM '+('{text}' if CONTRACTS[op][param]['required'] else '评分标准：重视来源证据')
    record=own.create('p','',text,allowed_operators=[op]); raw=config(op,param,'user_prompt:'+record['id']); before=copy.deepcopy(raw)
    resolved,snapshots=resolve_pipeline_resources(raw)
    own.delete(record['id'])
    prompt=instantiate_prompt(resolved['operators'][0]['params']['init'][0]['value'])
    rendered=prompt.build_prompt('SOURCE') if '{text}' in text else prompt.build_prompt()
    assert 'CUSTOM' in rendered and '{text}' not in rendered
    assert raw==before and snapshots[0]['content']['template']==text
    assert snapshots[0]['param_name']==param
    if op=='Text2MultiHopQAGenerator':
        assert 'reasoning_steps' in rendered and prompt.build_system_prompt()

@pytest.mark.parametrize('op,param,text',[
    ('KBCTextCleaner','prompt_template','No source variable'),
    ('Text2MultiHopQAGenerator','prompt_template','{question}'),
    ('Text2QASampleEvaluator','question_quality_prompt_template','Score {answer}'),
    ('AlpagasusSampleEvaluator','prompt_template','{text}'),
])
def test_protocol_mismatch_rejected_before_execution(env,op,param,text):
    own,_=env;record=own.create('bad','',text)
    with pytest.raises(ResourceReferenceError):resolve_pipeline_resources(config(op,param,'user_prompt:'+record['id']))

class Storage:
    def __init__(self,rows):self.frame=pd.DataFrame(rows)
    def read(self,_):return self.frame.copy()
    def write(self,frame):self.frame=frame

class Serving:
    def __init__(self,response):self.response=response;self.seen=[]
    def generate_from_input(self,user_inputs,system_prompt="",**kwargs):
        self.seen.extend(user_inputs)
        return [self.response]*len(user_inputs)

def test_actual_four_dimension_evaluator_preserves_inputs_scales_and_failures(env):
    own,_=env
    prompts={}
    for param in RUBRICS:
        record=own.create(param,'','CUSTOM '+param)
        frozen,_=resolve_pipeline_resources(config('Text2QASampleEvaluator',param,'user_prompt:'+record['id']))
        prompts[param]=instantiate_prompt(frozen['operators'][0]['params']['init'][0]['value'])
    serving=Serving('**Grading**: 4\n**Feedback**: supported')
    op=Text2QASampleEvaluator(serving,**prompts)
    storage=Storage([dict(question='Q',answer='A',context='SOURCE',facts=['EVIDENCE'])])
    op.run(storage,input_question_key='question',input_answer_key='answer',input_context_key='context',input_supporting_facts_key='facts')
    for index,param in enumerate(RUBRICS):
        assert 'CUSTOM '+param in serving.seen[index]
        assert 'Question: Q' in serving.seen[index] and 'Answer: A' in serving.seen[index]
        assert '**Grading**' in serving.seen[index] and '1 to 5' in serving.seen[index]
    assert 'SOURCE' in serving.seen[2] and 'EVIDENCE' in serving.seen[2]
    assert storage.frame.question_quality_grades.tolist()==[4]
    serving.response='**Grading**: 99\n**Feedback**: invalid'
    grades,_,audit=op._score_dimension(['x'])
    assert grades==[None] and audit[0]['parse_status']!='parsed'

def test_actual_cleaner_and_alpagasus_use_managed_text(env):
    own,_=env
    for name,text,response,row,run in [
        ('KBCTextCleaner','CUSTOM clean {text}','<cleaned_start>cleaned<cleaned_end>',{'source':'RAW'},dict(input_key='source',output_key='clean')),
        ('AlpagasusSampleEvaluator','CUSTOM grade','4\nGood',{'q':'Q','i':'I','a':'A'},dict(input_instruction_key='q',input_input_key='i',input_output_key='a',output_key='grade')),
    ]:
        record=own.create(name,'',text);frozen,_=resolve_pipeline_resources(config(name,'prompt_template','user_prompt:'+record['id']))
        serving=Serving(response); prompt=instantiate_prompt(frozen['operators'][0]['params']['init'][0]['value'])
        op=CLASSES[name](llm_serving=serving,prompt_template=prompt)
        storage=Storage([row]);op.run(storage,**run)
        assert 'CUSTOM' in serving.seen[0]
        if name=='KBCTextCleaner':assert 'RAW' in serving.seen[0] and storage.frame.clean.tolist()==['cleaned']
        else:
            assert 'Instruction: Q' in serving.seen[0] and 'Response: A' in serving.seen[0] and '0 to 5' in serving.seen[0]
            serving.response='nan';assert op.get_score([row],'q','i','a')==[None]

@pytest.mark.parametrize('path',['sync','ray'])
def test_real_execution_loops_consume_named_rubric_slots(env,tmp_path,monkeypatch,path):
    from app.services import dataflow_engine,ray_pipeline_executor
    from app.services.task_registry import TaskRegistry
    from app.core.config import settings
    from dataflow.utils.registry import OPERATOR_REGISTRY
    own,_=env
    serving=Serving('**Grading**: 4\n**Feedback**: okay')
    class FixtureEvaluator(Text2QASampleEvaluator):
        def __init__(self, question_quality_prompt_template=None, answer_alignment_prompt_template=None,
                     answer_verifiability_prompt_template=None, downstream_value_prompt_template=None):
            super().__init__(serving,question_quality_prompt_template,answer_alignment_prompt_template,
                             answer_verifiability_prompt_template,downstream_value_prompt_template)
    original_get=OPERATOR_REGISTRY.get
    monkeypatch.setattr(OPERATOR_REGISTRY,'_get_all',lambda:None)
    monkeypatch.setattr(OPERATOR_REGISTRY,'get',lambda name:FixtureEvaluator if name=='Text2QASampleEvaluator' else original_get(name))
    record=own.create('quality','','CUSTOM execution rubric')
    raw=config('Text2QASampleEvaluator','question_quality_prompt_template','user_prompt:'+record['id'])
    raw['operators'][0]['params']['run']=[{'name':'input_question_key','value':'q'},{'name':'input_answer_key','value':'a'}]
    source=tmp_path/'input.jsonl';source.write_text('{"q":"Q","a":"A"}\n')
    monkeypatch.setattr(container,'dataset_registry',SimpleNamespace(get=lambda _:dict(root=str(source))))
    monkeypatch.setattr(settings,'CACHE_DIR',str(tmp_path/'cache'))
    tasks=TaskRegistry(str(tmp_path/'tasks.json'));task_id,frozen,_=tasks.start_execution(config=raw)
    own.delete(record['id'])
    if path=='sync':result=dataflow_engine.DataFlowEngine().run(frozen,task_id,execution_path=tasks.path)
    else:result=ray_pipeline_executor.dataflow_pipeline_execute(frozen,{'storage':dict(first_entry_file_name=str(source),cache_path=str(tmp_path/'ray'),file_name_prefix='step',cache_type='jsonl'),'serving_map':{},'embedding_serving_map':{},'db_manager_map':{}},task_id,tasks.path)
    assert result['status']=='completed',result['logs']
    assert 'CUSTOM execution rubric' in serving.seen[0]
    assert len(serving.seen)==4


def test_contract_api_is_not_shadowed_by_operator_prompt_route():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.v1.endpoints.prompts import router
    app=FastAPI();app.include_router(router,prefix='/prompts')
    result=TestClient(app).get('/prompts/contracts').json()
    assert result['success'] and len(result['data']['Text2QASampleEvaluator'])==4


def test_named_slots_catalog_replaces_only_selected_default(env,tmp_path,monkeypatch):
    from app.services.resource_catalog import ResourceCatalog
    own,details=env
    rec=own.create('quality','','My rubric')
    op=config('Text2QASampleEvaluator','question_quality_prompt_template','user_prompt:'+rec['id'])['operators'][0]
    container_stub=SimpleNamespace(user_prompt_registry=own, json_schema_manager=None,
        prompt_registry=SimpleNamespace(list_prompt_info=lambda:SimpleNamespace(model_dump=lambda:{'prompts':{builtin:dict(operator=['Text2QASampleEvaluator'],description='',primary_type='core_text',parameter=dict(init=[],build_prompt=[]),class_str=builtin) for _,builtin in RUBRICS.values()}})),
        pipeline_registry=SimpleNamespace(list_pipelines=lambda:[dict(id='fixture',name='fixture',config={'operators':[op]})],_is_preset_pipeline=lambda _:False),
        data_library=SimpleNamespace(root=tmp_path),operator_registry=SimpleNamespace(get_op_details=details))
    result=ResourceCatalog(container_stub).prompts()['resources']
    refs=lambda name:[r for item in result if item['id']==name for r in item['references'] if r['pipeline_id']=='pipeline:fixture']
    assert refs(rec['id'])[0]['field']=='question_quality_prompt_template'
    assert not refs('Text2QAQuestionQualityPrompt')
    assert refs('Text2QAAnswerAlignmentPrompt')[0]['field']=='answer_alignment_prompt_template'


def test_native_empty_optional_values_preserve_defaults_and_required_inputs(env):
    raw={'operators':[{'name':'Text2QASampleEvaluator','params':{'init':[{'name':'llm_serving','value':''},{'name':'question_quality_prompt_template','value':''}], 'run':[{'name':'input_context_key','value':''},{'name':'input_supporting_facts_key','value':''},{'name':'input_question_key','value':''}]}}]}
    frozen,_=resolve_pipeline_resources(raw)
    params=frozen['operators'][0]['params']
    assert all(p['value'] is None for p in params['init'])
    assert params['run'][0]['value'] is None and params['run'][1]['value'] is None
    assert params['run'][2]['value']==''  # required inputs cannot be silently dropped
    assert raw['operators'][0]['params']['init'][0]['value']==''


def test_actual_multihop_consumer_uses_prompt_and_keeps_json_protocol(env):
    import json
    from dataflow.operators.core_text.generate.text2multihopqa_generator import ExampleConstructor
    own,_=env
    rec=own.create('qa','','CUSTOM question from {text}')
    frozen,_=resolve_pipeline_resources(config('Text2MultiHopQAGenerator','prompt_template','user_prompt:'+rec['id']))
    prompt=instantiate_prompt(frozen['operators'][0]['params']['init'][0]['value'])
    expected=dict(question='Q',answer='A',reasoning_steps=[{'step':'reason'}],supporting_facts=['P','I'],type='fact')
    serving=Serving(json.dumps(expected))
    worker=ExampleConstructor(llm_serving=serving,prompt_template=prompt,max_requests_per_chunk=1)
    rows=worker._generate_qa_pairs([dict(premise='P',intermediate='I',conclusion='C')])
    assert rows==[expected]
    assert 'CUSTOM question from P. I. C' in serving.seen[0]
    assert 'reasoning_steps' in serving.seen[0]


def test_isolated_acceptance_uses_real_resource_and_pipeline_apis(tmp_path,monkeypatch):
    from pathlib import Path
    from fastapi.testclient import TestClient
    from app.core.config import settings
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'scripts'))
    from preview_sft_prompts import configure
    from preview_task_results import create_preview
    for key,value in vars(container).copy().items():monkeypatch.setattr(container,key,value)
    for key in ('BASE_DIR','RESOURCE_DIR','CACHE_DIR','PREFERENCES_PATH'):monkeypatch.setattr(settings,key,getattr(settings,key))
    client=TestClient(create_preview(tmp_path/'preview',configure))
    assert client.get('/api/v1/datasets/').json()['success']
    assert client.get('/api/v1/prompts/prompt-info').json()['success']
    assert len(client.get('/api/v1/pipelines/').json()['data'])==4
    for pipeline in client.get('/api/v1/pipelines/').json()['data']:
        assert client.get('/api/v1/pipelines/'+pipeline['id']).json()['success']
    previews=client.post('/api/v1/prompt-acceptance/verify').json()
    assert previews['success'] and len(previews['data'])==7
    mm=client.get('/api/v1/multimodal/configs').json()['data'][0]
    checked=client.get('/api/v1/multimodal/configs/'+mm['id']+'/check').json()['data']
    assert checked['structure_valid'] and not checked['ready']
    result=client.post('/api/v1/multimodal/configs/'+mm['id']+'/submit').json()
    assert not result['success'] and result['meta']['http_status']==409


def test_inline_adapter_cannot_bypass_fixed_slot_variables(env):
    raw=config('Text2QASampleEvaluator','question_quality_prompt_template','unused')
    raw['operators'][0]['params']['init'][0]['value']={'cls_name':'FormatStrPrompt','resource_template':'Score {answer}'}
    with pytest.raises(ResourceReferenceError,match='只允许变量'):resolve_pipeline_resources(raw)
    raw['operators'][0]['params']['init'][0]['value']['resource_template']='Valid rubric'
    frozen,_=resolve_pipeline_resources(raw)
    prompt=instantiate_prompt(frozen['operators'][0]['params']['init'][0]['value'])
    assert prompt.build_prompt()=='Valid rubric'
