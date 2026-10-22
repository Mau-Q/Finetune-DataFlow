"""Portable persistence regressions; run without the model/engine test fixtures.

From backend: python -m unittest discover -s platform_tests -v
"""
import errno
import multiprocessing
import os
from pathlib import Path
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services import platform_lock
from app.services.dataset_backups import DatasetBackups
from app.services.dataset_database import DatasetDatabase
from app.services.resource_store import ResourceStore


def increment(path, count):
    store = ResourceStore(path)
    for _ in range(count):
        with store.writing() as data:
            data['count'] = data.get('count', 0) + 1


def hold_lock(path, ready, seconds):
    with open(path, 'a+') as handle:
        with platform_lock.exclusive_lock(handle):
            ready.set()
            time.sleep(seconds)


class PersistenceTests(unittest.TestCase):
    def test_cross_process_updates_are_serialized(self):
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / 'resources.json')
            context = multiprocessing.get_context('spawn')
            workers = [context.Process(target=increment, args=(path, 15)) for _ in range(3)]
            try:
                for worker in workers:
                    worker.start()
                for worker in workers:
                    worker.join(30)
                    self.assertEqual(worker.exitcode, 0)
                self.assertEqual(ResourceStore(path).get('count'), 45)
            finally:
                for worker in workers:
                    if worker.is_alive():
                        worker.terminate()
                    worker.join()

    def test_waits_for_long_holder_and_releases_after_exception(self):
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / 'empty.lock')
            context = multiprocessing.get_context('spawn')
            ready = context.Event()
            seconds = 11 if os.name == 'nt' else 0.2
            worker = context.Process(target=hold_lock, args=(path, ready, seconds))
            worker.start()
            try:
                self.assertTrue(ready.wait(15))
                start = time.monotonic()
                with open(path, 'a+') as handle:
                    with self.assertRaisesRegex(RuntimeError, 'body failure'):
                        with platform_lock.exclusive_lock(handle):
                            self.assertGreaterEqual(time.monotonic() - start, seconds - 0.1)
                            raise RuntimeError('body failure')
                with open(path, 'a+') as handle:
                    with platform_lock.exclusive_lock(handle):
                        pass
                worker.join(15)
                self.assertEqual(worker.exitcode, 0)
            finally:
                if worker.is_alive():
                    worker.terminate()
                worker.join()

    def test_windows_retries_contention_but_not_bad_descriptors(self):
        calls = []
        def locking(fd, operation, size):
            calls.append(operation)
            if operation == 1 and len(calls) <= 12:
                raise OSError(errno.EACCES, 'busy')
        fake = SimpleNamespace(LK_NBLCK=1, LK_UNLCK=2, locking=locking)
        with tempfile.TemporaryFile(mode='a+') as handle:
            with patch.object(platform_lock, 'os', SimpleNamespace(name='nt')):
                with patch.dict('sys.modules', {'msvcrt': fake}), patch.object(platform_lock.time, 'sleep'):
                    with platform_lock.exclusive_lock(handle):
                        pass
                    self.assertEqual(calls, [1] * 13 + [2])
                    with patch.object(fake, 'locking', side_effect=OSError(errno.EBADF, 'bad fd')):
                        with self.assertRaises(OSError) as error:
                            with platform_lock.exclusive_lock(handle):
                                self.fail('must not enter')
                        self.assertEqual(error.exception.errno, errno.EBADF)

    def test_backup_restore_with_uri_characters_and_closed_connections(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp) / '中文 # percent% space'
            root = base / 'data'
            DatasetDatabase(root)
            manager = DatasetBackups(root, base / 'backups')
            archive = manager.snapshot()
            restored = manager.restore(archive, base / 'restore')
            DatasetBackups.validate(restored / 'data')
            # On Windows, leaked SQLite handles prevent directory replacement.
            root.rename(base / 'moved')
            restored.rename(base / 'moved-restore')
            self.assertTrue((base / 'moved' / 'datasets.sqlite3').is_file())


if __name__ == '__main__':
    unittest.main()
