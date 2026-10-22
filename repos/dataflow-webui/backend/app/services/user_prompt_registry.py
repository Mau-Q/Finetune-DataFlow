"""User templates stay independent of the built-in PROMPT_REGISTRY."""
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from app.core.config import settings
from app.services.resource_store import ResourceStore, ResourceConflictError, next_updated_at

BACKEND_DIR = Path(__file__).parent.parent.parent
PROMPTS_DIR = BACKEND_DIR / settings.RESOURCE_DIR / "prompts"
PROMPTS_FILE = PROMPTS_DIR / "user_templates.json"
# Only simple identifiers are variables. JSON objects remain literal, including
# nested objects. Double braces escape a literal brace, as in Python format.
_TOKEN = re.compile(r'\{\{|\}\}|\{([A-Za-z_][A-Za-z0-9_]*)\}')


def _extract_placeholders(template):
    return list(dict.fromkeys(m.group(1) for m in _TOKEN.finditer(template or '') if m.group(1)))


def render_template(template, variables):
    placeholders = _extract_placeholders(template)
    missing = [p for p in placeholders if p not in variables]
    escaped = 0
    def replace(match):
        nonlocal escaped
        if match.group(0) == '{{':
            escaped += 1
            return '{'
        if match.group(0) == '}}':
            if escaped:
                escaped -= 1
                return '}'
            return '}}'
        key = match.group(1)
        return str(variables[key]) if key in variables else match.group(0)
    return {'rendered': _TOKEN.sub(replace, template), 'placeholders': placeholders, 'missing': missing}


class UserPromptRegistry:
    def __init__(self, path=None):
        self.store = ResourceStore(path or PROMPTS_FILE)
        self.store.read()  # Corruption must be reported, never replaced by {}.

    def _validate(self, rec):
        if not rec['name'].strip() or not rec['template'].strip():
            raise ValueError('模板名称和内容不能为空')
        # Reject Python field traversal/conversions; JSON braces are literal.
        if re.search(r'\{[A-Za-z_][A-Za-z0-9_]*(?:[.!\[]|:[^{}]*\})', rec['template']):
            raise ValueError('只支持 {变量名}，不支持属性访问、转换或格式说明')

    def create(self, name, description, template, allowed_operators=None, example_variables=None, usage='通用', purpose='通用'):
        now = datetime.now(timezone.utc).isoformat()
        rec = dict(id=f'tpl_{uuid.uuid4().hex[:8]}', name=name, description=description or '', usage=usage, purpose=purpose,
                   template=template, allowed_operators=list(allowed_operators or []),
                   example_variables=dict(example_variables or {}), created_at=now, updated_at=now)
        self._validate(rec)
        with self.store.writing() as data:
            data[rec['id']] = rec
        return rec

    def get(self, tpl_id):
        return self.store.get(tpl_id)

    def list_all(self):
        return self.store.list_all()

    def update(self, tpl_id, **fields):
        with self.store.writing() as data:
            if tpl_id not in data:
                return None
            rec = data[tpl_id]
            expected = fields.get('expected_updated_at')
            if expected is not None and expected != rec.get('updated_at'):
                raise ResourceConflictError('资源已在其他页面修改；请取消编辑后重新打开，当前输入已保留。')
            for key in ('name', 'description', 'template', 'allowed_operators', 'example_variables', 'usage', 'purpose'):
                if fields.get(key) is not None:
                    rec[key] = fields[key]
            self._validate(rec)
            rec['updated_at'] = next_updated_at(rec.get('updated_at'))
        return rec

    def delete(self, tpl_id):
        with self.store.writing() as data:
            return data.pop(tpl_id, None) is not None

    def preview(self, template, variables):
        return render_template(template, variables)

    def get_template_text(self, tpl_id):
        rec = self.get(tpl_id)
        return rec['template'] if rec else None
