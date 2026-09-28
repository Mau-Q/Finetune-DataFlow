"""Vendored exact source segments; see vendor_manifest.json."""
from __future__ import annotations
import re


WORD_COMPAT_UNIT_RE = re.compile(
    r"[\u3400-\u4dbf\u4e00-\u9fff]|[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*"
)


def word_compatible_mixed_count(*parts: str) -> int:
    """Count CJK characters and contiguous Latin/number words deterministically."""

    return len(WORD_COMPAT_UNIT_RE.findall("\n".join(parts)))
