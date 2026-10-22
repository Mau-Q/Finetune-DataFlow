import io
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfWriter

from app.api.v1.endpoints import data_library, datasets
from app.api.v1.handlers import install_exception_handlers
from app.core.config import settings
from app.core.container import container
from app.services.data_library import DataLibrary
from app.services.dataset_registry import DatasetRegistry, VisualizeDatasetService


def pdf():
    writer = PdfWriter(); writer.add_blank_page(width=80, height=100)
    buffer = io.BytesIO(); writer.write(buffer)
    return buffer.getvalue()


def png():
    buffer = io.BytesIO(); Image.new('RGB', (8, 8), 'red').save(buffer, 'PNG')
    return buffer.getvalue()


@pytest.fixture
def source_app(tmp_path, monkeypatch):
    registry = DatasetRegistry(str(tmp_path / 'registry.yaml'), scan=False)
    library = DataLibrary(tmp_path / 'library')
    monkeypatch.setattr(settings, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(settings, 'RESOURCE_DIR', 'data')
    monkeypatch.setattr(container, 'dataset_registry', registry)
    monkeypatch.setattr(container, 'dataset_visualize_service', VisualizeDatasetService())
    monkeypatch.setattr(container, 'data_library', library)
    app = FastAPI(); app.include_router(datasets.router, prefix='/api/v1/datasets'); app.include_router(data_library.router, prefix='/api/v1/library'); install_exception_handlers(app)
    with TestClient(app) as client:
        yield client, registry, library


def test_visibility_only_affects_listing_and_survives_reload(source_app, tmp_path):
    client, registry, _ = source_app
    for name in ['paper', 'example']:
        path = tmp_path / (name + '.jsonl'); path.write_text('{"x":1}\n')
        registry.add_or_update({'name': name, 'root': str(path), 'pipeline': 'test', 'meta': {}})
    keep, hidden = registry.list()
    config = tmp_path / 'data/dataset_visibility.json'; config.parent.mkdir()
    config.write_text(json.dumps({'hidden_dataset_ids': [hidden['id']]}))
    all_records = client.get('/api/v1/datasets/').json()['data']
    assert len(all_records) == 2
    assert [r['is_visible'] for r in all_records] == [True, False]
    visible = client.get('/api/v1/datasets/?visible_only=true').json()['data']
    assert [r['id'] for r in visible] == [keep['id']]
    assert client.get('/api/v1/datasets/' + hidden['id']).json()['data']['id'] == hidden['id']
    assert DatasetRegistry(registry.path, scan=False).get(hidden['id'])
    # Future uploads stay visible without editing the preference snapshot.
    upload = client.post('/api/v1/datasets/upload?name=new', files={'file': ('new.jsonl', b'{"x":2}\n')}).json()
    assert upload['success']
    assert len(client.get('/api/v1/datasets/?visible_only=true').json()['data']) == 2


def test_source_upload_forms_pipeline_manifest_and_preview(source_app):
    client, registry, library = source_app
    result = client.post('/api/v1/library/inputs/upload', data={'name': 'papers'}, files=[('files', ('paper.pdf', pdf())), ('files', ('image.png', png()))]).json()
    assert result['success']
    record = result['data']; assert record['num_samples'] == 2
    rows = [json.loads(line) for line in Path(record['root']).read_text().splitlines()]
    assert [r['source_name'] for r in rows] == ['paper.pdf', 'image.png']
    assert all(Path(r['source']).is_file() and r['material_id'] for r in rows)
    assert client.get(f'/api/v1/library/inputs/{record["id"]}/file?row=0').content == pdf()
    assert client.get(f'/api/v1/library/inputs/{record["id"]}/file?row=1').content == png()
    preview = client.get(f'/api/v1/library/inputs/{record["id"]}/preview?offset=1&limit=1').json()['data']
    assert preview == rows[1:]
    assert not client.get(f'/api/v1/library/inputs/{record["id"]}/file?row=2').json()['success']
    duplicate = client.post('/api/v1/library/inputs/upload', data={'name': 'duplicate'}, files=[('files', ('other.pdf', pdf())), ('files', ('other.png', png()))]).json()
    assert not duplicate['success'] and duplicate['meta']['http_status'] == 409
    assert len(registry.list()) == 1 and len(library.list_materials()) == 2


def test_upload_same_name_cannot_overwrite_previous_file(source_app):
    client, registry, _ = source_app
    records = []
    for number in (1, 2):
        record = client.post('/api/v1/datasets/upload', files={'file': ('../../same.jsonl', f'{{"n":{number}}}\n'.encode())}).json()['data']
        records.append(record)
    assert records[0]['root'] != records[1]['root']
    assert json.loads(Path(records[0]['root']).read_text()) == {'n': 1}
    assert json.loads(Path(records[1]['root']).read_text()) == {'n': 2}
    assert Path(records[0]['root']).name == 'same.jsonl'


def test_legacy_source_preview_and_missing_file(source_app, tmp_path):
    client, registry, _ = source_app
    paper = tmp_path / 'old-paper.pdf'; paper.write_bytes(pdf())
    manifest = tmp_path / 'sources.jsonl'; manifest.write_text(json.dumps({'source': str(paper), 'source_name': paper.name}))
    record = registry.add_or_update({'name': 'papers', 'root': str(manifest), 'pipeline': 'test', 'meta': {}})
    url = f'/api/v1/library/inputs/{record["id"]}/file'
    assert client.get(url).content == pdf()
    paper.unlink()
    failed = client.get(url).json(); assert not failed['success'] and failed['meta']['http_status'] == 404


def test_csv_preview_and_invalid_import(source_app, tmp_path):
    client, registry, _ = source_app
    path = tmp_path / 'table.csv'; path.write_text('a,b\n1,2\n3,4\n')
    record = registry.add_or_update({'name': 'table', 'root': str(path), 'pipeline': 'test', 'meta': {}})
    assert client.get(f'/api/v1/library/inputs/{record["id"]}/preview?offset=1&limit=1').json()['data'] == [{'a': '3', 'b': '4'}]
    failed = client.post('/api/v1/library/inputs/upload', data={'name': 'invalid'}, files={'files': ('fake.pdf', b'not a pdf')}).json()
    assert not failed['success'] and len(registry.list()) == 1


def test_hidden_draft_still_accessible_by_id(source_app, tmp_path):
    client, _, _ = source_app
    record = client.post('/api/v1/library/drafts', json={'name': 'example'}).json()['data']
    path = tmp_path / 'data/dataset_visibility.json'; path.parent.mkdir(); path.write_text(json.dumps({'hidden_draft_ids': [record['id']]}))
    assert client.get('/api/v1/library/drafts?visible_only=true').json()['data'] == []
    assert client.get('/api/v1/library/drafts').json()['data'][0]['id'] == record['id']
    assert client.get('/api/v1/library/drafts/' + record['id']).json()['success']


def test_parquet_null_preview_is_json_serializable(source_app, tmp_path):
    import pandas as pd
    client, registry, _ = source_app
    path = tmp_path / 'table.parquet'; pd.DataFrame({'value': [1.0, None]}).to_parquet(path)
    record = registry.add_or_update({'name': 'table', 'root': str(path), 'pipeline': 'test', 'meta': {}})
    response = client.get(f'/api/v1/library/inputs/{record["id"]}/preview').json()
    assert response['success'] and response['data'] == [{'value': 1.0}, {'value': None}]
    assert record['num_samples'] == 2


def test_repeated_file_in_one_selection_is_rejected(source_app):
    client, registry, library = source_app
    response = client.post('/api/v1/library/inputs/upload', data={'name': 'repeat'}, files=[('files', ('a.pdf', pdf())), ('files', ('b.pdf', pdf()))]).json()
    assert not response['success'] and '重复内容' in response['message']
    assert registry.list() == [] and library.list_materials() == []


@pytest.mark.parametrize('rows,content_type,file_count', [
    ([{'source': '/papers/a.pdf'}, {'source': '/papers/b.PDF'}], 'pdf', 2),
    ([{'source': '/images/a.png', 'material_id': 'mat_a'}], 'image', 1),
    ([{'source': '/papers/a.pdf'}, {'source': '/images/a.jpg'}], 'pdf_image', 2),
    ([{'instruction': 'question', 'output': 'answer', 'source': '/papers/a.pdf'}], None, None),
    ([{'source': '/papers/a.pdf'}, {'text': 'ordinary record'}], None, None),
    ([{'source': '/docs/a.txt', 'source_name': 'a.pdf'}], 'text', 1),
    ([], None, None),
])
def test_catalog_content_type_is_distinct_from_storage(source_app, tmp_path, rows, content_type, file_count):
    client, registry, _ = source_app
    path = tmp_path / 'manifest.jsonl'
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    record = registry.add_or_update({'name': 'Dataset name is not evidence', 'root': str(path), 'pipeline': 'test', 'meta': {}})
    listing = client.get('/api/v1/datasets/?visible_only=true').json()['data'][0]
    detail = client.get('/api/v1/datasets/' + record['id']).json()['data']
    for result in [listing, detail]:
        assert result['type'] == 'jsonl'
        assert result['content_type'] == content_type
        assert result['file_count'] == file_count
    assert 'content_type' not in registry.get(record['id'])


def test_catalog_content_cache_refreshes_after_file_change(source_app, tmp_path):
    client, registry, _ = source_app
    path = tmp_path / 'manifest.jsonl'
    path.write_text('{"source":"a.pdf"}\n')
    registry.add_or_update({'name': 'files', 'root': str(path), 'pipeline': 'test', 'meta': {}})
    assert client.get('/api/v1/datasets/').json()['data'][0]['content_type'] == 'pdf'
    path.write_text('{"source":"image.png"}\n')
    assert client.get('/api/v1/datasets/').json()['data'][0]['content_type'] == 'image'
    path.unlink()
    assert client.get('/api/v1/datasets/').json()['data'][0]['content_type'] is None


def test_catalog_times_survive_schema_and_reregistration(source_app, tmp_path):
    client, registry, _ = source_app
    path = tmp_path / 'times.jsonl'; path.write_text('{"x":1}\n\n')
    record = registry.add_or_update({'name': 'first', 'root': str(path), 'pipeline': 'test', 'meta': {}})
    listing = client.get('/api/v1/datasets/').json()['data'][0]
    assert listing['num_samples'] == 1
    assert listing['created_at'] == record['created_at']
    assert listing['updated_at'] == record['updated_at']
    updated = registry.add_or_update({'name': 'renamed', 'root': str(path), 'pipeline': 'test', 'meta': {}})
    assert updated['created_at'] == record['created_at']
    assert updated['added_at'] == record['added_at']
    assert updated['updated_at'] >= record['updated_at']
    detail = client.get('/api/v1/datasets/' + record['id']).json()['data']
    assert detail['updated_at'] == updated['updated_at']


def test_csv_catalog_counts_records_without_header_or_multiline_fields(source_app, tmp_path):
    _, registry, _ = source_app
    path = tmp_path / 'rows.csv'
    path.write_text('question,answer\n"first\nquestion",one\nsecond,two\n')
    record = registry.add_or_update({'name': 'table', 'root': str(path), 'pipeline': 'test', 'meta': {}})
    assert record['num_samples'] == 2


@pytest.mark.parametrize('suffix', ['txt', 'md'])
def test_text_upload_preview_and_download_are_one_document(source_app, suffix):
    client, _, _ = source_app
    content = '\ufeff几何观察\n\n红色正方形、蓝色圆形、绿色三角形。\n'.encode('utf-8')
    rec = client.post('/api/v1/datasets/upload?name=text', files={'file': ('notes.' + suffix, content)}).json()['data']
    assert rec['num_samples'] == 1
    preview = client.get(f'/api/v1/library/inputs/{rec["id"]}/preview').json()
    assert preview['success'] and preview['data'] == [{'text': content.decode('utf-8-sig')}]
    assert client.get(f'/api/v1/library/inputs/{rec["id"]}/preview?offset=1').json()['data'] == []
    assert client.get('/api/v1/datasets/file_type_sample/' + rec['id']).content == content


def test_folder_import_detects_types_preserves_nested_paths_and_owned_copies(source_app):
    client, registry, library = source_app
    files = [('batch/papers/note.pdf', pdf()), ('batch/images/shape.png', png()),
             ('batch/text/note.txt', '全文\n第二行'.encode()),
             ('batch/a/data.csv', b'id,value\n1,first\n'), ('batch/b/data.csv', b'id,value\n2,second\n')]
    result = client.post('/api/v1/library/inputs/upload-folder', data={'name': 'folder'}, files=[
        *[('files', (name, content)) for name, content in files],
        ('files', ('batch/.DS_Store', b'ignored')), ('files', ('batch/tool.exe', b'ignored'))]).json()
    assert result['success'], result
    record = result['data']
    detail = client.get('/api/v1/datasets/' + record['id']).json()['data']
    assert detail['content_type'] == 'mixed' and detail['file_count'] == 5
    assert json.loads(detail['meta']['skipped_files']) == ['batch/.DS_Store', 'batch/tool.exe']
    rows = client.get(f'/api/v1/library/inputs/{record["id"]}/preview').json()['data']
    assert [row['source_name'] for row in rows] == sorted(n for n, _ in files)
    originals = dict(files)
    for index, row in enumerate(rows):
        assert Path(row['source']).is_relative_to(library.root)
        assert client.get(f'/api/v1/library/inputs/{record["id"]}/file?row={index}').content == originals[row['source_name']]
        if row['source_name'].endswith('.csv'):
            preview = client.get(f'/api/v1/library/inputs/{record["id"]}/member-preview?row={index}').json()
            expected = 'first' if '/a/' in row['source_name'] else 'second'
            assert preview['data'][0]['value'] == expected
        if row['source_name'].endswith('.txt'):
            assert client.get(f'/api/v1/library/inputs/{record["id"]}/member-preview?row={index}').json()['data'] == [{'text': '全文\n第二行'}]
    with library.db.reading() as con:
        assert con.execute('SELECT COUNT(*) FROM source_members WHERE dataset_id=?', (record['id'],)).fetchone()[0] == 5
    duplicate = client.post('/api/v1/library/inputs/upload-folder', data={'name': 'again'}, files=[('files', (n, c)) for n, c in reversed(files)]).json()
    assert not duplicate['success'] and duplicate['meta']['http_status'] == 409
    assert len(registry.list()) == 1


@pytest.mark.parametrize('entries,kind', [
    ([('folder/a.pdf', 'pdf')], 'pdf'),
    ([('folder/a.png', 'png')], 'image'),
    ([('folder/a.txt', 'txt'), ('folder/b.md', 'txt')], 'text'),
    ([('folder/a.csv', 'csv'), ('folder/b.jsonl', 'jsonl')], 'structured'),
    ([('folder/a.pdf', 'pdf'), ('folder/a.png', 'png')], 'pdf_image'),
])
def test_folder_homogeneous_content_forms(source_app, entries, kind):
    client, _, _ = source_app
    contents = {'pdf': pdf(), 'png': png(), 'txt': b'plain text', 'csv': b'a\n1\n', 'jsonl': b'{"a":1}\n'}
    result = client.post('/api/v1/library/inputs/upload-folder', data={'name': 'type'}, files=[('files', (name, contents[type_])) for name, type_ in entries]).json()
    assert result['success'], result
    detail = client.get('/api/v1/datasets/' + result['data']['id']).json()['data']
    assert detail['content_type'] == kind and detail['file_count'] == len(entries)


@pytest.mark.parametrize('bad_name,bad_content', [('folder/z.json', b'not json'), ('folder/z.pdf', b'not pdf'), ('../escape.txt', b'text'), ('folder/z.txt', b'\xff')])
def test_invalid_folder_is_atomic(source_app, bad_name, bad_content):
    client, registry, library = source_app
    result = client.post('/api/v1/library/inputs/upload-folder', data={'name': 'invalid'}, files=[
        ('files', ('folder/a.png', png())), ('files', ('folder/b.txt', b'valid')), ('files', (bad_name, bad_content))]).json()
    assert not result['success']
    assert registry.list() == [] and library.list_materials() == []
    assert not list(library.root.rglob('*.png'))
    assert not list(library.root.rglob('*.txt'))
    assert not list(library.root.rglob('*.jsonl'))


def test_native_selection_auto_detects_folder_and_imports_owned_files(source_app, tmp_path, monkeypatch):
    from app.services import local_source_picker
    client, registry, _ = source_app
    root = tmp_path / 'selected'; (root / 'nested').mkdir(parents=True)
    (root / 'image.png').write_bytes(png())
    (root / 'nested/note.txt').write_text('内容', encoding='utf-8')
    (root / '.hidden').write_text('skip')
    (root / 'skip.exe').write_text('skip')
    monkeypatch.setattr(local_source_picker, 'pick_paths', lambda: [str(root)])
    choice = client.post('/api/v1/library/inputs/choose-local').json()['data']
    assert choice['data_form'] == '混合' and choice['count'] == 2
    assert {f['name'] for f in choice['files']} == {'selected/image.png', 'selected/nested/note.txt'}
    assert all(f['size'] > 0 and not Path(f['name']).is_absolute() for f in choice['files'])
    assert len(choice['skipped']) == 2 and registry.list() == []
    record = client.post('/api/v1/library/inputs/import-local', data={'selection_id': choice['selection_id'], 'name': 'native'}).json()['data']
    assert (root / 'nested/note.txt').read_text() == '内容'
    assert client.get('/api/v1/datasets/' + record['id']).json()['data']['content_type'] == 'mixed'
    assert not client.post('/api/v1/library/inputs/import-local', data={'selection_id': choice['selection_id'], 'name': 'again'}).json()['success']


def test_native_selection_single_file_keeps_record_count(source_app, tmp_path, monkeypatch):
    from app.services import local_source_picker
    client, _, _ = source_app
    file = tmp_path / 'rows.csv'; file.write_text('a\n1\n2\n')
    monkeypatch.setattr(local_source_picker, 'pick_paths', lambda: [str(file)])
    choice = client.post('/api/v1/library/inputs/choose-local').json()['data']
    assert choice['data_form'] == '结构化数据' and choice['count'] == 1
    record = client.post('/api/v1/library/inputs/import-local', data={'selection_id': choice['selection_id'], 'name': 'csv'}).json()['data']
    assert record['num_samples'] == 2 and record['type'] == 'csv'
    assert client.get('/api/v1/datasets/file_type_sample/' + record['id']).content == file.read_bytes()


def test_native_cancel_and_changed_selection_never_import(source_app, tmp_path, monkeypatch):
    from app.services import local_source_picker
    client, registry, library = source_app
    monkeypatch.setattr(local_source_picker, 'pick_paths', lambda: [])
    assert client.post('/api/v1/library/inputs/choose-local').json()['data'] == {'cancelled': True}
    file = tmp_path / 'note.txt'; file.write_text('first')
    monkeypatch.setattr(local_source_picker, 'pick_paths', lambda: [str(file)])
    choice = client.post('/api/v1/library/inputs/choose-local').json()['data']
    file.write_text('changed content')
    result = client.post('/api/v1/library/inputs/import-local', data={'selection_id': choice['selection_id'], 'name': 'test'}).json()
    assert not result['success'] and result['meta']['http_status'] == 409
    assert registry.list() == [] and library.list_materials() == []
    assert not client.post('/api/v1/library/inputs/import-local', data={'selection_id': 'arbitrary-path', 'name': 'test'}).json()['success']
