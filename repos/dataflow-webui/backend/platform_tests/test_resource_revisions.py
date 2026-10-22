"""Revision preconditions must work with Windows' coarse wall clock."""
from datetime import datetime, timezone, timedelta
import unittest
from unittest.mock import patch

from app.services.resource_store import next_updated_at


class RevisionTests(unittest.TestCase):
    def test_frozen_or_backward_clock_cannot_reuse_revision(self):
        previous = datetime(2026, 1, 1, tzinfo=timezone.utc)
        class Clock(datetime):
            @classmethod
            def now(cls, tz):
                return previous - timedelta(seconds=1)
        with patch('app.services.resource_store.datetime', Clock):
            for stamp in (previous.isoformat(), previous.replace(tzinfo=None).isoformat()):
                updated = next_updated_at(stamp)
                self.assertGreater(datetime.fromisoformat(updated), previous)
                self.assertGreater(datetime.fromisoformat(next_updated_at(updated)), datetime.fromisoformat(updated))
