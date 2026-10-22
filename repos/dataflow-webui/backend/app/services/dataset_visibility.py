"""Local display preferences. Hidden records remain available by ID to pipelines."""
import json
from pathlib import Path
from app.core.config import settings


def visibility_settings():
    path = Path(settings.BASE_DIR) / settings.RESOURCE_DIR / 'dataset_visibility.json'
    if not path.exists():
        return {}
    return json.loads(path.read_text('utf-8'))


def annotate_datasets(records):
    hidden = set(visibility_settings().get('hidden_dataset_ids', []))
    return [dict(record, is_visible=record['id'] not in hidden) for record in records]


def visible_drafts(records):
    hidden = set(visibility_settings().get('hidden_draft_ids', []))
    return [record for record in records if record['id'] not in hidden]
