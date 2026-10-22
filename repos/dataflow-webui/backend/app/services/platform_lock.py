"""Small cross-platform exclusive file lock used by local persistence code."""

from __future__ import annotations

import errno
import os
import time
from contextlib import contextmanager


@contextmanager
def exclusive_lock(handle):
    """Hold an exclusive lock on the first byte of an open lock file."""
    if os.name == "nt":
        import msvcrt

        # Windows permits locking past EOF, so an empty lock file needs no
        # initialization write (which could race with another lock holder).
        # LK_LOCK gives up after ten attempts; match flock's blocking behavior
        # by retrying only contention errors with the nonblocking operation.
        while True:
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                time.sleep(0.05)
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle, fcntl.LOCK_EX)
    try:
        yield
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
