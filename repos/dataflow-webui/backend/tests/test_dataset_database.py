import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest
from PIL import Image
from pypdf import PdfWriter
from app.schemas.data_library import DraftCreate
from app.services.data_library import DataLibrary, _json_bytes
from app.services.dataset_registry import DatasetRegistry
from app.services.dataset_database import DatasetDatabase
from app.services.dataset_backups import DatasetBackups
from app.services.dataset_adoption import adopt_pdf_dataset
from app.services.dataset_persistence import register_backups


def seed(tmp_path):
    root=tmp_path/'data';root.mkdir()
    lib=DataLibrary(root/'library')
    buffer=io.BytesIO();Image.new('RGB',(8,8),'red').save(buffer,'PNG')
    material=lib.add_material('image.png',buffer.getvalue(),{'name':'Image'})
    draft=lib.create_draft(DraftCreate(name='DPO',training_type='dpo',modality='image_text'))
    row={'prompt':'颜色？','chosen':'红色','rejected':'蓝色','images':['image.png']}
    lib.import_rows(draft['id'],'data.jsonl',_json_bytes(row)+b'\n',{'image.png':material['id']})
    original=tmp_path/'paper.pdf';writer=PdfWriter();writer.add_blank_page(width=80,height=80)
    with original.open('wb') as handle:writer.write(handle)
    manifest=root/'inputs.jsonl';manifest.write_text(json.dumps({'source':str(original),'source_name':original.name})+'\n')
    registry=DatasetRegistry(str(root/'data_registry.yaml'),scan=False)
    source=registry.add_or_update({'name':'PDFs','root':str(manifest),'pipeline':'test','meta':{}})
    return root,lib,registry,source,draft,material,original


def test_sqlite_normalizes_rows_and_media_and_survives_new_instance(tmp_path):
    root,lib,registry,source,draft,material,_=seed(tmp_path)
    assert DataLibrary(root/'library').get_draft(draft['id'])==lib.get_draft(draft['id'])
    with sqlite3.connect(root/'datasets.sqlite3') as con:
        assert con.execute('SELECT COUNT(*) FROM samples').fetchone()[0]==1
        assert con.execute('SELECT material_id FROM draft_media').fetchone()[0]==material['id']
        assert con.execute('PRAGMA foreign_key_check').fetchall()==[]
    # Legacy YAML is an import source, not a second authority.
    Path(registry.path).write_text('datasets: {}\n')
    assert DatasetRegistry(registry.path,scan=False).get(source['id'])==source


def test_legacy_library_migration_is_idempotent_and_keeps_sources(tmp_path):
    root,lib,registry,source,draft,material,_=seed(tmp_path)
    records={kind:lib.db.list(kind) for kind in ('materials','drafts','releases')}
    legacy=tmp_path/'legacy';legacy.mkdir()
    for kind,values in records.items():
        (legacy/'library'/kind).mkdir(parents=True)
        for record in values:(legacy/'library'/kind/(record['id']+'.json')).write_bytes(_json_bytes(record))
    before={str(p):p.read_bytes() for p in legacy.rglob('*.json')}
    migrated=DataLibrary(legacy/'library')
    assert migrated.get_draft(draft['id'])['rows']==lib.get_draft(draft['id'])['rows']
    migrated.create_draft(DraftCreate(name='Added after migration'))
    assert len(DataLibrary(legacy/'library').list_drafts())==2
    assert all(Path(p).read_bytes()==content for p,content in before.items())


def test_registry_concurrent_updates_and_abrupt_exit_roll_back(tmp_path):
    root,_,registry,source,_,_,_=seed(tmp_path)
    def add(i):
        path=root/f'{i}.jsonl';path.write_text('{"value":1}\n')
        return DatasetRegistry(registry.path,scan=False).add_or_update({'name':str(i),'root':str(path),'pipeline':'test','meta':{}})
    with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(add,range(20)))
    assert len(registry.list())==21
    code='import sqlite3,os,sys; c=sqlite3.connect(sys.argv[1]); c.execute("BEGIN IMMEDIATE"); c.execute("DELETE FROM source_datasets"); os._exit(7)'
    result=subprocess.run([sys.executable,'-c',code,str(root/'datasets.sqlite3')])
    assert result.returncode==7
    assert len(DatasetRegistry(registry.path,scan=False).list())==21
    assert registry.get(source['id'])==source


def test_pdf_adoption_preserves_id_original_and_is_idempotent(tmp_path):
    root,lib,registry,source,_,_,original=seed(tmp_path)
    content=original.read_bytes()
    result=adopt_pdf_dataset(registry,lib,source['id'])
    adopted=registry.get(source['id'])
    assert adopted['id']==source['id'] and Path(adopted['root']).is_relative_to(lib.root)
    assert original.read_bytes()==content
    assert all(Path(r['copy']).read_bytes()==content for r in result['files'])
    count=len(lib.list_materials())
    adopt_pdf_dataset(registry,lib,source['id'])
    assert len(lib.list_materials())==count
    assert original.read_bytes()==content
    re_registered=registry.add_or_update(dict(registry.get(source['id'])))
    assert re_registered['id']==source['id'] and len(registry.list())==1


def test_backup_restore_isolated_does_not_read_live_originals(tmp_path):
    root,lib,registry,source,draft,material,original=seed(tmp_path)
    manager=DatasetBackups(root,tmp_path/'backups')
    archive=manager.snapshot()
    original.unlink()
    restored=manager.restore(archive,tmp_path/'restored')
    manifest=manager.verify(archive)
    for name,metadata in manifest['files'].items():
        assert (restored/name).is_file()
    DatasetBackups.validate(restored/'data',manifest,restored)
    assert lib.get_draft(draft['id'])['row_count']==1
    with pytest.raises(ValueError,match='already exists'):manager.restore(archive,restored)


@pytest.mark.parametrize('damage',['database','missing_database','image'])
def test_automatic_recovery_preserves_damaged_evidence(tmp_path,damage):
    root,lib,_,_,draft,material,_=seed(tmp_path)
    manager=DatasetBackups(root,tmp_path/'backups')
    manager.snapshot()
    database=root/'datasets.sqlite3'
    image=lib.materials/material['blob_name']
    if damage=='database':database.write_bytes(b'broken database')
    elif damage=='missing_database':database.unlink()
    else:image.write_bytes(b'broken image')
    result=manager.recover_if_needed()
    assert Path(result['quarantine']).is_dir()
    DatasetBackups.validate(root)
    assert DataLibrary(root/'library').get_draft(draft['id'])['row_count']==1
    if damage=='database':assert (Path(result['quarantine'])/'datasets.sqlite3').read_bytes()==b'broken database'
    if damage=='image':assert (Path(result['quarantine'])/'library/materials'/material['blob_name']).read_bytes()==b'broken image'


def test_backup_hash_rejects_tampering_and_recovery_preserves_changed_external(tmp_path):
    root,_,_,_,_,_,original=seed(tmp_path)
    manager=DatasetBackups(root,tmp_path/'backups');archive=manager.snapshot()
    corrupt=tmp_path/'tampered.zip'
    with zipfile.ZipFile(archive) as src,zipfile.ZipFile(corrupt,'w') as dst:
        for name in src.namelist():dst.writestr(name,b'broken' if name=='data/datasets.sqlite3' else src.read(name))
    with pytest.raises(ValueError):manager.restore(corrupt,tmp_path/'invalid-restore')
    assert not (tmp_path/'invalid-restore').exists()
    original.write_bytes(b'user changed external original')
    (root/'datasets.sqlite3').write_bytes(b'broken database')
    with pytest.raises(RuntimeError,match='External file changed'):manager.recover_if_needed()
    assert original.read_bytes()==b'user changed external original'
    assert (root/'datasets.sqlite3').read_bytes()==b'broken database'


def test_mutations_coalesce_backups_and_retention_keeps_baseline(tmp_path):
    root,lib,_,_,_,_,_=seed(tmp_path)
    manager=DatasetBackups(root,tmp_path/'backups',keep=2)
    baseline=manager.snapshot();baseline.rename(baseline.with_name(baseline.stem+'-baseline.zip'))
    register_backups(root,manager)
    for i in range(3):lib.create_draft(DraftCreate(name=f'new-{i}'))
    assert len(manager.archives())==1
    manager.flush_pending()
    assert len(manager.archives())==2
    archive,manifest=manager.latest()
    restored=manager.restore(archive,tmp_path/'latest-restore')
    with sqlite3.connect(restored/'data/datasets.sqlite3') as con:
        assert con.execute('SELECT COUNT(*) FROM drafts').fetchone()[0]==4


def test_source_members_are_database_relations_after_adoption(tmp_path):
    root,lib,registry,source,_,_,_=seed(tmp_path)
    adopt_pdf_dataset(registry,lib,source['id'])
    with sqlite3.connect(root/'datasets.sqlite3') as con:
        row=con.execute('SELECT dataset_id,material_id,source_path FROM source_members WHERE dataset_id=?',(source['id'],)).fetchone()
        assert row[0]==source['id'] and row[1].startswith('mat_')
        assert Path(row[2]).is_relative_to(lib.materials)
        assert con.execute('PRAGMA user_version').fetchone()[0]==2


def test_periodic_backup_worker_starts_and_stops(tmp_path):
    import time
    root,_,_,_,_,_,_=seed(tmp_path)
    manager=DatasetBackups(root,tmp_path/'backups',interval=0.03)
    manager.start()
    try:
        deadline=time.monotonic()+3
        while len(manager.archives())<2 and time.monotonic()<deadline:
            time.sleep(0.01)
        assert len(manager.archives())>=2
        assert manager.last_error is None
    finally:
        manager.stop()
    assert not manager._thread.is_alive()


def test_explicit_recovery_can_undo_a_committed_sample_deletion(tmp_path):
    from app.services.training_lifecycle import TrainingLifecycle
    root,lib,_,_,draft,_,_=seed(tmp_path)
    manager=DatasetBackups(root,tmp_path/'backups');archive=manager.snapshot()
    sample=lib.get_draft(draft['id'])['sample_ids'][0]
    TrainingLifecycle(lib).edit(draft['id'],sample,delete=True)
    assert lib.get_draft(draft['id'])['row_count']==0
    result=manager.recover_if_needed(archive)
    assert lib.get_draft(draft['id'])['row_count']==1
    with sqlite3.connect(Path(result['quarantine'])/'datasets.sqlite3') as con:
        assert con.execute('SELECT COUNT(*) FROM samples').fetchone()[0]==0


def test_missing_database_cannot_replace_a_good_backup_with_empty_state(tmp_path):
    root,_,_,_,_,_,_=seed(tmp_path)
    manager=DatasetBackups(root,tmp_path/'backups');good=manager.snapshot()
    (root/'datasets.sqlite3').unlink()
    with pytest.raises(ValueError,match='refusing an empty backup'):
        manager.snapshot(reason='periodic')
    assert manager.archives()==[good]
    manager.recover_if_needed()
    with sqlite3.connect(root/'datasets.sqlite3') as con:
        assert con.execute('SELECT COUNT(*) FROM samples').fetchone()[0]==1


def test_backup_includes_committed_pages_still_in_wal(tmp_path):
    root,lib,_,_,_,_,_=seed(tmp_path)
    keeper=lib.db.connect()
    try:
        keeper.execute('PRAGMA wal_autocheckpoint=0')
        lib.create_draft(DraftCreate(name='Committed in WAL'))
        wal=Path(str(root/'datasets.sqlite3')+'-wal')
        assert wal.exists() and wal.stat().st_size>0
        manager=DatasetBackups(root,tmp_path/'backups')
        archive=manager.snapshot()
        restored=manager.restore(archive,tmp_path/'restored')
        with sqlite3.connect(restored/'data/datasets.sqlite3') as con:
            assert con.execute('SELECT COUNT(*) FROM drafts').fetchone()[0]==2
        assert not any(name.endswith(('-wal','-shm')) for name in manager.verify(archive)['files'])
    finally:
        keeper.close()
