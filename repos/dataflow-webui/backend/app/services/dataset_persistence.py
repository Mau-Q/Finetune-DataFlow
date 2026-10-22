"""Shared cross-process dataset transaction lock and durable file replacement."""
import functools
import os
from pathlib import Path
import tempfile
import threading
from contextlib import contextmanager
from loguru import logger
from app.services.platform_lock import exclusive_lock

_LOCKS = {}
_LOCKS_GUARD = threading.Lock()
_LOCAL = threading.local()
_MANAGERS = {}


def root_key(root):
    return str(Path(root).resolve())


@contextmanager
def dataset_lock(root):
    key = root_key(root)
    with _LOCKS_GUARD:
        lock = _LOCKS.setdefault(key, threading.RLock())
    with lock:
        depths = getattr(_LOCAL, 'depths', None)
        if depths is None:
            depths = _LOCAL.depths = {}
        if depths.get(key):
            depths[key] += 1
            try:
                yield
            finally:
                depths[key] -= 1
            return
        path = Path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with (path.parent / ('.' + path.name + '-datasets.lock')).open('a+') as handle:
            with exclusive_lock(handle):
                depths[key] = 1
                try:
                    yield
                finally:
                    depths.pop(key)


def sync_directory(path):
    # Windows does not allow opening a directory with os.open for fsync.
    # The file itself is flushed before os.replace; directory fsync is a
    # Unix-only durability enhancement.
    if os.name == 'nt':
        return
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.pending-')
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def register_backups(root, manager):
    _MANAGERS[root_key(root)] = manager


def checkpoint(root):
    if getattr(_LOCAL, 'deferred', {}).get(root_key(root), 0):
        return
    manager = _MANAGERS.get(root_key(root))
    if manager:
        try:
            manager.request_snapshot()
        except Exception as exc:
            manager.last_error = str(exc)
            logger.error('Dataset saved, but automatic backup failed: {}', exc)


def registry_write(method):
    @functools.wraps(method)
    def wrapped(self, *args, **kwargs):
        root = Path(self.path).parent
        with dataset_lock(root):
            result = method(self, *args, **kwargs)
            checkpoint(root)
            return result
    return wrapped


@contextmanager
def defer_checkpoints(root):
    key = root_key(root)
    deferred = getattr(_LOCAL, 'deferred', None)
    if deferred is None:
        deferred = _LOCAL.deferred = {}
    deferred[key] = deferred.get(key, 0) + 1
    succeeded = False
    try:
        yield
        succeeded = True
    finally:
        deferred[key] -= 1
        if not deferred[key]:
            deferred.pop(key)
            if succeeded:
                checkpoint(root)


def locked_registry(method):
    """Serialize the complete read/modify/replace cycle, including initializers."""
    @functools.wraps(method)
    def wrapped(self, *args, **kwargs):
        with dataset_lock(self.path):
            return method(self, *args, **kwargs)
    return wrapped
