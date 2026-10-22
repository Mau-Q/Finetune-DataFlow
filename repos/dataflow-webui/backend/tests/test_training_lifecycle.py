import io
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from app.core.container import container
from app.api.v1.endpoints import data_library, generation
from app.api.v1.handlers import install_exception_handlers
from app.schemas.data_library import DraftCreate
from app.services.data_library import DataLibrary, LibraryError, _hash, _json_bytes
from app.services.training_lifecycle import TrainingLifecycle


@pytest.fixture
def setup(tmp_path):
    lib = DataLibrary(tmp_path/'library')
    return lib, TrainingLifecycle(lib)


def draft(lib, rows=None, modality='text'):
    rec = lib.create_draft(DraftCreate(name='Lifecycle test', modality=modality))
    if rows:
        lib.import_rows(rec['id'], 'data.json', _json_bytes(rows), {})
    return rec['id']


def text_row(output='answer'):
    return {'instruction': 'question', 'input': 'context', 'output': output}


def test_task_collect_release_owned_and_membership(setup, tmp_path):
    lib, life = setup
    did = draft(lib)
    path = tmp_path/'training.jsonl'
    path.write_bytes(_json_bytes(text_row())+b'\n')
    artifact = {'id': 'training_1', 'kind': 'training', 'path': str(path), 'sha256': _hash(path.read_bytes())}
    task = {'task_id': 'task1', 'status': 'completed'}
    result = life.collect(did, task, artifact)
    assert result['added'] == 1
    sid = result['sample_ids'][0]
    assert result['sample_sources'][sid][0]['task_id']=='task1'
    with pytest.raises(LibraryError, match='已经收集'):
        life.collect(did, task, artifact)
    release = life.publish(did)
    original = life.download(release['id']).read_bytes()
    old_jsonl = life.download(release['id'], 'jsonl').read_bytes()
    path.write_text('changed')
    life.edit(did, sid, text_row('changed'))
    assert life.download(release['id']).read_bytes()==original
    assert life.download(release['id'], 'jsonl').read_bytes()==old_jsonl
    release2 = life.publish(did)
    assert release2['version']==2 and release2['data_sha256']!=release['data_sha256']
    forked = life.fork(release['id'])
    assert forked['rows']==[text_row()] and forked['parent_release']==release['id']
    assert forked['sample_ids']==[sid]


def image(lib):
    buffer=io.BytesIO()
    Image.new('RGB',(3,3),'red').save(buffer,format='PNG')
    return lib.add_material('same.png', buffer.getvalue(), {'name':'Image'})


def test_multimodal_portable_bundle_and_original_mutation(setup):
    lib,life=setup
    mat=image(lib)
    row={'messages':[{'role':'user','content':[{'type':'text','text':'Describe'},{'type':'image_url','image_url':{'url':'original.png'}}]}, {'role':'assistant','content':'red'}], 'images':['original.png']}
    did=draft(lib, modality='image_text')
    lib.import_rows(did,'data.json',_json_bytes([row]),{'original.png':mat['id']})
    r=life.publish(did)
    assert 'alpaca' not in r['formats']
    blob=life.download(r['id']).read_bytes()
    with zipfile.ZipFile(io.BytesIO(blob)) as bundle:
        sample=json.loads(bundle.read('data.jsonl'))
        ref=sample['images'][0]
        assert ref.startswith('media/') and not ref.startswith('/')
        assert sample['messages'][0]['content'][1]['image_url']['url']==ref
        assert bundle.read(ref)==lib.material_file(mat['id'])[0].read_bytes()
        meta=json.loads(bundle.read('manifest.json'))
        assert meta['sample_ids'] and meta['media']['original.png']['sha256']==mat['sha256']
    lib.material_file(mat['id'])[0].write_bytes(b'changed')
    assert life.download(r['id']).read_bytes()==blob
    with pytest.raises(LibraryError, match='变化'):
        life.publish(did)
    with pytest.raises(LibraryError, match='不支持'):
        life.download(r['id'],'alpaca')


def test_edit_delete_map_keep_identity_and_atomic_validation(setup):
    lib,life=setup
    did=draft(lib,[text_row('one'),text_row('two')])
    original=life.view(did)
    sid=original['sample_ids'][0]
    with pytest.raises(LibraryError,match='非空'):
        life.edit(did,sid,{'instruction':'','output':''})
    assert life.view(did)['rows']==original['rows']
    life.map_fields(did,{'instruction':'output','input':'','output':'instruction'})
    changed=life.view(did)
    assert changed['rows'][0]=={'instruction':'one','input':'','output':'question'}
    assert changed['sample_ids']==original['sample_ids']
    life.edit(did,sid,delete=True)
    assert life.view(did)['sample_ids']==original['sample_ids'][1:]
    with pytest.raises(LibraryError,match='不存在'):
        life.edit(did,sid,delete=True)


def test_empty_task_collect_success_empty_publish_blocked(setup,tmp_path):
    lib,life=setup
    did=draft(lib)
    path=tmp_path/'empty.jsonl';path.write_bytes(b'')
    item={'id':'empty','kind':'training','path':str(path),'sha256':_hash(b'')}
    assert life.collect(did,{'task_id':'zero','status':'completed'},item)['added']==0
    with pytest.raises(LibraryError,match='空草稿'):
        life.publish(did)


@pytest.mark.parametrize('status,kind',[('failed','training'),('completed','candidate'),('running','training')])
def test_only_completed_training_collects(setup,status,kind):
    lib,life=setup
    with pytest.raises(LibraryError,match='已完成'):
        life.collect(draft(lib),{'status':status},{'kind':kind})


def test_corrupt_or_missing_release_fails(setup):
    lib,life=setup
    rid=life.publish(draft(lib,[text_row()]))['id']
    life.download(rid).write_bytes(b'corrupt')
    with pytest.raises(LibraryError,match='损坏'):
        life.download(rid)
    with pytest.raises(LibraryError,match='不存在'):
        life.download('../source')


def test_concurrent_publish_has_unique_versions(setup):
    lib,life=setup
    did=draft(lib,[text_row()])
    with ThreadPoolExecutor(max_workers=4) as pool:
        versions=list(pool.map(lambda _: TrainingLifecycle(DataLibrary(lib.root)).publish(did)['version'],range(4)))
    assert sorted(versions)==[1,2,3,4]


def test_mapping_failure_does_not_write(setup):
    lib,life=setup;did=draft(lib,[text_row()]);before=life.view(did)
    with pytest.raises(LibraryError,match='缺少源字段'):
        life.map_fields(did,{'instruction':'missing','input':'','output':'output'})
    assert life.view(did)==before


def test_api_publish_download_edit_fork(setup,monkeypatch):
    lib,life=setup;did=draft(lib,[text_row()])
    monkeypatch.setattr(container,'data_library',lib)
    app=FastAPI();app.include_router(generation.router,prefix='/api/v1/generation');app.include_router(data_library.router,prefix='/api/v1/library');install_exception_handlers(app)
    with TestClient(app) as client:
        view=client.get(f'/api/v1/library/drafts/{did}').json()['data']
        sid=view['sample_ids'][0]
        r=client.post(f'/api/v1/generation/drafts/{did}/publish').json()['data']
        blob=client.get(f'/api/v1/generation/releases/{r["id"]}/download').content
        assert zipfile.is_zipfile(io.BytesIO(blob))
        assert client.put(f'/api/v1/generation/drafts/{did}/samples/{sid}',json={'row':text_row('new')}).json()['success']
        assert client.get(f'/api/v1/generation/releases/{r["id"]}/download').content==blob
        assert client.post(f'/api/v1/generation/releases/{r["id"]}/fork').json()['data']['rows']==[text_row()]
        assert len(client.get(f'/api/v1/generation/drafts/{did}/releases').json()['data'])==1


@pytest.mark.parametrize('modality', ['text', 'image_text'])
def test_dpo_file_import_edit_publish_and_fork(setup, modality):
    lib, life = setup
    created = lib.create_draft(DraftCreate(name='DPO（示例）', modality=modality, training_type='dpo'))
    row = {'prompt': '问题', 'chosen': '优选回答', 'rejected': '较差回答'}
    bindings = {}
    if modality == 'image_text':
        material = image(lib)
        row['images'] = ['images/example.png']
        bindings['images/example.png'] = material['id']
    lib.import_rows(created['id'], 'samples.jsonl', _json_bytes(row) + b'\n', bindings)
    view = lib.get_draft(created['id'])
    assert view['training_type'] == 'dpo' and view['rows'] == [row]
    edited = dict(row, chosen='修改后的优选回答')
    life.edit(created['id'], view['sample_ids'][0], edited)
    release = life.publish(created['id'])
    assert release['training_type'] == 'dpo'
    assert 'alpaca' not in release['formats']
    with zipfile.ZipFile(life.download(release['id'])) as bundle:
        exported = json.loads(bundle.read('data.jsonl'))
        assert exported['chosen'] == edited['chosen']
        if modality == 'image_text':
            assert exported['images'][0].startswith('media/')
            assert bundle.read(exported['images'][0])
    forked = life.fork(release['id'])
    assert forked['training_type'] == 'dpo' and forked['modality'] == modality
    life.publish(forked['id'])
    with pytest.raises(LibraryError, match='仅适用于 SFT'):
        life.map_fields(created['id'], {'instruction':'prompt','input':'','output':'chosen'})


@pytest.mark.parametrize('row', [
    {'prompt':'问题','chosen':'回答','rejected':''},
    {'prompt':'问题','chosen':'相同','rejected':'相同'},
    {'instruction':'问题','output':'回答'},
])
def test_invalid_dpo_import_preserves_draft(setup, row):
    lib, _ = setup
    created = lib.create_draft(DraftCreate(name='DPO', training_type='dpo'))
    with pytest.raises(LibraryError, match='DPO'):
        lib.import_rows(created['id'], 'bad.jsonl', _json_bytes(row) + b'\n', {})
    assert lib.get_draft(created['id'])['row_count'] == 0


def test_catalog_latest_release_tracks_versions_without_marking_draft_published(setup, monkeypatch):
    lib, life = setup
    did = draft(lib, [text_row()])
    other = draft(lib, [text_row('other dataset')])
    monkeypatch.setattr(container, 'data_library', lib)
    app = FastAPI(); app.include_router(data_library.router, prefix='/api/v1/library')
    with TestClient(app) as client:
        def summary(record_id):
            return next(r for r in client.get('/api/v1/library/drafts').json()['data'] if r['id'] == record_id)
        assert summary(did)['latest_release_version'] is None
        life.publish(other)
        assert summary(did)['latest_release_version'] is None
        life.publish(did)
        assert summary(did)['latest_release_version'] == 1
        sid = lib.get_draft(did)['sample_ids'][0]
        life.edit(did, sid, text_row('edited after publication'))
        row = summary(did)
        assert row['status'] == 'draft' and row['latest_release_version'] == 1
        assert 'rows' not in row
        assert row['updated_at'] == lib.get_draft(did)['updated_at']
        life.publish(did)
        assert summary(did)['latest_release_version'] == 2
        assert summary(other)['latest_release_version'] == 1


def test_stale_sample_edit_keeps_current_dataset(setup):
    lib, life = setup
    did = draft(lib, [text_row()])
    original = life.view(did)
    sid = original['sample_ids'][0]
    latest = life.edit(did, sid, text_row('newer'), expected_updated_at=original['updated_at'])
    with pytest.raises(LibraryError, match='其他页面更新') as error:
        life.edit(did, sid, text_row('stale'), expected_updated_at=original['updated_at'])
    assert error.value.status == 409
    assert life.view(did)['rows'] == latest['rows']
