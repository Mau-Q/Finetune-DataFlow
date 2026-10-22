import io
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfWriter

from app.api.v1.endpoints import data_library
from app.api.v1.handlers import install_exception_handlers
from app.core.container import container
from app.schemas.data_library import DraftCreate, MaterialRegister
from app.services.data_library import DataLibrary, LibraryError


def png(color='red'):
    buffer = io.BytesIO()
    Image.new('RGB', (12, 8), color).save(buffer, format='PNG')
    return buffer.getvalue()


def pdf():
    writer = PdfWriter()
    writer.add_blank_page(width=80, height=100)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.fixture
def library(tmp_path):
    return DataLibrary(tmp_path / 'library')


@pytest.fixture
def client(library, monkeypatch):
    monkeypatch.setattr(container, 'data_library', library)
    app = FastAPI()
    app.include_router(data_library.router, prefix='/api/v1/library')
    install_exception_handlers(app)
    with TestClient(app) as client:
        yield client


def material(library, color='red', **meta):
    return library.add_material('same.png', png(color), {'name': color, **meta})


def test_material_identity_persistence_and_owned_copy(library, tmp_path):
    a = material(library)
    b = material(library, 'blue')
    assert a['id'] != b['id']
    assert a['filename'] == b['filename']
    assert library.material_file(a['id'])[0].read_bytes() == png()
    assert len(DataLibrary(library.root).list_materials()) == 2
    with pytest.raises(LibraryError, match='重复材料'):
        material(library)
    source = tmp_path / 'source.pdf'
    source.write_bytes(pdf())
    rec = library.register_material(MaterialRegister(name='PDF', path=str(source)))
    source.write_text('changed')
    assert library.material_file(rec['id'])[0].read_bytes() == pdf()
    assert rec['pages'] == 1


def test_links_group_update_and_cycle_rejected(library):
    a = material(library)
    b = material(library, 'blue', parent_material_id=a['id'], relation='parsed_table')
    updated = library.update_material(b['id'], {'name': 'table', 'group': 'group-a', 'source': 'source', 'parent_material_id': a['id'], 'relation': 'parsed_table'})
    assert updated['group'] == 'group-a'
    with pytest.raises(LibraryError, match='循环'):
        library.update_material(a['id'], {'name': 'cycle', 'parent_material_id': b['id']})
    with pytest.raises(LibraryError, match='关联'):
        material(library, 'green', relation='parsed_formula')


@pytest.mark.parametrize('filename,content', [('a.svg', b'<svg/>'), ('a.pdf', b'not pdf'), ('a.png', b'not image'), ('a.jpg', png()), ('a.png', b'')])
def test_invalid_material_has_no_side_effect(library, filename, content):
    with pytest.raises(LibraryError):
        library.add_material(filename, content, {'name': 'invalid'})
    assert library.list_materials() == []
    assert list(library.materials.iterdir()) == []


def test_draft_import_atomic_validation_duplicates_and_reload(library):
    draft = library.create_draft(DraftCreate(name='text'))
    row = {'instruction': 'Question?', 'input': '', 'output': 'Answer.'}
    raw = json.dumps([row, row]).encode()
    result = library.import_rows(draft['id'], 'data.json', raw, {})
    assert (result['added'], result['duplicates_skipped']) == (1, 1)
    with pytest.raises(LibraryError, match='已经导入'):
        library.import_rows(draft['id'], 'other.jsonl', b'\n'.join(json.dumps(r).encode() for r in [row, row]), {})
    invalid = [dict(row, output='different'), {'instruction': 'missing output'}]
    with pytest.raises(LibraryError, match='第 2 条'):
        library.import_rows(draft['id'], 'invalid.json', json.dumps(invalid).encode(), {})
    detail = DataLibrary(library.root).get_draft(draft['id'])
    assert detail['row_count'] == 1
    assert detail['rows'] == [row]
    assert detail['training_type'] == 'sft' and detail['modality'] == 'text'
    assert detail['fields'] == ['input', 'instruction', 'output']


@pytest.mark.parametrize('content', [b'{}', b'[]', b'not JSON', b'[{"instruction":"x","instruction":"y","output":"z"}]', b'[{"instruction":"x","output":"y","score":NaN}]', b'\xff'])
def test_bad_training_files_do_not_write(library, content):
    draft = library.create_draft(DraftCreate(name='text'))
    with pytest.raises(LibraryError):
        library.import_rows(draft['id'], 'bad.json', content, {})
    assert library.get_draft(draft['id'])['row_count'] == 0


def test_image_training_requires_explicit_media_and_detects_missing_files(library):
    a = material(library)
    draft = library.create_draft(DraftCreate(name='vision', modality='image_text'))
    rows = [{'messages': [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'images/a.png'}}, {'type': 'text', 'text': 'What?'}]}, {'role': 'assistant', 'content': 'A red image.'}]}]
    raw = json.dumps(rows).encode()
    with pytest.raises(LibraryError, match='媒体缺失'):
        library.import_rows(draft['id'], 'data.json', raw, {})
    library.import_rows(draft['id'], 'data.json', raw, {'images/a.png': a['id']})
    assert library.get_draft(draft['id'])['media_bindings'] == {'images/a.png': a['id']}
    path, _ = library.material_file(a['id'])
    path.unlink()
    with pytest.raises(LibraryError, match='缺失'):
        library.import_rows(draft['id'], 'more.json', json.dumps([{'instruction': 'x', 'output': 'y', 'images': ['images/a.png']}]).encode(), {})
    assert library.get_draft(draft['id'])['row_count'] == 1


def test_text_rejects_images_and_chat_requires_assistant(library):
    draft = library.create_draft(DraftCreate(name='text'))
    for row in [{'instruction': 'x', 'output': 'y', 'images': ['a.png']}, {'messages': [{'role': 'user', 'content': 'question'}]}]:
        with pytest.raises(LibraryError):
            library.import_rows(draft['id'], 'data.json', json.dumps([row]).encode(), {})


def test_concurrent_imports_preserve_both_batches(library):
    draft = library.create_draft(DraftCreate(name='text'))
    def add(i):
        # Independent service objects model multiple backend workers.
        return DataLibrary(library.root).import_rows(draft['id'], 'data.json', json.dumps([{'instruction': str(i), 'output': 'y'}]).encode(), {})
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(add, range(8)))
    assert library.get_draft(draft['id'])['row_count'] == 8


def test_atomic_write_failure_preserves_previous_document(library, monkeypatch):
    draft = library.create_draft(DraftCreate(name='text'))
    def fail(*args):
        raise OSError('disk write failed')
    original = library.db.put
    def fail_after_put(kind, record):
        original(kind, record)
        fail()
    monkeypatch.setattr(library.db, 'put', fail_after_put)
    with pytest.raises(OSError):
        library.import_rows(draft['id'], 'data.json', b'[{"instruction":"x","output":"y"}]', {})
    assert library.get_draft(draft['id'])['row_count'] == 0
    assert not list(library.drafts.glob('.pending-*'))


def test_api_end_to_end_with_real_envelope(client, library):
    base = '/api/v1/library'
    upload = client.post(base + '/materials/upload', files={'file': ('paper.pdf', pdf(), 'application/pdf')}, data={'metadata': json.dumps({'name': 'paper', 'group': 'research'})}).json()
    assert upload['success']
    mat = upload['data']
    response = client.get(f'{base}/materials/{mat["id"]}/file')
    assert response.content == pdf()
    assert response.headers['content-type'] == 'application/pdf'
    duplicate = client.post(base + '/materials/upload', files={'file': ('other.pdf', pdf())}, data={'metadata': '{"name":"same"}'}).json()
    assert duplicate['success'] is False and duplicate['meta']['http_status'] == 409
    draft = client.post(base + '/drafts', json={'name': 'training'}).json()['data']
    imported = client.post(f'{base}/drafts/{draft["id"]}/import', files={'file': ('data.jsonl', b'{"instruction":"hi","output":"hello"}\n')}).json()
    assert imported['success'] and imported['data']['row_count'] == 1
    assert client.get(f'{base}/drafts/{draft["id"]}?limit=1').json()['data']['rows'][0]['output'] == 'hello'
    assert client.get(f'{base}/drafts/{draft["id"]}?limit=0').json()['success'] is False
    assert not client.post(base + '/drafts', json={'name': 'bad', 'training_type': 'unsupported'}).json()['success']
    assert not client.get(base + '/materials/unknown/file').json()['success']
    assert client.get(base + '/materials').json()['data'][0]['group'] == 'research'


def test_corrupt_metadata_fails_visibly(library):
    a = material(library)
    with library.db.transaction() as con:
        con.execute('PRAGMA ignore_check_constraints=ON')
        con.execute("UPDATE materials SET payload=? WHERE id=?", ('{corrupt',a['id']))
    with pytest.raises(json.JSONDecodeError):
        DataLibrary(library.root).list_materials()


def test_single_image_field_and_media_rebinding(library):
    a = material(library)
    b = material(library, 'blue')
    draft = library.create_draft(DraftCreate(name='vision', modality='image_text'))
    row = {'instruction': 'what?', 'output': 'red', 'image': 'a.png'}
    library.import_rows(draft['id'], 'data.json', json.dumps([row]).encode(), {'a.png': a['id']})
    row['output'] = 'different'
    with pytest.raises(LibraryError, match='已绑定'):
        library.import_rows(draft['id'], 'other.json', json.dumps([row]).encode(), {'a.png': b['id']})
    text = library.create_draft(DraftCreate(name='text'))
    with pytest.raises(LibraryError, match='文本数据集含图片'):
        library.import_rows(text['id'], 'bad.json', json.dumps([row]).encode(), {'a.png': a['id']})
