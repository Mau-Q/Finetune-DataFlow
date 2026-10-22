import copy
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.core.config import settings
from app.api.v1.endpoints import tasks
from app.api.v1.handlers import install_exception_handlers
from app.services import result_storage as storage, local_source_picker
from app.services.data_library import LibraryError, _json_bytes, _hash, DataLibrary
from app.services.task_artifacts import with_task_artifacts
from app.services.task_results import TaskResults
from app.services.task_registry import TaskRegistry


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings,'BASE_DIR',str(tmp_path))
    monkeypatch.setattr(settings,'CACHE_DIR',str(tmp_path/'cache'))
    monkeypatch.setattr(settings,'RESOURCE_DIR','data')
    return tmp_path


def test_preferences_remember_output_without_changing_language(isolated):
    pref=isolated/'data'/'user_preferences.json';pref.parent.mkdir();pref.write_text('{"language":"cn","theme":"dark"}')
    assert storage.preferences()['output_root']==str(isolated/'results')
    saved=storage.save_preferences(str(isolated/'my-results'))
    assert storage.preferences()==saved and pref.read_text()=='{"language":"cn","theme":"dark"}'


def test_relative_path_and_file_rejected(isolated):
    with pytest.raises(LibraryError,match='绝对目录'):storage.check_root('relative/output')
    file=isolated/'file';file.write_text('existing')
    with pytest.raises(LibraryError,match='不可写'):storage.check_root(str(file))
    assert file.read_text()=='existing'


def test_task_directories_are_unique_and_do_not_overwrite(isolated, monkeypatch):
    from datetime import datetime
    monkeypatch.setattr(storage, "datetime", SimpleNamespace(now=lambda: datetime(2026, 10, 19, 20, 0, 0)))
    root=isolated/'results'
    first={};second={}
    path=storage.prepare(first,'task-a','文本 SFT')
    other=storage.prepare(second,'task-b','文本 SFT')
    assert path!=other and Path(path).parent==root and '文本_SFT_' in Path(path).name
    (Path(path)/'keep.txt').write_text('keep')
    with pytest.raises(LibraryError):storage.prepare({},'task-a','文本 SFT')
    assert (Path(path)/'keep.txt').read_text()=='keep'


def test_non_capture_run_persists_final_and_registry_points_to_owned_files(isolated):
    config={'operators':[{'name':'Test'}],'execution_options':{'output_root':str(isolated/'out')}}
    directory=Path(storage.prepare(config,'task-a'))
    cache=isolated/'cache'/'last.jsonl';cache.parent.mkdir();content=_json_bytes({'instruction':'Q','input':'','output':'A'})+b'\n';cache.write_bytes(content)
    @with_task_artifacts
    def run(pipeline_config,task_id):
        return {'task_id':task_id,'status':'completed','output':{'execution_results':[{'index':0,'file_path':str(cache)}]},'logs':['done']}
    result=run(config,'task-a')
    assert (directory/'final.jsonl').read_bytes()==content
    assert json.loads((directory/'logs.json').read_text())==['done']
    manifest=json.loads((directory/'manifest.json').read_text())
    assert manifest['task_id']=='task-a' and len(manifest['files'])==3
    assert all(_hash((directory/f['path']).read_bytes())==f['sha256'] for f in manifest['files'])
    assert Path(result['output']['execution_results'][0]['file_path']).parent==directory/'intermediate'
    cache.unlink()
    record=dict(result,pipeline_config=config)
    service=TaskResults(SimpleNamespace(data_library=DataLibrary(isolated/'data'/'library'),task_registry=SimpleNamespace(get=lambda _:record)))
    detail = service.detail('task-a')
    assert detail['available'] and detail['result_directory']==str(directory)
    assert detail['artifact']['path']==str(directory/'final.jsonl')


def test_storage_failure_exposed_without_hiding_execution_result(isolated):
    config={};directory=storage.prepare(config,'task-a')
    result={'task_id':'task-a','status':'completed','output':{},'logs':[]}
    result=storage.persist(config,result)
    assert result['status']=='completed' and 'storage_error' in result['output']


def test_registry_task_override_does_not_change_saved_source(isolated):
    config={'file_path':'test.py','operators':[],'execution_options':{'output_root':str(isolated/'out')}}
    original=copy.deepcopy(config)
    registry=TaskRegistry(str(isolated/'tasks.json'))
    tid,frozen,record=registry.start_execution(config=config)
    assert config==original and 'result_directory' in frozen['execution_options']
    assert Path(frozen['execution_options']['result_directory']).is_dir()
    assert registry.get(tid)['pipeline_source_config']==original


def test_native_picker_uses_directory_only_and_cancellation(monkeypatch):
    monkeypatch.setattr(local_source_picker.sys,'platform','darwin')
    captured=[]
    def fake(command,**kwargs):captured.append(command[-1]);return SimpleNamespace(stdout='[]')
    monkeypatch.setattr(local_source_picker.subprocess,'run',fake)
    assert local_source_picker.pick_paths(directories_only=True)==[]
    assert 'canChooseFiles = false' in captured[0] and 'allowsMultipleSelection = false' in captured[0]
    assert local_source_picker.pick_paths()==[] and 'canChooseFiles = true' in captured[1]


def test_storage_api_keeps_all_writes_isolated(isolated,monkeypatch):
    app=FastAPI();app.include_router(tasks.router,prefix='/api/v1/tasks');install_exception_handlers(app)
    monkeypatch.setattr(local_source_picker,'pick_paths',lambda **kwargs:[])
    with TestClient(app) as client:
        url='/api/v1/tasks/result-storage'
        assert client.get(url).json()['data']['output_root']==str(isolated/'results')
        assert client.post(url+'/choose').json()['data']['cancelled']
        assert client.put(url,json={'output_root':str(isolated/'new-default')}).json()['success']
        assert not client.post(url+'/check',json={'output_root':'relative'}).json()['success']
        assert client.get(url).json()['data']['output_root']==str(isolated/'new-default')
