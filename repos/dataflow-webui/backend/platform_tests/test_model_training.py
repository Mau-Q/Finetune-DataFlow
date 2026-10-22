"""Offline training integration contracts, also run by Windows persistence CI."""
import builtins
from contextlib import closing
import importlib
import io
import json
import multiprocessing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from app.schemas.model_training import TrainingPlan
from app.services.model_training import ModelTraining, TrainingError, canonical, digest
from app.services.training_bundles import import_bundle


def conflicting_bundle(root, name, barrier, outcomes):
    service = ModelTraining(root)
    body = canonical(TrainingPlan(name=name).model_dump())
    manifest = {'format':'dataflex-run-bundle','schema_version':1,'bundle_id':'b'*32,
                'source':{},'files':{'plan.json':digest(body)}}
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        archive.writestr('plan.json', body)
        archive.writestr('manifest.json', canonical(manifest))
    barrier.wait(15)
    try:
        result = import_bundle(service, data.getvalue())
        outcomes.put(('saved', result['archive_sha256']))
    except TrainingError as exc:
        outcomes.put(('rejected', exc.status))


class ModelTrainingIntegrationTests(unittest.TestCase):
    def test_host_controls_import_without_posix_modules(self):
        real_import = builtins.__import__
        def guarded(name, *args, **kwargs):
            if name == 'fcntl':
                raise ImportError('fcntl is unavailable on Windows')
            return real_import(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=guarded):
            module = importlib.import_module('app.services.training_ssh')
            importlib.reload(module)

    def test_training_database_backup_and_restore_with_uri_characters(self):
        from app.services.training_backups import backup, restore
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / '中文 # percent% space' / 'training'
            service = ModelTraining(root)
            plan = service.save_plan(TrainingPlan(name='中文训练方案').model_dump())
            archive = backup(service)
            recovered = restore(archive, root.parent / 'recovered # %')
            self.assertEqual(recovered.get('plans', plan['id'])['plan']['name'], '中文训练方案')
            # Windows refuses these renames if SQLite handles remain open.
            service.path.rename(root / 'moved.sqlite3')
            recovered.path.rename(recovered.root / 'moved.sqlite3')

    def test_catalog_uses_utf8_under_non_utf8_locale(self):
        from app.services.training_compiler import catalog
        real_read = Path.read_text
        def locale_read(path, encoding=None, errors=None):
            return real_read(path, encoding=encoding or 'ascii', errors=errors)
        with tempfile.TemporaryDirectory() as temp:
            service = ModelTraining(temp)
            with patch.object(Path, 'read_text', locale_read):
                self.assertGreater(len(catalog(service)['components']), 0)

    def test_host_save_lock_and_plan_conflicts(self):
        from app.services.training_ssh import save_host, host_config
        with tempfile.TemporaryDirectory() as temp:
            service = ModelTraining(temp)
            host = {'alias':'fixture-only','workdir':'/tmp/training-fixture','python':'/usr/bin/python3','gpus':'0'}
            saved = save_host(service, host)
            self.assertEqual(host_config(service), saved)
            plan = service.save_plan(TrainingPlan().model_dump())
            service.save_plan(dict(plan['plan'], name='new'), plan['id'], plan['version'])
            with self.assertRaises(TrainingError):
                service.save_plan(plan['plan'], plan['id'], plan['version'])
            self.assertEqual(service.get('plans', plan['id'])['plan']['name'], 'new')

    def test_conflicting_bundle_imports_cannot_replace_winners_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            context = multiprocessing.get_context('spawn')
            barrier = context.Barrier(3)
            outcomes = context.Queue()
            workers = [context.Process(target=conflicting_bundle, args=(temp, str(i), barrier, outcomes)) for i in range(3)]
            try:
                for worker in workers:
                    worker.start()
                for worker in workers:
                    worker.join(25)
                    self.assertEqual(worker.exitcode, 0)
                statuses = [outcomes.get(timeout=5) for _ in workers]
                self.assertEqual(sum(status[0] == 'saved' for status in statuses), 1)
                self.assertEqual(sum(status == ('rejected', 409) for status in statuses), 2)
                saved = ModelTraining(temp).get('bundles', 'b'*32)
                self.assertEqual(digest(Path(saved['path']).read_bytes()), saved['archive_sha256'])
            finally:
                for worker in workers:
                    if worker.is_alive():
                        worker.terminate()
                    worker.join()
                outcomes.close()

    def test_corrupt_store_and_bundle_conflicts_preserve_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            service = ModelTraining(Path(temp) / 'training')
            def bundle(name):
                body = canonical(TrainingPlan(name=name).model_dump())
                manifest = {'format':'dataflex-run-bundle','schema_version':1,'bundle_id':'a'*32,
                            'source':{}, 'files':{'plan.json':digest(body)}}
                result = io.BytesIO()
                with zipfile.ZipFile(result, 'w') as archive:
                    archive.writestr('plan.json', body)
                    archive.writestr('manifest.json', canonical(manifest))
                return result.getvalue()
            first = import_bundle(service, bundle('first'))
            original = Path(first['path']).read_bytes()
            with self.assertRaises(TrainingError):
                import_bundle(service, bundle('conflict'))
            self.assertEqual(Path(first['path']).read_bytes(), original)
            self.assertEqual(service.get('bundles', first['id']), first)
            self.assertTrue(import_bundle(service, original)['idempotent'])
            service.path.write_bytes(b'corrupt evidence')
            with self.assertRaises(TrainingError):
                ModelTraining(service.root)
            self.assertEqual(service.path.read_bytes(), b'corrupt evidence')


if __name__ == '__main__':
    unittest.main()
