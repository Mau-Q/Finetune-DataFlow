"""Verified backups of local training state. Remote model weights are never implied."""
from app.services.model_training import training_transaction
from app.services.dataset_persistence import atomic_write
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import uuid
import zipfile
from app.services.model_training import ModelTraining,TrainingError,canonical,digest
from app.services.training_bundles import safe_members,safe_read


@training_transaction
def backup(service):
    database=service.backup()
    files={'training.sqlite3':database.read_bytes()}
    for directory in ['results','bundles']:
        for path in (service.root/directory).glob('*'):
            if path.is_file():files[directory+'/'+path.name]=safe_read(path)
    manifest={'format':'dataflex-local-backup','schema_version':1,'remote_checkpoints_included':False,'files':{k:digest(v) for k,v in files.items()}}
    target=service.root/'backups'/(uuid.uuid4().hex+'.zip')
    import io
    archive=io.BytesIO()
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for name,content in files.items():z.writestr(name,content)
        z.writestr('backup_manifest.json',canonical(manifest))
    atomic_write(target,archive.getvalue())
    verify(target)
    return target


def verify(path):
    files=safe_members(Path(path).read_bytes())
    try:manifest=json.loads(files.pop('backup_manifest.json'))
    except (KeyError,ValueError) as e:raise TrainingError('备份清单缺失或无效') from e
    if manifest.get('format')!='dataflex-local-backup' or manifest.get('schema_version')!=1 or set(files)!=set(manifest.get('files',{})):raise TrainingError('备份清单与成员不一致')
    for name,h in manifest['files'].items():
        p=Path(name)
        if name!='training.sqlite3' and (len(p.parts)!=2 or p.parts[0] not in ['results','bundles']):raise TrainingError('备份成员位置无效')
        if digest(files[name])!=h:raise TrainingError('备份文件哈希不一致')
    if 'training.sqlite3' not in files:raise TrainingError('备份缺少数据库')
    with tempfile.TemporaryDirectory() as tmp:
        dbpath=Path(tmp)/'training.sqlite3';dbpath.write_bytes(files['training.sqlite3'])
        try:
            with closing(sqlite3.connect(dbpath)) as db:
                if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise TrainingError('备份数据库损坏')
                records=[(kind,json.loads(body)) for kind,body in db.execute('SELECT kind,body FROM records')]
                for kind,r in records:
                    if kind=='runs':
                        name='results/'+r['content_sha256']+'.json'
                        if name not in files or digest(files[name])!=r['content_sha256']:raise TrainingError('备份缺少结果文件或结果哈希不一致')
                    if kind=='bundles':
                        name='bundles/'+r['id']+'.zip'
                        if name not in files or digest(files[name])!=r['archive_sha256']:raise TrainingError('备份缺少运行包或哈希不一致')
        except sqlite3.Error as e:raise TrainingError('备份数据库损坏') from e
    return files,manifest


def restore(path,destination):
    files,manifest=verify(path);destination=Path(destination)
    if destination.exists() and any(destination.iterdir()):raise TrainingError('恢复仅允许到新的空目录，不覆盖现有训练数据')
    destination.mkdir(parents=True,exist_ok=True)
    for name,content in files.items():
        p=destination/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(content)
    service=ModelTraining(destination)
    # Rebase only local bundle paths; remote host/control paths remain historical evidence.
    for r in service.list('bundles'):
        r['path']=str((destination/'bundles'/(r['id']+'.zip')).resolve())
        service.put('bundles',r,r['id'],r['version'])
    return service


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True)
    b=sub.add_parser('backup');b.add_argument('root')
    v=sub.add_parser('verify');v.add_argument('archive')
    r=sub.add_parser('restore');r.add_argument('archive');r.add_argument('destination');a=p.parse_args()
    if a.command=='backup':print(backup(ModelTraining(a.root)))
    elif a.command=='verify':print(json.dumps(verify(a.archive)[1]))
    else:print(restore(a.archive,a.destination).path)
