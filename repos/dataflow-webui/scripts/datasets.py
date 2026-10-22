#!/usr/bin/env python3
"""Dataset storage administration. Use the same Python environment as the backend."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app.core.config import settings
from app.services.dataset_backups import DatasetBackups


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--data-root',type=Path,default=Path(settings.BASE_DIR)/settings.RESOURCE_DIR)
    parser.add_argument('--backup-dir',type=Path)
    subs=parser.add_subparsers(dest='command',required=True)
    subs.add_parser('backup')
    subs.add_parser('status')
    verify=subs.add_parser('verify');verify.add_argument('archive',type=Path)
    restore=subs.add_parser('restore');restore.add_argument('archive',type=Path);restore.add_argument('--target',type=Path,required=True)
    recover=subs.add_parser('recover');recover.add_argument('--archive',type=Path)
    adopt=subs.add_parser('adopt-pdfs');adopt.add_argument('dataset_id')
    args=parser.parse_args();manager=DatasetBackups(args.data_root,args.backup_dir)
    if args.command=='backup':
        result={'snapshot':str(manager.snapshot())}
    elif args.command=='verify':
        manifest=manager.verify(args.archive);result={'files':len(manifest['files']),'verified':True}
    elif args.command=='restore':
        result={'restored':str(manager.restore(args.archive,args.target))}
    elif args.command=='recover':
        # Recovery swaps the live directory. Require an offline process, not a live API route.
        import socket,os
        try:
            with socket.create_connection(('127.0.0.1',int(os.environ.get('DATAFLOW_PORT','8000'))),timeout=2):
                running=True
        except OSError:
            running=False
        if running:
            raise SystemExit('Stop the backend before running in-place recovery.')
        result={'recovery':manager.recover_if_needed(args.archive)}
    elif args.command=='adopt-pdfs':
        from app.services.dataset_registry import DatasetRegistry
        from app.services.data_library import DataLibrary
        from app.services.dataset_adoption import adopt_pdf_dataset
        result=adopt_pdf_dataset(DatasetRegistry(str(args.data_root/'data_registry.yaml'),scan=False),DataLibrary(args.data_root/'library'),args.dataset_id)
        result['snapshot']=str(manager.snapshot(reason='after-pdf-adoption'))
        from app.services.dataset_persistence import atomic_write
        atomic_write(manager.directory/('adoption-'+args.dataset_id+'.json'),json.dumps(result,ensure_ascii=False,indent=2).encode())
    else:
        archive,manifest=manager.latest();manager.validate(args.data_root)
        result={'database':str(args.data_root/'datasets.sqlite3'),'valid':True,'latest_backup':str(archive) if archive else None,
                'backup_files':len(manifest['files']) if manifest else 0,'unresolved_legacy_sources':manifest.get('unresolved_external',[]) if manifest else []}
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
