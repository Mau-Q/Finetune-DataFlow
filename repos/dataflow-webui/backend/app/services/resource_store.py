"""Atomic, locked JSON resource records; always read current disk state."""
import copy
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone, timedelta
from app.services.platform_lock import exclusive_lock


def next_updated_at(previous):
    """Advance revision timestamps even on coarse or backward-moving clocks.

    Call while holding the resource write lock so optimistic edit preconditions
    cannot reuse a previous revision within one Windows clock tick.
    """
    now = datetime.now(timezone.utc)
    if previous:
        before = datetime.fromisoformat(previous)
        if before.tzinfo is None:
            before = before.replace(tzinfo=timezone.utc)
        now = max(now, before + timedelta(microseconds=1))
    return now.isoformat()


class ResourceStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def read(self):
        if not self.path.exists():
            return {}
        data = json.loads(self.path.read_text('utf-8'))
        if not isinstance(data, dict):
            raise ValueError(f'资源存储损坏: {self.path.name}')
        return data

    @contextmanager
    def writing(self):
        with self._lock, self.path.with_suffix('.lock').open('a+') as handle:
            with exclusive_lock(handle):
                data = self.read()
                yield data
                fd, temporary = tempfile.mkstemp(dir=self.path.parent, prefix='.pending-')
                try:
                    with os.fdopen(fd, 'w', encoding='utf-8') as output:
                        json.dump(data, output, ensure_ascii=False, indent=2, allow_nan=False)
                        output.flush()
                        os.fsync(output.fileno())
                    os.replace(temporary, self.path)
                finally:
                    Path(temporary).unlink(missing_ok=True)

    def get(self, key):
        return copy.deepcopy(self.read().get(key))

    def list_all(self):
        return list(self.read().values())


class ResourceConflictError(ValueError):
    """An editor attempted to overwrite a newer persisted resource revision."""
