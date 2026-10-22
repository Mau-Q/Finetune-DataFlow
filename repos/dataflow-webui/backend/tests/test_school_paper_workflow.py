import importlib.util
import json
from pathlib import Path
import threading
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from app.services.paper_multitask import definition, install, ID
from app.services.auto_collection import pipeline_contract
from app.services.user_prompt_registry import UserPromptRegistry
from app.services.json_schema_manager import JsonSchemaManager

ROOT = Path(__file__).resolve().parents[4]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'deploy/school'/f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_portable_template_and_idempotent_install(tmp_path, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, 'BASE_DIR', str(tmp_path))
    data = {'pipelines': {}}
    c = SimpleNamespace(pipeline_registry=SimpleNamespace(_read=lambda: data, _write=lambda d: data.update(d)),
                        user_prompt_registry=UserPromptRegistry(tmp_path/'prompts.json'),
                        json_schema_manager=JsonSchemaManager(tmp_path/'schemas.json'))
    install(c)
    config = data['pipelines'][ID]['config']
    assert len(config['operators']) == 12
    assert config['input_dataset']['id'] == ''
    assert 'simple_training' not in config['execution_options']
    assert pipeline_contract(config) == {'modality': 'text', 'training_type': 'sft'}
    assert [p['value'] for op in config['operators'] for p in op['params']['init'] if p['name'] == 'llm_serving'] == [None, None]
    data['pipelines'][ID]['name'] = 'User edit'
    install(c)
    assert data['pipelines'][ID]['name'] == 'User edit'
    assert len(c.user_prompt_registry.list_all()) == 2


def test_parser_bridge_bytes_only_authenticated_protocol(tmp_path):
    bridge, client = load('mineru_bridge'), load('mineru_client')
    token = tmp_path/'token'
    token.write_text('isolated-test-token')
    source = tmp_path/'source.pdf'
    source.write_bytes(b'%PDF-1.7\nfixture')
    seen = []
    def parser(root, prior, script, content):
        seen.append(content)
        return b'fixture-zip'
    server = bridge.serve(tmp_path, tmp_path, tmp_path, token.read_text(), host='127.0.0.1', port=0, parser=parser)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = 'http://127.0.0.1:'+str(server.server_address[1])
    try:
        with pytest.raises(HTTPError):
            urlopen(base+'/health')
        client.parse(source, tmp_path/'parsed.zip', token, base)
        assert seen == [source.read_bytes()]
        assert (tmp_path/'parsed.zip').read_bytes() == b'fixture-zip'
        with pytest.raises(HTTPError):
            urlopen(Request(base+'/parse', data=b'not pdf', headers={'Authorization':'Bearer '+token.read_text()}))
    finally:
        server.shutdown();server.server_close();thread.join()


def test_pdf_preflight_template_supports_shallow_server_workspace(monkeypatch):
    from app.core.config import settings
    from app.services.text_generation import template
    monkeypatch.setattr(settings, 'BASE_DIR', '/state/workspace')
    assert len(template()['config']['operators']) == 13


def test_compile_tracks_pandas_declared_columns_without_running(tmp_path):
    from app.services.pipeline_compile_check import compile_check
    from dataflow.core import OperatorABC
    from dataflow.operators.core_text import PandasOperator
    from dataflow.utils.storage import FileStorage
    source = tmp_path/'source.jsonl'
    source.write_text('{"source":"file.pdf"}\n')
    storage = FileStorage(first_entry_file_name=str(source), cache_path=str(tmp_path/'cache'), cache_type='jsonl')
    def forbidden(df):
        raise AssertionError('Compile must never execute user transforms')
    class Consumer(OperatorABC):
        def run(self, storage, input_key):
            raise AssertionError('Compile must never execute consumers')
    params = {'output_key':['source_path','document_id']}
    producer = PandasOperator([forbidden])
    assert compile_check([(producer, params, 'PandasOperator', '0'),
                          (Consumer(), {'input_key':'source_path'}, 'Consumer','1')], storage)['ok']
    assert params == {'output_key':['source_path','document_id']}
    result = compile_check([(producer, params, 'PandasOperator','0'),
                            (Consumer(), {'input_key':'missing'}, 'Consumer','1')], storage)
    assert not result['ok'] and not result['skipped']


def test_execution_timestamps_have_explicit_timezone(tmp_path):
    from datetime import datetime
    from app.services.task_registry import TaskRegistry
    registry = TaskRegistry(path=str(tmp_path/'tasks.json'))
    task = registry.create({'dataset_id':'time-fixture'})
    started = registry.update(task['id'], {'status':'running'})
    completed = registry.update(task['id'], {'status':'completed'})
    for value in [task['created_at'], started['started_at'], completed['finished_at'], registry.get_current_time()]:
        assert datetime.fromisoformat(value).utcoffset() is not None


def test_warm_parser_reuses_owned_model_for_multiple_pdfs(tmp_path, monkeypatch):
    import hashlib
    bridge = load('mineru_bridge')
    script = tmp_path/'job.py';script.write_text('# frozen model job')
    parser = bridge.WarmParser(tmp_path/'bridge', tmp_path, script)
    engine = parser.root/'engines'/'existing';engine.mkdir()
    (engine/'ready.json').write_text('{}');(engine/'lease').touch()
    parser.state.write_text(json.dumps({'container':'owned-model','engine':str(engine),'gpu':'GPU-fixture',
        'script_sha256':hashlib.sha256(script.read_bytes()).hexdigest()}))
    calls = []
    actual_owner = parser.owner
    def command(args, **kwargs):
        calls.append(args)
        if args[:2] == ['docker','inspect']:
            return SimpleNamespace(returncode=0, stdout=json.dumps([{
                'Config':{'Labels':{'dataflow.mineru.owner':actual_owner}}, 'State':{'Running':True}}]))
        assert args[:3] == ['docker','exec','owned-model']
        (parser.root/'jobs'/Path(args[-1]).parent.name/'parsed.zip').write_bytes(b'parsed-archive')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(bridge.subprocess, 'run', command)
    monkeypatch.setattr(bridge, 'choose_gpu', lambda: pytest.fail('Must reuse the already loaded GPU model'))
    for content in [b'%PDF-first',b'%PDF-second']:
        assert parser(parser.root, tmp_path, script, content) == b'parsed-archive'
    receipts = [json.loads(p.read_text()) for p in (parser.root/'jobs').glob('*/receipt.json')]
    assert len(receipts) == 2 and all(r['reused_model'] for r in receipts)
    assert all(c[1] in {'inspect','exec'} for c in calls)
    parser.owner = 'different-owner'
    with pytest.raises(RuntimeError, match='different owner'):
        parser.running('owned-model')
