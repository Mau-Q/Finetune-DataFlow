import sqlite3
import pytest
from app.schemas.model_training import TrainingPlan
from app.services.model_training import ModelTraining, TrainingError


def test_plan_reopen_conflict_copy_and_missing_storage(tmp_path):
    s=ModelTraining(tmp_path)
    p=TrainingPlan(name='independent').model_dump()
    r=s.save_plan(p)
    assert r['plan']['group_id'] is None
    assert ModelTraining(tmp_path).get('plans',r['id'])==r
    r2=s.save_plan(dict(p,model='remote/model'),r['id'],r['version'])
    with pytest.raises(TrainingError,match='已更新'): s.save_plan(p,r['id'],r['version'])
    assert s.get('plans',r['id'])==r2
    assert s.check(p)['compatibility']=='failed'
    backup=s.backup()
    with sqlite3.connect(backup) as db: assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    s.path.unlink()
    with pytest.raises(TrainingError,match='缺失'): ModelTraining(tmp_path)


def test_corrupt_database_is_not_reset(tmp_path):
    p=tmp_path/'training.sqlite3';p.write_bytes(b'broken')
    with pytest.raises(TrainingError,match='损坏'): ModelTraining(tmp_path)
    assert p.read_bytes()==b'broken'

from app.services.training_compiler import catalog, compile_plan, save_descriptor

@pytest.mark.parametrize('family,name',[('selection','random'),('mixture','odm'),('reweighting','loss'),('reorder','dynamic_folding'),('lego','select_only')])
def test_families_compile_without_importing_training_packages(tmp_path,family,name):
    s=ModelTraining(tmp_path)
    p=TrainingPlan(model='/remote/model',data=[{'kind':'file','ref':'a.jsonl'},{'kind':'file','ref':'b.jsonl','domain':'second'}],strategy={'family':family,'component':name,'params':{}}).model_dump()
    r=compile_plan(s,p)
    assert not r['checks']['errors'],r['checks']
    assert json.loads(r['yaml']['dataset_info.json'])==r['dataset_info']
    assert r['train']['packing'] is False
    assert r['train']['report_to']=='none'
    assert r['train']['train_type'].startswith('dynamic_')


def test_compatibility_and_custom_description(tmp_path):
    s=ModelTraining(tmp_path)
    p=TrainingPlan(model='m',data=[{'kind':'file','ref':'a'}],strategy={'family':'reweighting','component':'adapt','params':{}}).model_dump()
    assert any('参考集' in e for e in compile_plan(s,p)['checks']['errors'])
    p['strategy']={'family':'mixture','component':'static','params':{'proportions':[1,1]}}
    assert any('总和' in e for e in compile_plan(s,p)['checks']['errors'])
    descriptor={'family':'selection','name':'user_alg','fields':{'k':{'type':'integer','default':3,'minimum':1}},'tasks':['sft'],'modalities':['text']}
    save_descriptor(s,descriptor)
    p['strategy']={'family':'selection','component':'user_alg','params':{'k':0}}
    assert any('最小值' in e for e in compile_plan(s,p)['checks']['errors'])
    p['strategy']['params']['k']=4
    assert compile_plan(s,p)['components']['selectors']['user_alg']['params']['k']==4
    p['task']='dpo'
    assert any('DPO' in e for e in compile_plan(s,p)['checks']['errors'])

import json, zipfile, io, subprocess, sys
from pathlib import Path
from app.services.training_bundles import export_bundle, safe_members, snapshot_source


def test_portable_bundle_hash_guard_and_no_fake_run(tmp_path,monkeypatch):
    src=tmp_path/'src';(src/'src/dataflex').mkdir(parents=True)
    (src/'src/dataflex/cli.py').write_text('print("fixture")')
    from app.services import training_bundles
    from app.services.model_training import digest
    (src/'UPSTREAM.json').write_text(json.dumps({'commit':'a'*40,'files':{'src/dataflex/cli.py':digest((src/'src/dataflex/cli.py').read_bytes())}}))
    monkeypatch.setattr(training_bundles,'DATAFLEX_SOURCE_ROOT',src)
    # A stale external-path variable must never redirect the source snapshot.
    monkeypatch.setenv('DATAFLEX_SOURCE_DIR',str(tmp_path/'missing-external-source'))
    data=tmp_path/'rows.jsonl';data.write_text('{"instruction":"q","output":"a"}\n')
    service=ModelTraining(tmp_path/'state')
    r=service.save_plan(TrainingPlan(model='/remote/model',data=[{'kind':'file','ref':str(data)}]).model_dump())
    bundle=export_bundle(service,r['id'])
    members=safe_members(Path(bundle['path']).read_bytes());dest=tmp_path/'moved';dest.mkdir()
    for k,v in members.items():p=dest/k;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(v)
    result=subprocess.run([sys.executable,str(dest/'runner.py'),'verify'],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert service.list('runs')==[]
    (dest/'data/dataset_0.jsonl').write_text('changed')
    result=subprocess.run([sys.executable,str(dest/'runner.py'),'verify'],capture_output=True,text=True)
    assert result.returncode!=0
    data.write_text('{"instruction":"changed","output":"a"}\n')
    bundle2=export_bundle(service,r['id'])
    assert bundle2['manifest']['inputs'][0]['sha256']!=bundle['manifest']['inputs'][0]['sha256']
    (src/'src/dataflex/cli.py').write_text('print("changed")')
    bundle3=export_bundle(service,r['id'])
    assert bundle3['manifest']['source_sha256']!=bundle2['manifest']['source_sha256']


def test_zip_and_symlink_guards(tmp_path):
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:z.writestr('../escape','no')
    with pytest.raises(TrainingError,match='不安全'):safe_members(out.getvalue())
    from app.services.training_bundles import safe_read
    (tmp_path/'file').write_text('x')
    try:
        (tmp_path/'link').symlink_to(tmp_path/'file')
    except OSError as exc:
        if getattr(exc, 'winerror', None) != 1314: raise
        pytest.skip('Creating a real symlink requires Windows Developer Mode or elevated privileges')
    with pytest.raises(TrainingError,match='普通文件'):safe_read(tmp_path/'link')

from app.services.training_results import import_result,run_detail,add_evaluation,compare
from app.services.model_training import digest, canonical


def result_fixture(service,attempt='attempt1',status='running',sequence=1):
    p=TrainingPlan(model='fixture').model_dump()
    if not service.list('bundles'):service.put('bundles',{'manifest_sha256':'a'*64,'plan_snapshot':p,'manifest':{'source':{'commit':'fixture','dirty':False}}},'bundle1')
    return {'schema_version':1,'run_id':'run1','attempt_id':attempt,'input_manifest_sha256':'a'*64,'sequence':sequence,'synthetic':True,'status':status,'metrics':[{'step':1,'loss':2.0}],'strategy_metrics':[],'artifacts':[{'id':'model','sha256':'b'*64,'path':'/fixture/adapter','availability':'remote_registered','identity_scope':'adapter_config'}],'environment':{'fixture':True},'actual_config':p,'log':'synthetic'}


def test_result_idempotency_increment_and_sealing(tmp_path):
    s=ModelTraining(tmp_path);payload=result_fixture(s)
    r=import_result(s,payload);assert import_result(s,payload)['idempotent']
    bad=dict(payload,sequence=2,synthetic=False)
    with pytest.raises(TrainingError,match='身份'):import_result(s,bad)
    updated=dict(payload,sequence=2,metrics=payload['metrics']+[{'step':2,'loss':1}],status='failed')
    import_result(s,updated)
    assert run_detail(s,r['id'])['status']=='failed'
    with pytest.raises(TrainingError,match='封存'):import_result(s,dict(updated,sequence=3))
    assert not compare(s,[r['id']])['runs']
    assert len(compare(s,[r['id']],True)['runs'])==1
    with pytest.raises(TrainingError):import_result(s,dict(updated,metrics=[{'loss':float('nan')}]))


def test_evaluation_requires_artifact_identity_and_partial_jsonl(tmp_path):
    s=ModelTraining(tmp_path);r=import_result(s,result_fixture(s))
    payload={'attempt_id':r['id'],'artifact_id':'model','artifact_sha256':'c'*64,'task':'qa','dataset_version':'heldout-v1','metric_definitions':{'acc':'exact match'},'metrics':{'acc':.5},'tool_version':'test-v1','config':{'seed':42}}
    with pytest.raises(TrainingError,match='不匹配'):add_evaluation(s,payload)
    payload['artifact_sha256']='b'*64
    e=add_evaluation(s,payload);assert e['synthetic'];assert add_evaluation(s,payload)['id']==e['id']
    from app.services.training_runtime.runner import read_metrics
    p=tmp_path/'metrics.jsonl';p.write_text('{"current_steps":1,"loss":2}\n{"current_steps":2')
    assert read_metrics(p)==[{'current_steps':1,'step':1,'loss':2}]


def test_training_backup_restore_and_tamper_guard(tmp_path):
    from app.services.training_backups import backup,verify,restore
    s=ModelTraining(tmp_path/'original');payload=result_fixture(s)
    # Synthetic bundle metadata fixture used above has no physical bundle; remove for this result-only snapshot.
    with s.connect() as db:db.execute("DELETE FROM records WHERE kind='bundles'")
    from app.schemas.model_training import TrainingPlan
    # Real zip content and matching registry record for backup integrity.
    p=s.root/'bundles/bundle1.zip';p.parent.mkdir();p.write_bytes(b'fixture zip')
    s.put('bundles',{'manifest_sha256':'a'*64,'plan_snapshot':TrainingPlan().model_dump(),'manifest':{'source':{}},'archive_sha256':digest(p.read_bytes()),'path':str(p)},'bundle1')
    import_result(s,payload)
    path=backup(s);files,manifest=verify(path)
    recovered=restore(path,tmp_path/'recovered')
    assert run_detail(recovered,'attempt1')['result']==payload
    assert Path(recovered.get('bundles','bundle1')['path']).is_file()
    assert manifest['remote_checkpoints_included'] is False
    with pytest.raises(TrainingError,match='空目录'):restore(path,recovered.root)
    content=io.BytesIO()
    with zipfile.ZipFile(path) as source,zipfile.ZipFile(content,'w') as out:
        for name in source.namelist():out.writestr(name,b'tampered' if name.startswith('results/') else source.read(name))
    damaged=tmp_path/'damaged.zip';damaged.write_bytes(content.getvalue())
    with pytest.raises(TrainingError,match='哈希'):verify(damaged)
    # A rewritten outer manifest cannot certify content that contradicts the DB identity.
    with zipfile.ZipFile(path) as source:
        contents={name:source.read(name) for name in source.namelist()}
    outer=json.loads(contents['backup_manifest.json'])
    result_name=next(name for name in contents if name.startswith('results/'))
    contents[result_name]=b'{"tampered":true}'
    outer['files'][result_name]=digest(contents[result_name])
    contents['backup_manifest.json']=canonical(outer)
    with zipfile.ZipFile(damaged,'w') as out:
        for name,body in contents.items():out.writestr(name,body)
    with pytest.raises(TrainingError,match='结果哈希'):verify(damaged)


def test_api_versions_schemas_result_identity_and_missing_host(tmp_path,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.v1.endpoints.model_training import router
    from app.core.container import container
    service=ModelTraining(tmp_path);monkeypatch.setattr(container,'model_training',service)
    app=FastAPI();app.include_router(router,prefix='/training');client=TestClient(app)
    body={'plan':TrainingPlan(name='API independent').model_dump()}
    r=client.post('/training/plans',json=body).json()['data']
    assert client.put('/training/plans/'+r['id'],json=body).status_code==409
    assert client.post('/training/start',json={'bundle_id':'none','idempotency_key':'request-123'}).status_code==409
    body['plan']['batch_size']=0
    assert client.post('/training/plans',json=body).status_code==422
    assert client.get('/training/plans/'+r['id']).json()['data']['version']==1


def test_release_message_and_media_bundle_is_portable(tmp_path,monkeypatch):
    # This media-conversion contract must not depend on a sibling DataFlex checkout.
    import app.services.training_bundles as bundles
    monkeypatch.setattr(bundles,'snapshot_source',lambda *args:({'source/src/dataflex/cli.py':b'# synthetic media fixture'}, {'commit':'fixture','dirty':False,'files':{}}))
    from app.services.data_library import DataLibrary
    from app.services.training_lifecycle import TrainingLifecycle
    from app.schemas.data_library import DraftCreate,MaterialMetadata
    from PIL import Image
    library=DataLibrary(tmp_path/'data/library')
    picture=io.BytesIO();Image.new('RGB',(2,2),'red').save(picture,format='PNG')
    mat=library.add_material('fixture.png',picture.getvalue(),MaterialMetadata(name='fixture').model_dump())
    draft=library.create_draft(DraftCreate(name='fixture image',modality='image_text',training_type='sft'))
    rows=[{'messages':[{'role':'user','content':[{'type':'text','text':'describe'},{'type':'image_url','image_url':{'url':'image1'}}]},{'role':'assistant','content':'red'}]}]
    library.import_rows(draft['id'],'fixture.jsonl',b''.join(canonical(r)+b'\n' for r in rows),{'image1':mat['id']})
    release=TrainingLifecycle(library).publish(draft['id'])
    s=ModelTraining(tmp_path/'training',library)
    plan=s.save_plan(TrainingPlan(model='/fixture/vlm',modality='image_text',data=[{'kind':'release','ref':release['id']}]).model_dump())
    bundle=export_bundle(s,plan['id']);members=safe_members(Path(bundle['path']).read_bytes())
    data=json.loads(members['data/dataset_0.jsonl'])
    assert '<image>' in data['messages'][0]['content']
    assert 'data/'+data['images'][0] in members
    assert json.loads(members['data/dataset_info.json'])['dataset_0']['formatting']=='sharegpt'
    assert json.loads(members['sample_map.json'])['mapping'][0]['sample_id']==release['sample_ids'][0]
    from app.services.training_bundles import import_bundle
    assert import_bundle(s,Path(bundle['path']).read_bytes())['idempotent']


def test_hf_preparation_creates_importable_derived_identity_offline(tmp_path,monkeypatch):
    import app.services.training_bundles as bundles
    monkeypatch.setattr(bundles,'snapshot_source',lambda *args:({'source/src/dataflex/cli.py':b'# synthetic source'}, {'commit':'fixture','dirty':False,'files':{}}))
    service=ModelTraining(tmp_path/'state')
    r=service.save_plan(TrainingPlan(model='/remote/model',data=[{'kind':'huggingface','ref':'fixture/data','revision':'a'*40}]).model_dump())
    bundle=bundles.export_bundle(service,r['id']);members=bundles.safe_members(Path(bundle['path']).read_bytes())
    root=tmp_path/'prepare';root.mkdir()
    for name,body in members.items():p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(body)
    (root/'datasets.py').write_text('''import json
class Dataset:
 def to_json(self,path,**kwargs):open(path,'w').write(json.dumps({'instruction':'fixture','output':'answer'})+'\\n')
def load_dataset(ref,subset,revision,split):
 assert ref=='fixture/data' and revision=='a'*40 and split=='train'
 return Dataset()
''')
    ran=subprocess.run([sys.executable,str(root/'prepare_data.py'),'--allow-dataset-download'],capture_output=True,text=True)
    assert ran.returncode==0,ran.stderr
    derived=next(tmp_path.glob('prepared-*.zip'))
    imported=bundles.import_bundle(service,derived.read_bytes())
    assert imported['manifest']['parent_manifest_sha256']==bundle['manifest_sha256']
    assert imported['manifest_sha256']!=bundle['manifest_sha256']
    assert not imported['manifest']['external_references']
    assert 'data/dataset_0.jsonl' in imported['manifest']['files']


def test_explicit_external_reference_is_hashed_without_copy(tmp_path,monkeypatch):
    import app.services.training_bundles as bundles
    monkeypatch.setattr(bundles,'snapshot_source',lambda *args:({'source/src/dataflex/cli.py':b'# fixture'}, {'commit':'fixture','dirty':False,'files':{}}))
    s=ModelTraining(tmp_path/'state');data=tmp_path/'input.jsonl';data.write_bytes(b'{"instruction":"q","output":"a"}\n')
    record=s.save_plan(TrainingPlan(model='/remote/model',data=[{'kind':'file','ref':str(data),'mode':'reference','execution_ref':'/remote/data/large.jsonl'}]).model_dump())
    b=bundles.export_bundle(s,record['id'])
    assert b['manifest']['external_references'][0]['sha256']==digest(data.read_bytes())
    assert b['manifest']['external_references'][0]['ref']=='/remote/data/large.jsonl'
    assert 'data/dataset_0.jsonl' not in b['manifest']['files']
    for remote in (r'C:\data\input.jsonl', r'/remote\input.jsonl', 'relative/input.jsonl'):
        invalid=s.save_plan(TrainingPlan(model='/remote/model',data=[{'kind':'file','ref':str(data),'mode':'reference','execution_ref':remote}]).model_dump())
        with pytest.raises(TrainingError,match='Linux 绝对路径'):
            bundles.export_bundle(s,invalid['id'])
