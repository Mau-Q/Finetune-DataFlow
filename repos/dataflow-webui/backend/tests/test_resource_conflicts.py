from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from app.core.container import container
from app.services.resource_store import ResourceConflictError
from app.services.user_prompt_registry import UserPromptRegistry
from app.services.json_schema_manager import JsonSchemaManager
from app.api.v1.endpoints import prompts, json_schemas
from app.api.v1.handlers import install_exception_handlers


@pytest.fixture(params=['prompt','schema'])
def resource(request,tmp_path):
    if request.param=='prompt':
        registry=UserPromptRegistry(tmp_path/'prompts.json');rec=registry.create('original','','Question {q}',[],{'q':'test'})
    else:
        registry=JsonSchemaManager(tmp_path/'schemas.json');rec=registry.create('original','','{"type":"string"}','"test"')
    return request.param,registry,rec


def test_stale_save_rejected_without_modifying_new_content(resource):
    _,registry,original=resource
    current=registry.update(original['id'],name='new version',expected_updated_at=original['updated_at'])
    before=registry.store.path.read_bytes()
    with pytest.raises(ResourceConflictError):
        registry.update(original['id'],name='stale editor',expected_updated_at=original['updated_at'])
    assert registry.store.path.read_bytes()==before
    assert registry.get(original['id'])['updated_at']==current['updated_at']
    assert registry.update(original['id'],name='old client without precondition')['name']=='old client without precondition'


def test_revision_advances_when_clock_does_not(resource, monkeypatch):
    from datetime import datetime, timedelta
    from app.services import resource_store
    _, registry, original = resource
    before = datetime.fromisoformat(original['updated_at'])
    class FrozenClock(datetime):
        @classmethod
        def now(cls, tz):
            return before - timedelta(seconds=1)
    monkeypatch.setattr(resource_store, 'datetime', FrozenClock)
    current = registry.update(original['id'], name='new', expected_updated_at=original['updated_at'])
    assert datetime.fromisoformat(current['updated_at']) > before
    with pytest.raises(ResourceConflictError):
        registry.update(original['id'], name='stale', expected_updated_at=original['updated_at'])


def test_simultaneous_editors_only_one_revision_wins(resource):
    _,registry,original=resource
    def save(i):
        try:return registry.update(original['id'],name=f'editor-{i}',expected_updated_at=original['updated_at'])
        except ResourceConflictError:return None
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(save,range(4)))
    assert sum(r is not None for r in results)==1


def test_conflict_api_reports_409_with_current_resource_preserved(resource,monkeypatch):
    kind,registry,rec=resource
    app=FastAPI();install_exception_handlers(app)
    if kind=='prompt':
        monkeypatch.setattr(container,'user_prompt_registry',registry);app.include_router(prompts.router,prefix='/prompts');path='/prompts/user/'+rec['id']
    else:
        monkeypatch.setattr(container,'json_schema_manager',registry);app.include_router(json_schemas.router,prefix='/schemas');path='/schemas/'+rec['id']
    with TestClient(app) as client:
        assert client.put(path,json={'name':'first','expected_updated_at':rec['updated_at']}).json()['success']
        result=client.put(path,json={'name':'second','expected_updated_at':rec['updated_at']}).json()
        assert not result['success'] and result['meta']['http_status']==409
        assert registry.get(rec['id'])['name']=='first'
