"""Catalog browsing never mutates resources or equates compatibility with use."""
import json
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.v1.endpoints import prompts as prompt_api, json_schemas as schema_api
from app.api.v1.handlers import install_exception_handlers
from app.core.container import container
from app.services.resource_catalog import ResourceCatalog
from app.services.user_prompt_registry import UserPromptRegistry
from app.services.json_schema_manager import JsonSchemaManager, validate_schema
from app.services.builtin_resources import builtin_schemas
from app.services.resource_resolution import resolve_pipeline_resources


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    own = UserPromptRegistry(tmp_path / 'prompts.json')
    schemas = JsonSchemaManager(tmp_path / 'schemas.json')
    prompt = own.create('mine', 'own prompt', 'Answer {question}', ['FormatStrPromptedGenerator'], {'question':'test'}, usage='文本 SFT', purpose='生成')
    schema = schemas.create('mine schema', '', '{"type":"object"}', '{}', usage='文本 SFT', purpose='模型输出')
    mapping = {'Text2MultiHopQAGeneratorPrompt': {'operator':['Text2MultiHopQAGenerator'], 'description':'QA generation',
               'primary_type':'core_text','parameter':{'init':[], 'build_prompt':[{'name':'text'}]}, 'class_str':'test.Prompt'}}
    pipelines = [
        {'id':'used','name':'Used', 'config':{'operators':[{'name':'FormatStrPromptedGenerator','params':{'init':[
            {'name':'prompt_template','value':{'ref':'user_prompt:'+prompt['id'],'bindings':{'question':'text'}}},
            {'name':'json_schema','value':'schema_ref:'+schema['id']}], 'run':[]}}]}},
        {'id':'compatible','name':'Compatible only', 'config':{'operators':[{'name':'FormatStrPromptedGenerator','params':{}}]}},
        {'id':'builtin','name':'Builtin class', 'tags':['api','template'], 'config':{'operators':[{'name':'Text2MultiHopQAGenerator', 'params':{'prompt_template':{'cls_name':'Text2MultiHopQAGeneratorPrompt','params':[]}}}]}}
    ]
    app_container = SimpleNamespace(user_prompt_registry=own, json_schema_manager=schemas,
        prompt_registry=SimpleNamespace(list_prompt_info=lambda:SimpleNamespace(model_dump=lambda:{'prompts':mapping})),
        pipeline_registry=SimpleNamespace(list_pipelines=lambda:pipelines, _is_preset_pipeline=lambda p:'api' in p.get('tags',[])), data_library=SimpleNamespace(root=tmp_path),
        operator_registry=SimpleNamespace(get_op_details=lambda name:{'parameter':{'init':[{'name':'json_schema'}], 'run':[]}}))
    for name,value in vars(app_container).items():
        monkeypatch.setattr(container,name,value)
    return ResourceCatalog(app_container), own, schemas, prompt, schema


def test_catalog_records_saved_use_separately_from_compatibility(catalog):
    service,own,schemas,prompt,schema=catalog
    before=(own.store.path.read_bytes(),schemas.store.path.read_bytes())
    result=service.prompts()
    assert {p['id'] for p in result['pipelines'] if p['source']=='user'} == {'pipeline:used','pipeline:compatible'}
    assert next(p for p in result['pipelines'] if p['id']=='template:image-sft')['source']=='builtin'
    row=next(r for r in result['resources'] if r['source']=='user')
    assert row['id']==prompt['id'] and row['usages']==['文本 SFT']
    assert row['operators']==['FormatStrPromptedGenerator']
    assert [r['pipeline_id'] for r in row['references']]==['pipeline:used']
    assert row['references'][0]['bindings']=={'question':'text'}
    builtin=next(r for r in result['resources'] if r['id']=='Text2MultiHopQAGeneratorPrompt')
    assert any(r['pipeline_id']=='pipeline:builtin' for r in builtin['references'])
    mm=next(r for r in result['resources'] if r['id']=='mm-answer-v1')
    assert mm['variables']==['question'] and mm['readonly']
    assert mm['references'][0]['pipeline_id']=='template:image-sft'
    own_schema=next(r for r in service.schemas()['resources'] if r['id']==schema['id'])
    assert [r['pipeline_id'] for r in own_schema['references']]==['pipeline:used']
    assert (own.store.path.read_bytes(),schemas.store.path.read_bytes())==before


def test_all_builtin_schemas_validate_their_examples_and_are_readonly(catalog):
    _,_,manager,_,_=catalog
    before=manager.store.path.read_bytes()
    records=builtin_schemas()
    assert len(records)==6
    for row in records:
        validate_schema(row['schema'],row['example'])
        assert manager.get(row['id'])['schema']==row['schema']
        assert manager.update(row['id'],name='overwrite') is None
        assert not manager.delete(row['id'])
    assert manager.store.path.read_bytes()==before


@pytest.mark.parametrize('key,example',[
    ('builtin-text-sft-v1', {'instruction':'q','output':' '}),
    ('builtin-text-dialogue-sft-v1', {'messages':[{'role':'user','content':'q'}]}),
    ('builtin-image-sft-v1', {'instruction':'q','output':'a'}),
    ('builtin-text-dpo-v1', {'prompt':'q','chosen':'a'}),
    ('builtin-image-dpo-v1', {'prompt':'q','chosen':'a','rejected':'b','images':[]}),
    ('builtin-mm-qa-v1', {'question':'q'}),
])
def test_builtin_examples_reject_missing_or_empty_training_structure(key,example):
    schema=next(r for r in builtin_schemas() if r['id']==key)
    with pytest.raises(ValueError):validate_schema(schema['schema'],json.dumps(example))


def test_builtin_schema_reference_is_resolved_and_frozen(catalog):
    _,_,manager,_,_=catalog
    config={'operators':[{'name':'FormatStrPromptedGenerator','params':{'init':[{'name':'json_schema','value':'schema_ref:builtin-mm-qa-v1'}], 'run':[]}}]}
    executable,snapshots=resolve_pipeline_resources(config)
    expected=json.loads(manager.get('builtin-mm-qa-v1')['schema'])
    assert executable['operators'][0]['params']['init'][0]['value']==expected
    assert snapshots[0]['ref']=='schema_ref:builtin-mm-qa-v1' and snapshots[0]['sha256']
    assert config['operators'][0]['params']['init'][0]['value']=='schema_ref:builtin-mm-qa-v1'


def test_catalog_and_metadata_crud_api_preserve_existing_ids(catalog):
    service,own,manager,prompt,schema=catalog
    app=FastAPI();app.include_router(prompt_api.router,prefix='/api/v1/prompts');app.include_router(schema_api.router,prefix='/api/v1/json_schemas');install_exception_handlers(app)
    with TestClient(app) as client:
        assert client.get('/api/v1/prompts/catalog').json()['success']
        records=client.get('/api/v1/json_schemas/catalog').json()['data']['resources']
        assert sum(r['source']=='builtin' for r in records)==6
        assert len(client.get('/api/v1/json_schemas').json()['data'])==1
        assert len(client.get('/api/v1/json_schemas?include_builtin=true').json()['data'])==7
        result=client.put('/api/v1/prompts/user/'+prompt['id'],json={'usage':'通用','purpose':'清洗'}).json()
        assert result['data']['id']==prompt['id'] and result['data']['template']==prompt['template']
        assert own.get(prompt['id'])['purpose']=='清洗'
        result=client.put('/api/v1/json_schemas/'+schema['id'],json={'purpose':'训练样本校验'}).json()
        assert result['data']['id']==schema['id'] and result['data']['schema']==schema['schema']
        copied=client.post('/api/v1/json_schemas',json={k:records[-1][k] for k in ['name','schema','example','usage','purpose']}).json()
        assert copied['success'] and copied['data']['id'].startswith('schema_')
        assert not client.put('/api/v1/json_schemas/builtin-mm-qa-v1',json={'name':'bad'}).json()['success']


def test_builtin_preview_renders_registered_parameters_without_model_calls(monkeypatch):
    from app.services import resource_resolution
    calls = []
    def construct(value):
        calls.append(value)
        if value['cls_name'] == 'missing':
            raise ValueError('Prompt class not found')
        return SimpleNamespace(build_prompt=lambda text: 'Question: ' + text)
    monkeypatch.setattr(resource_resolution, 'instantiate_prompt', construct)
    app = FastAPI()
    app.include_router(prompt_api.router, prefix='/api/v1/prompts')
    install_exception_handlers(app)
    with TestClient(app) as client:
        result = client.post('/api/v1/prompts/builtin-preview', json={
            'name': 'RegisteredPrompt', 'init': {'lang': 'zh'}, 'variables': {'text': 'example'}
        }).json()
        assert result['data']['rendered'] == 'Question: example'
        assert calls[0] == {'cls_name': 'RegisteredPrompt', 'params': [{'name': 'lang', 'value': 'zh'}]}
        result = client.post('/api/v1/prompts/builtin-preview', json={'name': 'missing'}).json()
        assert not result['success'] and result['meta']['http_status'] == 422


def test_personal_scope_includes_actual_text_and_image_flow_resources(catalog):
    from app.services.text_generation import template as text_template
    from app.services.multimodal_templates import template as image_template
    from app.services.resource_catalog import TEXT_SFT
    from app.services.resource_store import ResourceStore
    service, own, schemas, _, _ = catalog
    mapping = {name: {'operator': [], 'description': '', 'primary_type': 'core_text',
               'parameter': {'init': [], 'build_prompt': []}, 'class_str': 'test.' + name} for name in TEXT_SFT}
    mapping['UnusedPrompt'] = dict(mapping['KnowledgeCleanerPrompt'])
    service.c.prompt_registry.list_prompt_info = lambda: SimpleNamespace(model_dump=lambda: {'prompts': mapping})
    flow = text_template()
    flow.update(id='personal-text', name='My text')
    service.c.pipeline_registry.list_pipelines = lambda: [flow]
    image = image_template()
    image.update(id='personal-image', name='My image')
    store = ResourceStore(service.c.data_library.root / 'multimodal_configs.json')
    with store.writing() as data:
        data[image['id']] = image
    before = (own.store.path.read_bytes(), schemas.store.path.read_bytes(), store.path.read_bytes())
    result = service.prompts()
    personal = [r for r in result['resources'] if r['personal']]
    assert {r['id'] for r in personal if r['kind'] == 'python'} == TEXT_SFT
    assert sum(r['id'].startswith('mm-') for r in personal) == 2
    assert not next(r for r in result['resources'] if r['id'] == 'UnusedPrompt')['personal']
    assert len({r['ref'] for r in personal}) == len(personal)
    def reference(name):
        return next(ref for r in personal if r['id'] == name for ref in r['references']
                    if ref['pipeline_id'] == 'pipeline:personal-text')
    cleaner = reference('KnowledgeCleanerPrompt')
    assert next(p for p in result['pipelines'] if p['id']=='pipeline:personal-text')['family']=='text-sft'
    assert next(p for p in result['pipelines'] if p['id']=='multimodal:personal-image')['family']=='image-sft'
    assert next(p for p in result['pipelines'] if p['id']=='template:text-sft')['origin']=='platform_template'
    assert cleaner['kind'] == 'operator_default'
    assert cleaner['parameters']['constructor'] == {'lang': 'en'}
    assert cleaner['parameters']['operator']['run']['input_key'] == 'raw_chunk'
    qa = reference('Text2MultiHopQAGeneratorPrompt')
    assert qa['kind'] == 'explicit' and qa['parameters']['constructor'] == {'lang': 'zh'}
    assert reference('Text2QAAnswerAlignmentPrompt')['kind'] == 'operator_default'
    assert reference('AlpagasusPrompt')['parameters']['constructor'] == {'dimension': 'quality'}
    answer = next(r for r in personal if r['id'] == 'mm-answer-v1')
    use = next(ref for ref in answer['references'] if ref['pipeline_source'] == 'user')
    assert use['parameters']['inputs'] == {'image': 'image', 'question': 'question'}
    assert use['bindings'] == {'question': 'question'}
    personal_schemas = [r for r in service.schemas()['resources'] if r['personal']]
    assert {r['id'] for r in personal_schemas} == {schemas.list_all()[0]['id'], 'builtin-mm-qa-v1'}
    check = next(r for r in personal_schemas if r['id'] == 'builtin-mm-qa-v1')
    assert check['readonly'] and check['references'][-1]['parameters']['output'] == 'validated'
    assert before == (own.store.path.read_bytes(), schemas.store.path.read_bytes(), store.path.read_bytes())


def test_explicit_override_suppresses_default_and_keeps_per_flow_parameters(catalog):
    service, _, _, prompt, _ = catalog
    mapping = {name: {'operator': [], 'description': '', 'primary_type': 'core_text',
               'parameter': {'init': [], 'build_prompt': []}, 'class_str': 'test.' + name}
               for name in ['KnowledgeCleanerPrompt', 'Text2MultiHopQAGeneratorPrompt']}
    service.c.prompt_registry.list_prompt_info = lambda: SimpleNamespace(model_dump=lambda: {'prompts': mapping})
    def flow(key, lang, override=False):
        init = [{'name': 'lang', 'value': lang}, {'name': 'api_key', 'value': 'secret-value'}]
        if override:
            init.append({'name': 'prompt_template', 'value': {'ref': 'user_prompt:' + prompt['id']}})
        return {'id': key, 'name': key, 'config': {'operators': [{'name': 'KBCTextCleaner', 'params': {'init': init}}]}}
    service.c.pipeline_registry.list_pipelines = lambda: [flow('en', 'en'), flow('zh', 'zh'), flow('override', 'zh', True)]
    result = service.prompts()
    cleaner = next(r for r in result['resources'] if r['id'] == 'KnowledgeCleanerPrompt')
    refs = [ref for ref in cleaner['references'] if ref['pipeline_source'] == 'user']
    assert {ref['pipeline_id'] for ref in refs} == {'pipeline:en', 'pipeline:zh'}
    assert {ref['parameters']['constructor']['lang'] for ref in refs} == {'en', 'zh'}
    assert all(ref['parameters']['operator']['init']['api_key'] == '[已隐藏]' for ref in refs)
    assert 'secret-value' not in json.dumps(result)
    builtin_qa = next(r for r in result['resources'] if r['id'] == 'Text2MultiHopQAGeneratorPrompt')
    assert not builtin_qa['personal']  # Only used by the system template.


def test_hidden_prompts_leave_registry_and_pipeline_references_intact(catalog, monkeypatch):
    from app.services import resource_catalog
    service, own, _, prompt, _ = catalog
    before = own.store.path.read_bytes()
    monkeypatch.setattr(resource_catalog, 'visibility_settings', lambda: {'hidden_prompt_ids': [prompt['id']]})
    assert all(r['id'] != prompt['id'] for r in service.prompts()['resources'])
    assert own.get(prompt['id']) == prompt
    assert own.store.path.read_bytes() == before
