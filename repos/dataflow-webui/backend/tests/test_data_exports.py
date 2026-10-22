import io
import json
import csv
import zipfile
import pytest
from PIL import Image
from app.schemas.data_library import DraftCreate
from app.services.data_library import DataLibrary,LibraryError
from app.services.data_reviews import DataReviews
from app.services.data_exports import DataExports
from app.services.training_lifecycle import TrainingLifecycle

ROLES=['develop','review']


def draft(lib,rows,modality='text',kind='sft',bindings=None):
    d=lib.create_draft(DraftCreate(name='Export',modality=modality,training_type=kind));lib.import_rows(d['id'],'x.jsonl',b''.join(json.dumps(r).encode()+b'\n' for r in rows),bindings or {});return lib._get('drafts',d['id'])


def test_fixed_snapshot_formats_and_idempotency(tmp_path,monkeypatch):
    lib=DataLibrary(tmp_path/'data/library');d=draft(lib,[{'instruction':'Q','output':'old','evidence':'keep'}]);e=DataExports(lib)
    original=e.build
    def build(*args):
        TrainingLifecycle(lib).edit(d['id'],d['sample_ids'][0],{'instruction':'Q','output':'new'})
        return original(*args)
    monkeypatch.setattr(e,'build',build)
    body={'source':d['id'],'request_id':'one','format':'jsonl'};r=e.create(body,'dev',ROLES)
    assert r['status']=='ready' and json.loads(e.download(r['id']).read_text())['output']=='old'
    assert e.create(body,'dev',ROLES)['id']==r['id']
    monkeypatch.setattr(e,'build',original)
    r=e.create(dict(body,request_id='alpaca',format='alpaca'),'dev',ROLES)
    assert json.loads(e.download(r['id']).read_text())=={'instruction':'Q','input':'','output':'new'}
    d2=draft(lib,[{'messages':[{'role':'user','content':'Q'},{'role':'assistant','content':'A'}]}])
    r=e.create({'source':d2['id'],'request_id':'messages','format':'messages'},'dev',ROLES)
    assert json.loads(e.download(r['id']).read_text())['messages'][1]['content']=='A'
    d3=draft(lib,[{'prompt':'Q','chosen':'good','rejected':'bad'}],kind='dpo')
    r=e.create({'source':d3['id'],'request_id':'dpo','format':'dpo'},'dev',ROLES)
    assert json.loads(e.download(r['id']).read_text())['rejected']=='bad'
    assert e.preview({'source':d['id'],'format':'dpo'},'dev',ROLES)['compatible']==0
    r=e.create({'source':d['id'],'request_id':'bad','format':'dpo'},'dev',ROLES)
    assert r['status']=='failed'
    with pytest.raises(LibraryError):e.download(r['id'])


def test_media_package_missing_media_and_review_filter(tmp_path):
    lib=DataLibrary(tmp_path/'data/library');buffer=io.BytesIO();Image.new('RGB',(2,2),'blue').save(buffer,format='PNG')
    mat=lib.add_material('image.png',buffer.getvalue(),{'name':'image'})
    d=draft(lib,[{'instruction':'Q','output':'A','image':'a.png'}],modality='image_text',bindings={'a.png':mat['id']});e=DataExports(lib)
    r=e.create({'source':d['id'],'request_id':'media','format':'package'},'dev',ROLES)
    assert r['status']=='ready'
    with zipfile.ZipFile(e.download(r['id'])) as z:
        row=json.loads(z.read('data.jsonl'));assert row['image'] in z.namelist();assert not row['image'].startswith('/')
        assert len(z.read(row['image']))>0
        assert '/Users/' not in z.read('manifest.json').decode()
    path,_=lib.material_file(mat['id']);path.unlink()
    r=e.create({'source':d['id'],'request_id':'missing','format':'package'},'dev',ROLES)
    assert r['status']=='failed'


def test_review_exports_csv_and_exact_revision_filter(tmp_path):
    lib=DataLibrary(tmp_path/'data/library');d=draft(lib,[{'instruction':'Q','output':'A'},{'instruction':'Q2','output':'A2'}]);reviews=DataReviews(lib)
    b=reviews.create({'source':d['id'],'reviewers':['r'],'count':1,'seed':7,'request_id':'review'},'dev')
    i=reviews.detail(b['id'],'r',['review'])['items'][0];i=reviews.action(b['id'],i['id'],'claim',{'version':1},'r',['review'])
    reviews.action(b['id'],i['id'],'submit',{'version':i['version'],'request_id':'submit','scores':{'correctness':5,'support':5,'usability':5},'conclusion':'pass','comment':'=HYPERLINK("bad")'},'r',['review'])
    e=DataExports(lib);r=e.create({'source':d['id'],'batch':b['id'],'request_id':'passed','format':'jsonl'},'dev',ROLES)
    assert r['row_count']==1
    csvr=e.create({'batch':b['id'],'request_id':'csv','format':'review_csv'},'dev',ROLES)
    row=next(csv.DictReader(io.StringIO(e.download(csvr['id']).read_text('utf-8-sig'))));assert row['comment'].startswith("'=")
    TrainingLifecycle(lib).edit(d['id'],i['sample_id'],{'instruction':'Q changed','output':'new'})
    with pytest.raises(LibraryError,match='修订'):e.create({'source':d['id'],'batch':b['id'],'request_id':'conflict','format':'jsonl'},'dev',ROLES)


def test_published_media_review_uses_logical_revision(tmp_path):
    lib=DataLibrary(tmp_path/'data/library');buffer=io.BytesIO();Image.new('RGB',(2,2),'red').save(buffer,format='PNG')
    mat=lib.add_material('r.png',buffer.getvalue(),{'name':'r'})
    d=draft(lib,[{'instruction':'Q','output':'A','image':'original.png'}],modality='image_text',bindings={'original.png':mat['id']})
    reviews=DataReviews(lib);b=reviews.create({'source':d['id'],'reviewers':['r'],'request_id':'review'},'dev')
    i=reviews.detail(b['id'],'r',['review'])['items'][0];i=reviews.action(b['id'],i['id'],'claim',{'version':1},'r',['review'])
    reviews.action(b['id'],i['id'],'submit',{'version':i['version'],'request_id':'submit','scores':{'correctness':5,'support':5,'usability':5},'conclusion':'pass'},'r',['review'])
    release=TrainingLifecycle(lib).publish(d['id'])
    assert 'snapshot_rows' not in release and 'snapshot_media_bindings' not in release
    e=DataExports(lib);result=e.create({'source':release['id'],'kind':'release','batch':b['id'],'request_id':'publish-reviewed-media','format':'package'},'dev',ROLES)
    assert result['status']=='ready'
    with zipfile.ZipFile(e.download(result['id'])) as z:
        row=json.loads(z.read('data.jsonl'));assert row['image'] in z.namelist()


def test_export_cache_expiry_preserves_release(tmp_path):
    lib=DataLibrary(tmp_path/'data/library');d=draft(lib,[{'instruction':'Q','output':'A'}]);release=TrainingLifecycle(lib).publish(d['id'])
    e=DataExports(lib);result=e.create({'source':release['id'],'kind':'release','request_id':'cache','format':'jsonl'},'dev',ROLES)
    exported=e.download(result['id']);e.expire(result['id'],'dev',ROLES)
    assert not exported.exists()
    with pytest.raises(LibraryError):e.download(result['id'])
    assert TrainingLifecycle(lib).download(release['id'],'jsonl').is_file()
