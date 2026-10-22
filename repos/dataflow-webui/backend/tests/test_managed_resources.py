"""M2 resource contracts; fixtures never call a model or use live metadata."""
import asyncio
import copy
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.container import container
from app.services.user_prompt_registry import UserPromptRegistry, render_template
from app.services.json_schema_manager import JsonSchemaManager, validate_schema
from app.services.resource_resolution import (
    resolve_pipeline_resources, ResourceReferenceError, instantiate_prompt, content_hash,
)
from app.services.task_registry import TaskRegistry


@pytest.fixture
def resources(tmp_path, monkeypatch):
    prompts = UserPromptRegistry(tmp_path / 'prompts.json')
    schemas = JsonSchemaManager(tmp_path / 'schemas.json')
    details = {
        'name': 'FormatStrPromptedGenerator', 'allowed_prompts': ['FormatStrPrompt'],
        'parameter': {'init': [{'name': n} for n in ('prompt_template', 'json_schema', 'llm_serving', 'system_prompt')],
                      'run': [{'name': 'storage'}, {'name': 'output_key'}, {'name': 'input_keys', 'kind': 'VAR_KEYWORD'}]},
    }
    monkeypatch.setattr(container, 'user_prompt_registry', prompts)
    monkeypatch.setattr(container, 'json_schema_manager', schemas)
    monkeypatch.setattr(container, 'operator_registry', SimpleNamespace(get_op_details=lambda name: details))
    prompt = prompts.create('shared', '', '问题：{question}\n输出 {"answer":{"value":"文本"}}', [], {})
    schema = schemas.create('answer', '', '{"type":"object","required":["answer"],"properties":{"answer":{"type":"string","minLength":2}}}', '{"answer":"ok"}')
    config = {'file_path': '', 'input_dataset': {'id': 'source'}, 'operators': [{
        'name': 'FormatStrPromptedGenerator', 'params': {
            'init': [{'name': 'prompt_template', 'value': {'ref': 'user_prompt:' + prompt['id'], 'bindings': {'question': 'text'}}},
                     {'name': 'json_schema', 'value': 'schema_ref:' + schema['id']}],
            'run': [{'name': 'output_key', 'value': 'answer'}],
        },
    }]}
    return prompts, schemas, prompt, schema, config


@pytest.mark.parametrize('text,variables,expected,missing', [
    ('Q {q} {q}', {'q': 'hello'}, 'Q hello hello', []),
    ('{"answer":{"text":"example"}} {q}', {'q': 'x'}, '{"answer":{"text":"example"}} x', []),
    ('{{literal}} {q}', {'q': '{other}'}, '{literal} {other}', []),
    ('JSON {"a": 1} {q}', {}, 'JSON {"a": 1} {q}', ['q']),
    ('{{"a": "fixed"}} {q}', {'q': 'x'}, '{"a": "fixed"} x', []),
])
def test_render_json_braces_missing_and_nonrecursive_substitution(text, variables, expected, missing):
    rendered = render_template(text, variables)
    assert rendered['rendered'] == expected
    assert rendered['missing'] == missing
    assert 'literal' not in rendered['placeholders']


@pytest.mark.parametrize('schema,example', [
    ('{"type":"nonsense"}', ''),
    ('{"required":"answer"}', ''),
    ('[]', ''),
    ('{"type":"integer","minimum":3}', '2'),
    ('{"type":"string","pattern":"^a"}', '"xyz"'),
    ('{"type":"object","additionalProperties":false}', '{"x":1}'),
    ('false', 'null'),
    ('{"$ref":"https://example.org/schema"}', ''),
    ('{"$ref":"#/$defs/missing"}', ''),
    ('{"type":"number"}', 'NaN'),
    ('{"$schema":"https://example.org/unsupported"}', ''),
])
def test_standard_schema_rejects_invalid_definitions_and_examples(schema, example):
    with pytest.raises(ValueError):
        validate_schema(schema, example)


@pytest.mark.parametrize('schema,example', [
    ('{"$schema":"http://json-schema.org/draft-07/schema#","type":"integer","minimum":1}', '2'),
    ('{"$schema":"https://json-schema.org/draft/2019-09/schema","type":"integer"}', '2'),
    ('{"$defs":{"x":{"type":"string"}},"$ref":"#/$defs/x"}', '"ok"'),
    ('{"oneOf":[{"type":"integer"},{"type":"string"}]}', '1'),
    ('true', '{"anything":true}'),
    ('false', ''),
])
def test_supported_dialects_and_internal_refs(schema, example):
    validate_schema(schema, example)


def test_invalid_updates_are_atomic_and_registry_instances_see_current_disk(resources, tmp_path):
    prompts, schemas, prompt, schema, _ = resources
    before = prompts.get(prompt['id'])
    with pytest.raises(ValueError):
        prompts.update(prompt['id'], name='changed', template='')
    assert prompts.get(prompt['id']) == before
    before = schemas.get(schema['id'])
    with pytest.raises(ValueError):
        schemas.update(schema['id'], schema='{"type":"integer"}')  # old example incompatible
    assert schemas.get(schema['id']) == before
    second = UserPromptRegistry(tmp_path / 'prompts.json')
    second.update(prompt['id'], template='new {question}')
    assert prompts.get(prompt['id'])['template'] == 'new {question}'
    detached = prompts.get(prompt['id'])
    detached['template'] = 'accidental mutation'
    assert second.get(prompt['id'])['template'] == 'new {question}'


def test_concurrent_crud_does_not_lose_records(tmp_path):
    def create(i):
        return UserPromptRegistry(tmp_path / 'shared.json').create(f'p{i}', '', '{q}')
    with ThreadPoolExecutor(max_workers=6) as pool:
        records = list(pool.map(create, range(20)))
    assert len(records) == len(UserPromptRegistry(tmp_path / 'shared.json').list_all()) == 20


def test_atomic_replace_failure_preserves_old_file(resources, monkeypatch):
    import app.services.resource_store as module
    prompts, _, prompt, _, _ = resources
    before = prompts.store.path.read_bytes()
    monkeypatch.setattr(module.os, 'replace', lambda *_: (_ for _ in ()).throw(OSError('disk error')))
    with pytest.raises(OSError):
        prompts.update(prompt['id'], template='changed {question}')
    assert prompts.store.path.read_bytes() == before
    assert not list(prompts.store.path.parent.glob('.pending-*'))


def test_corrupt_metadata_is_never_silently_reset(tmp_path):
    path = tmp_path / 'broken.json'
    path.write_text('{broken')
    with pytest.raises(ValueError):
        UserPromptRegistry(path)
    with pytest.raises(ValueError):
        JsonSchemaManager(path)
    assert path.read_text() == '{broken'


def test_shared_resource_references_freeze_and_survive_edit_delete(resources, tmp_path):
    prompts, schemas, prompt, schema, config = resources
    original = copy.deepcopy(config)
    tasks = TaskRegistry(str(tmp_path / 'tasks.json'))
    one, frozen_one, _ = tasks.start_execution(config=config)
    two, frozen_two, _ = tasks.start_execution(config=copy.deepcopy(config))
    assert frozen_one == frozen_two
    assert config == original
    snapshots = tasks.get_execution_status(one)['resource_snapshots']
    assert len(snapshots) == 2
    assert snapshots[0]['sha256'] == content_hash(snapshots[0]['content'])
    prompts.update(prompt['id'], template='changed {question}')
    schemas.update(schema['id'], schema='{"type":"object"}')
    _, future = resolve_pipeline_resources(config)
    assert future[0]['sha256'] != snapshots[0]['sha256']
    assert future[1]['sha256'] != snapshots[1]['sha256']
    prompts.delete(prompt['id'])
    schemas.delete(schema['id'])
    assert tasks.get_execution_status(one)['resource_snapshots'] == snapshots
    assert tasks.get_execution_status(two)['pipeline_config'] == frozen_one
    resolved, no_lookup = resolve_pipeline_resources(frozen_one)
    assert no_lookup == []
    assert resolved == frozen_one
    prompt_value = frozen_one['operators'][0]['params']['init'][0]['value']
    assert instantiate_prompt(prompt_value).build_prompt({'question'}, question='hello') == '问题：hello\n输出 {"answer":{"value":"文本"}}'
    with pytest.raises(ResourceReferenceError, match='不存在'):
        tasks.start_execution(config=config)
    assert len(tasks.list_executions()) == 2


@pytest.mark.parametrize('mutation,match', [
    (lambda c: c['operators'][0]['params']['init'][0]['value'].update(bindings={}), '缺少变量'),
    (lambda c: c['operators'][0]['params']['init'][0]['value'].update(bindings={'question':'text','output_key':'x'}), '不能使用'),
    (lambda c: c['operators'][0].update(name='Text2MultiHopQAGenerator'), '必须包含变量'),
    (lambda c: c['operators'][0]['params']['init'][1].update(value='schema_ref:missing'), '不存在'),
    (lambda c: c['operators'][0]['params']['init'][1].update(name='system_prompt'), '不是声明'),
    (lambda c: c['operators'][0]['params']['init'][1].update(value='{"type":"invalid"}'), 'Schema'),
])
def test_bad_references_block_before_queuing(resources, tmp_path, mutation, match):
    config = resources[-1]
    mutation(config)
    tasks = TaskRegistry(str(tmp_path / 'tasks.json'))
    with pytest.raises(ResourceReferenceError, match=match):
        tasks.start_execution(config=config)
    assert tasks.list_executions() == []


def test_allowed_operator_restriction(resources):
    prompts, _, prompt, _, config = resources
    prompts.update(prompt['id'], allowed_operators=['AnotherOperator'])
    with pytest.raises(ResourceReferenceError, match='未允许'):
        resolve_pipeline_resources(config)


def test_string_refs_and_legacy_inline_and_builtin_unchanged(resources):
    config = resources[-1]
    config['operators'][0]['params']['init'][0]['value'] = 'user_prompt:' + resources[2]['id']
    config['operators'][0]['params']['run'].append({'name':'input_keys','kind':'VAR_KEYWORD','value':[{'name':'question','value':'text'}]})
    frozen, records = resolve_pipeline_resources(config)
    assert len(records) == 2
    builtin = {'input_dataset':'source', 'operators':[{'name':'OtherOperator', 'params':{'prompt_template':{'cls_name':'FormatStrPrompt', 'params':[{'name':'f_str_template','value':'legacy {q}'}]}, 'input_key':'text'}}]}
    assert resolve_pipeline_resources(builtin) == (builtin, [])
    value = builtin['operators'][0]['params']['prompt_template']
    from dataflow.prompts.core_text import FormatStrPrompt  # eager registration, as in app startup
    assert instantiate_prompt(value).build_prompt({'q'}, q='x') == 'legacy x'


def test_resource_crud_api_uses_validation_envelope(resources):
    from app.api.v1.endpoints import prompts, json_schemas
    from app.api.v1.handlers import install_exception_handlers
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(prompts.router, prefix='/prompts')
    app.include_router(json_schemas.router, prefix='/schemas')
    with TestClient(app) as client:
        assert client.get('/prompts/user').json()['success']
        assert client.get('/schemas').json()['success']
        assert not client.post('/prompts/user', json={'name':'bad','template':''}).json()['success']
        bad = client.post('/schemas', json={'name':'bad','schema':'{"type":"bad"}'}).json()
        assert not bad['success'] and bad['meta']['http_status'] == 422
        bad = client.post('/schemas/validate', json={'name':'bad','schema':'{"minimum":5}', 'example':'2'}).json()
        assert not bad['success']
        preview = client.post('/prompts/user/preview', json={'template':'{"a":1} {q}', 'variables':{}}).json()
        assert preview['data']['missing'] == ['q']
        assert preview['data']['rendered'] == '{"a":1} {q}'


def test_async_submission_uses_frozen_content_and_rejects_missing_before_submit(resources, tmp_path, monkeypatch):
    from app.services.dataflow_engine import DataFlowEngine
    from app.services.ray_pipeline_executor import ray_executor
    _, _, _, _, config = resources
    submitted = []
    async def submit(**kwargs):
        submitted.append(kwargs)
    monkeypatch.setattr(ray_executor, 'submit_execution', submit)
    monkeypatch.setattr(DataFlowEngine, 'decode_hashed_arguments', lambda *_: {})
    tasks = TaskRegistry(str(tmp_path / 'tasks.json'))
    result = asyncio.run(tasks.start_execution_async(config=config))
    assert submitted[0]['pipeline_config'] == tasks.get_execution_status(result['task_id'])['pipeline_config']
    resources[0].delete(resources[2]['id'])
    with pytest.raises(ResourceReferenceError):
        asyncio.run(tasks.start_execution_async(config=config))
    assert len(submitted) == len(tasks.list_executions()) == 1


@pytest.mark.parametrize('path', ['sync', 'ray'])
def test_both_real_executors_render_frozen_prompt_with_list_bindings(resources, tmp_path, monkeypatch, path):
    """Execute the production loops with an actual generator and a local fake serving.

    No Ray cluster, external API, or live task/input is used.
    """
    from app.services import dataflow_engine, ray_pipeline_executor
    from app.core.config import settings
    from dataflow.operators.core_text import FormatStrPromptedGenerator
    from dataflow.utils.registry import OPERATOR_REGISTRY
    seen = []
    class FixtureServing:
        def generate_from_input(self, user_inputs, system_prompt, json_schema):
            seen.extend(user_inputs)
            assert json_schema['required'] == ['answer']
            return ['offline answer'] * len(user_inputs)
    # Keep the actual core operator and prompt contract; inject only the serving.
    class FixtureGenerator(FormatStrPromptedGenerator):
        def __init__(self, prompt_template, json_schema=None):
            super().__init__(FixtureServing(), prompt_template=prompt_template, json_schema=json_schema)
    monkeypatch.setattr(OPERATOR_REGISTRY, '_get_all', lambda: None)
    original_get = OPERATOR_REGISTRY.get
    monkeypatch.setattr(OPERATOR_REGISTRY, 'get', lambda name: FixtureGenerator if name == 'FormatStrPromptedGenerator' else original_get(name))
    # These direct executor calls bypass application startup initialization.
    # Keep their required working directory local to the test on clean clones.
    core_dir = tmp_path / 'core'
    (core_dir / 'api_pipelines').mkdir(parents=True)
    monkeypatch.setattr(settings, 'DATAFLOW_CORE_DIR', str(core_dir))
    monkeypatch.chdir(tmp_path)
    input_file = tmp_path / 'input.jsonl'
    input_file.write_text('{"text":"hello"}\n')
    monkeypatch.setattr(container, 'dataset_registry', SimpleNamespace(get=lambda _: {'root':str(input_file)}))
    monkeypatch.setattr(settings, 'CACHE_DIR', str(tmp_path / 'cache'))
    tasks = TaskRegistry(str(tmp_path / 'tasks.json'))
    task_id, frozen, _ = tasks.start_execution(config=resources[-1])
    # The live resource no longer exists by the time the worker begins.
    resources[0].delete(resources[2]['id'])
    resources[1].delete(resources[3]['id'])
    if path == 'sync':
        result = dataflow_engine.DataFlowEngine().run(frozen, task_id, execution_path=tasks.path)
    else:
        runtime = {'storage': {'first_entry_file_name': str(input_file), 'cache_path':str(tmp_path/'ray-cache'),
                              'file_name_prefix':'step', 'cache_type':'jsonl'},
                   'serving_map':{}, 'embedding_serving_map':{}, 'db_manager_map':{}}
        result = ray_pipeline_executor.dataflow_pipeline_execute(frozen, runtime, task_id, tasks.path)
    assert result['status'] == 'completed', result['logs']
    assert seen == ['问题：hello\n输出 {"answer":{"value":"文本"}}']
    assert tasks.get_execution_status(task_id)['resource_snapshots'][0]['content']['template'].startswith('问题')


def test_standard_schema_const_data_is_not_mistaken_for_a_ref():
    validate_schema('{"const":{"$ref":"https://example.org/literal"}}', '{"$ref":"https://example.org/literal"}')


def test_static_field_validation_includes_managed_bindings(resources, tmp_path, monkeypatch):
    from app.services.pipeline_registry import PipelineRegistry
    monkeypatch.setattr(container, 'dataset_registry', SimpleNamespace(get=lambda _: {'id': 'source'}, get_columns=lambda _: ['text']))
    monkeypatch.setattr(container, 'serving_registry', SimpleNamespace(_get=lambda _: None))
    registry = PipelineRegistry.__new__(PipelineRegistry)
    config = resources[-1]
    config['operators'][0]['params']['init'][0]['value']['bindings']['question'] = 'missing_column'
    result = registry.validate_pipeline_config(config)
    assert any(issue.code == 'missing_input_field' and issue.field_name == 'missing_column' for issue in result.errors)


def test_invalid_dialect_type_is_a_validation_error():
    with pytest.raises(ValueError, match='字符串'):
        validate_schema('{"$schema":123}')


def test_nested_schema_id_and_internal_anchor():
    validate_schema('{"$defs":{"node":{"$id":"https://example.org/local","$defs":{"x":{"type":"string"}},"$ref":"#/$defs/x"}}}')


def test_duplicate_run_bindings_block_submission(resources):
    config = resources[-1]
    config['operators'][0]['params']['init'][0]['value'] = 'user_prompt:' + resources[2]['id']
    config['operators'][0]['params']['run'].append({'name':'input_keys','kind':'VAR_KEYWORD','value':[
        {'name':'question','value':'text'}, {'name':'question','value':'another'},
    ]})
    with pytest.raises(ResourceReferenceError, match='重复'):
        resolve_pipeline_resources(config)


def test_pipeline_registry_persists_shared_refs_in_two_configs(resources, tmp_path, monkeypatch):
    from app.services.pipeline_registry import PipelineRegistry
    from app.services.dataset_registry import DatasetRegistry
    datasets = DatasetRegistry(path=str(tmp_path/'inputs.yaml'), scan=False)
    source = tmp_path/'sample.jsonl'
    source.write_text('{"text":"sample"}\n')
    dataset = datasets.add_or_update({'name':'sample','root':str(source),'pipeline':'fixture','meta':{}})
    monkeypatch.setattr(container, 'dataset_registry', datasets)
    registry = PipelineRegistry.__new__(PipelineRegistry)
    registry.path = str(tmp_path/'pipelines.json')
    registry._write({'pipelines':{}})
    config = resources[-1]
    config['input_dataset'] = {'id':dataset['id']}
    first = registry.create_pipeline({'name':'one','config':copy.deepcopy(config)})
    second = registry.create_pipeline({'name':'two','config':copy.deepcopy(config)})
    for saved in (first, second):
        reopened = registry.get_pipeline(saved['id'])
        params = reopened['config']['operators'][0]['params']['init']
        value = next(p['value'] for p in params if p['name']=='prompt_template')
        assert value == config['operators'][0]['params']['init'][0]['value']
        assert 'resource_template' not in json.dumps(reopened)
        assert resolve_pipeline_resources(reopened['config'])[1][0]['ref'] == 'user_prompt:' + resources[2]['id']


def test_launch_endpoints_expose_snapshot_and_missing_ref_is_not_queued(resources, tmp_path, monkeypatch):
    from app.api.v1.endpoints import tasks as endpoints
    from app.api.v1.handlers import install_exception_handlers
    tasks = TaskRegistry(str(tmp_path/'tasks.json'))
    config = resources[-1]
    monkeypatch.setattr(container, 'task_registry', tasks)
    monkeypatch.setattr(container, 'pipeline_registry', SimpleNamespace(get_pipeline=lambda _: {'id':'pipeline','config':config}))
    seen = []
    def run(frozen, task_id, execution_path):
        seen.append(copy.deepcopy(frozen))
        return {'task_id':task_id,'status':'completed','output':{},'logs':[]}
    monkeypatch.setattr(endpoints.dataflow_engine, 'run', run)
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(endpoints.router, prefix='/tasks')
    with TestClient(app) as client:
        response = client.post('/tasks/execute?pipeline_id=pipeline').json()
        assert response['success'] and len(response['data']['resource_snapshots']) == 2
        assert response['data']['pipeline_config'] == seen[0]
        resources[0].delete(resources[2]['id'])
        for url in ('/tasks/execute?pipeline_id=pipeline', '/tasks/execute-async?pipeline_id=pipeline'):
            rejected = client.post(url).json()
            assert not rejected['success'] and rejected['meta']['http_status'] == 422
        assert len(tasks.list_executions()) == len(seen) == 1


def test_schema_slash_routes_work_before_static_ui_mount(resources, tmp_path):
    from fastapi.staticfiles import StaticFiles
    from app.api.v1.endpoints import json_schemas
    from app.api.v1.handlers import install_exception_handlers
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(json_schemas.router, prefix='/api/v1/json_schemas')
    app.mount('/', StaticFiles(directory=tmp_path, html=True))
    with TestClient(app) as client:
        for suffix in ('', '/'):
            created = client.post('/api/v1/json_schemas'+suffix, json={'name':'slash fixture', 'schema':'{"type":"string"}'}).json()
            assert created['success']
            assert client.get('/api/v1/json_schemas'+suffix).json()['success']


def test_resource_like_text_inside_content_is_literal_not_a_nested_reference(resources):
    prompts, schemas, prompt, schema, config = resources
    prompts.update(prompt['id'], template='user_prompt:literal {question}')
    schemas.update(schema['id'], schema='{"type":"string","const":"schema_ref:literal"}', example='"schema_ref:literal"')
    frozen, snapshots = resolve_pipeline_resources(config)
    prompts.delete(prompt['id'])
    schemas.delete(schema['id'])
    assert resolve_pipeline_resources(frozen) == (frozen, [])
    value = frozen['operators'][0]['params']['init'][0]['value']
    assert instantiate_prompt(value).build_prompt({'question'}, question='x') == 'user_prompt:literal x'
