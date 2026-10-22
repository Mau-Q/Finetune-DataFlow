import io
import pytest
from PIL import Image
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.core.container import container
from app.services.data_library import DataLibrary, LibraryError
from app.services.multimodal_templates import MultimodalTemplates, template
from app.services.user_prompt_registry import UserPromptRegistry
from app.services.json_schema_manager import JsonSchemaManager
from app.schemas.data_library import DraftCreate
from app.api.v1.endpoints.multimodal import router


@pytest.fixture
def mm(tmp_path, monkeypatch):
    lib=DataLibrary(tmp_path/'library')
    monkeypatch.setattr(container,'data_library',lib)
    monkeypatch.setattr(container,'user_prompt_registry',UserPromptRegistry(tmp_path/'prompts.json'))
    monkeypatch.setattr(container,'json_schema_manager',JsonSchemaManager(tmp_path/'schemas.json'))
    # Any attempt to touch the core engine/task registry fails this fixture.
    monkeypatch.setattr(container,'task_registry',None)
    monkeypatch.setattr(container,'operator_registry',None)
    data=io.BytesIO();Image.new('RGB',(2,2)).save(data,format='PNG')
    image=lib.add_material('image.png',data.getvalue(),{'name':'Image'})
    draft=lib.create_draft(DraftCreate(name='VQA',modality='image_text'))
    config=template()['config'];config['material_ids']=[image['id']];config['draft_id']=draft['id']
    return MultimodalTemplates(),config,lib


def test_roundtrip_and_service_empty_draft(mm):
    service,config,lib=mm
    config['max_workers']=3;config['steps'][0]['x']=80
    rec=service.save('VQA',config)
    assert MultimodalTemplates().get(rec['id'])['config']==config
    check=service.check(config)
    assert check['structure_valid'] and not check['ready']
    assert any('未配置视觉服务' in e for e in check['errors'])
    with pytest.raises(LibraryError,match='未配置视觉服务'):
        service.submit(rec['id'])
    assert len(lib.list_drafts())==1 and lib.get_draft(config['draft_id'])['row_count']==0


def test_no_service_or_inputs_required_for_save(mm):
    service,_,_=mm
    rec=service.save('Empty draft',template()['config'])
    assert service.check(rec['config'])['structure_valid']
    assert not service.check(rec['config'])['ready']


@pytest.mark.parametrize('change',[
 lambda c:c['steps'].reverse(),
 lambda c:c['steps'][1]['inputs'].update(question='missing'),
 lambda c:c['steps'][1]['inputs'].update(question='image'),
 lambda c:c['steps'][1].update(output='image'),
 lambda c:c['steps'][1].update(resource_ref='builtin:mm-question-v1'),
 lambda c:c['steps'][1].update(bindings={}),
 lambda c:c['steps'][0].update(kind='FakeCoreOperator'),
 lambda c:c.update(max_workers=0),
 lambda c:c['steps'][0].update(x=3000),
 lambda c:c.update(material_ids=c['material_ids']*2),
 lambda c:c.update(output_contract='text'),
 lambda c:c['steps'][3].update(output='other'),
 lambda c:c['steps'][2].update(bindings={'ignored':'image'}),
])
def test_invalid_save_is_atomic(mm,change):
    service,config,_=mm
    rec=service.save('Good',config);before=service.store.path.read_bytes()
    change(config)
    with pytest.raises(LibraryError):service.save('Bad',config,rec['id'])
    assert service.store.path.read_bytes()==before


def test_renamed_fields_and_correct_dependencies(mm):
    service,c,_=mm
    c['steps'][0]['output']='q';c['steps'][1]['output']='a'
    c['steps'][1]['inputs']['question']='q';c['steps'][1]['bindings']['question']='q'
    for s in c['steps'][2:]:s['inputs'].update(question='q',answer='a')
    assert service.save('Renamed',c)['config']==c


def test_external_resources_and_deleted_reference(mm):
    service,c,_=mm
    prompt=container.user_prompt_registry.create('Answer','','Answer from image: {question}',allowed_operators=['PromptedVQAGenerator'])
    schema=container.json_schema_manager.create('QA','','{"type":"object"}','')
    c['steps'][1]['resource_ref']='user_prompt:'+prompt['id']
    c['steps'][2]['resource_ref']='schema_ref:'+schema['id']
    rec=service.save('References',c)
    container.user_prompt_registry.delete(prompt['id'])
    assert not service.check(rec['config'])['structure_valid']
    with pytest.raises(LibraryError,match='Prompt 引用不存在'):service.submit(rec['id'])


def test_media_drift_and_wrong_draft(mm):
    service,c,lib=mm
    rec=service.save('VQA',c)
    path,_=lib.material_file(c['material_ids'][0]);path.write_bytes(b'changed')
    assert any('材料内容已变化' in e for e in service.check(c)['errors'])
    text=lib.create_draft(DraftCreate(name='Text'))
    c['draft_id']=text['id']
    with pytest.raises(LibraryError,match='图文 SFT'):service.save('Wrong',c)


def test_service_reference_never_enables_execution(mm):
    service,c,_=mm;c['vision_service_id']='some-service'
    rec=service.save('Bound',c)
    with pytest.raises(LibraryError,match='桥接尚未启用'):service.submit(rec['id'])


def test_api_roundtrip_and_submit_no_task(mm):
    _,c,_=mm
    app=FastAPI();app.include_router(router,prefix='/mm');client=TestClient(app)
    assert client.get('/mm/template').status_code==200
    r=client.post('/mm/configs',json={'name':'API VQA','config':c});assert r.status_code==200
    rec=r.json()['data'];key=rec['id']
    assert client.get('/mm/configs/'+key).json()['data']==rec
    assert len(client.get('/mm/configs').json()['data'])==1
    assert client.get('/mm/configs/'+key+'/check').json()['data']['structure_valid']
    assert client.post('/mm/configs/'+key+'/submit').status_code==409
    assert client.get('/mm/configs/missing').status_code==404
    c['steps'][0]['output']='image'
    assert client.post('/mm/configs',json={'name':'Bad','config':c}).status_code==400
