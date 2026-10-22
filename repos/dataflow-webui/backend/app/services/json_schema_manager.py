"""JSON Schema resources, validated on the server and atomically persisted."""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from jsonschema import validators, exceptions
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7, DRAFT201909, DRAFT202012
from referencing.exceptions import NoSuchResource, Unresolvable
from app.core.config import settings
from app.services.resource_store import ResourceStore, ResourceConflictError, next_updated_at

BACKEND_DIR = Path(__file__).parent.parent.parent
SCHEMAS_DIR = BACKEND_DIR / settings.RESOURCE_DIR / "schemas"
SCHEMAS_FILE = SCHEMAS_DIR / "schemas.json"


def _no_remote(uri):
    raise NoSuchResource(ref=uri)


def validate_schema(schema, example=''):
    try:
        def strict_load(text):
            return json.loads(text, parse_constant=lambda v: (_ for _ in ()).throw(ValueError(f'非法 JSON 数值: {v}')))
        parsed = strict_load(schema) if isinstance(schema, str) else schema
        if not isinstance(parsed, (dict, bool)):
            raise ValueError('Schema 必须是 JSON 对象或布尔值')
        dialect = parsed.get('$schema') if isinstance(parsed, dict) else None
        known = {v.META_SCHEMA['$id'].rstrip('#'): v for v in
                 (validators.Draft7Validator, validators.Draft201909Validator, validators.Draft202012Validator)}
        if dialect is not None and not isinstance(dialect, str):
            raise ValueError('$schema 必须是字符串')
        if dialect and dialect.rstrip('#') not in known:
            raise ValueError('支持 JSON Schema draft-07、2019-09 和 2020-12')
        cls = known[dialect.rstrip('#')] if dialect else validators.Draft202012Validator
        cls.check_schema(parsed)
        registry = Registry(retrieve=_no_remote)
        spec = {validators.Draft7Validator: DRAFT7, validators.Draft201909Validator: DRAFT201909, validators.Draft202012Validator: DRAFT202012}[cls]
        resource = Resource.from_contents(parsed, default_specification=spec)
        def check_refs(resource, resolver):
            if isinstance(resource.contents, dict):
                for key in ('$ref', '$dynamicRef'):
                    ref = resource.contents.get(key)
                    if isinstance(ref, str):
                        if not ref.startswith('#'):
                            raise ValueError('Schema 引用仅支持文档内 # 引用，不加载外部资源')
                        resolver.lookup(ref)
            for child in resource.subresources():
                check_refs(child, resolver.in_subresource(child))
        check_refs(resource, registry.resolver_with_root(resource))
        validator = cls(parsed, registry=registry)
        if example and example.strip():
            validator.validate(strict_load(example))
        return parsed
    except (exceptions.SchemaError, exceptions.ValidationError) as exc:
        raise ValueError(f'Schema 校验失败: {exc.message}') from exc
    except (json.JSONDecodeError, Unresolvable, exceptions._WrappedReferencingError, RecursionError) as exc:
        raise ValueError(f'Schema 或示例无效: {exc}') from exc


class JsonSchemaManager:
    def __init__(self, path=None):
        self.store = ResourceStore(path or SCHEMAS_FILE)
        self.store.read()

    def create(self, name, description, schema, example, usage='通用', purpose='通用'):
        validate_schema(schema, example)
        if not name.strip():
            raise ValueError('Schema 名称不能为空')
        now = datetime.now(timezone.utc).isoformat()
        rec = dict(id=f'schema_{uuid.uuid4().hex[:8]}', name=name, description=description or '',
                   schema=schema, example=example or '', usage=usage, purpose=purpose, created_at=now, updated_at=now)
        with self.store.writing() as data:
            data[rec['id']] = rec
        return rec

    def get(self, schema_id):
        from app.services.builtin_resources import get_builtin_schema
        return get_builtin_schema(schema_id) if schema_id.startswith('builtin-') else self.store.get(schema_id)

    def list_all(self):
        return self.store.list_all()

    def update(self, schema_id, **fields):
        if schema_id.startswith('builtin-'):
            return None
        with self.store.writing() as data:
            if schema_id not in data:
                return None
            rec = data[schema_id]
            expected = fields.get('expected_updated_at')
            if expected is not None and expected != rec.get('updated_at'):
                raise ResourceConflictError('资源已在其他页面修改；请取消编辑后重新打开，当前输入已保留。')
            for key in ('name', 'description', 'schema', 'example', 'usage', 'purpose'):
                if fields.get(key) is not None:
                    rec[key] = fields[key]
            if not rec['name'].strip():
                raise ValueError('Schema 名称不能为空')
            validate_schema(rec['schema'], rec.get('example', ''))
            rec['updated_at'] = next_updated_at(rec.get('updated_at'))
        return rec

    def delete(self, schema_id):
        if schema_id.startswith('builtin-'):
            return False
        with self.store.writing() as data:
            return data.pop(schema_id, None) is not None

    def delete_by_name(self, name):
        with self.store.writing() as data:
            ids = [key for key, rec in data.items() if rec['name'] == name]
            for key in ids:
                del data[key]
        return bool(ids)
