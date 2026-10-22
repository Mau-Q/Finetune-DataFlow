"""Presentation metadata for file manifests; registry type stays the storage format."""
import json
from functools import lru_cache
from pathlib import Path

from app.services.data_library import IMAGE_TYPES

MAX_MANIFEST_BYTES = 2 * 1024 * 1024


def _file_kind(source):
    if not isinstance(source, str):
        return None
    suffix = Path(source).suffix.lower()
    if suffix == '.pdf':
        return 'pdf'
    if suffix in IMAGE_TYPES:
        return 'image'
    if suffix in {'.txt', '.md'}:
        return 'text'
    if suffix in {'.json', '.jsonl', '.csv', '.parquet'}:
        return 'structured'
    return None


@lru_cache(maxsize=256)
def _manifest_summary(path, modified_ns, size):
    # Bound list-page work, and inspect every row rather than guessing from a sample.
    if size > MAX_MANIFEST_BYTES:
        return None, None
    with Path(path).open('rb') as handle:
        content = handle.read(MAX_MANIFEST_BYTES + 1)
    if len(content) > MAX_MANIFEST_BYTES:
        return None, None
    kinds = set()
    count = 0
    for line in content.decode('utf-8-sig').splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or set(row) - {'source', 'source_name', 'material_id'}:
            return None, None
        kind = _file_kind(row.get('source'))
        if not kind:
            return None, None
        kinds.add(kind)
        count += 1
    if not count:
        return None, None
    kind = 'pdf_image' if kinds == {'pdf', 'image'} else 'mixed' if len(kinds) > 1 else next(iter(kinds))
    return kind, count


def annotate_content(record):
    result = dict(record, content_type=None, file_count=None)
    path = Path(record['root'])
    try:
        stat = path.stat()
        kind = _file_kind(str(path))
        if kind in {'pdf', 'image', 'text'}:
            result.update(content_type=kind, file_count=1)
        elif path.suffix.lower() == '.jsonl':
            kind, count = _manifest_summary(str(path), stat.st_mtime_ns, stat.st_size)
            result.update(content_type=kind, file_count=count)
    except (OSError, ValueError, UnicodeError):
        # A missing, invalid or unrecognized file must not break the whole catalog.
        pass
    return result
