"""Shared resource resolution for validation, task freezing and both executors.

Managed slots declare fixed input/output protocols; built-in defaults remain compatible.
"""
import copy
import hashlib
import json
from app.core.container import container
from app.services.json_schema_manager import validate_schema
from app.services.prompt_contracts import CONTRACTS, validate_managed_template
from app.services.user_prompt_registry import _extract_placeholders, render_template

SCHEMA_PARAMS = {'schema', 'json_schema', 'output_schema', 'response_schema',
                 'structured_output_schema', 'response_format_schema'}


class ResourceReferenceError(ValueError):
    pass


def content_hash(content):
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _ref(value):
    candidate = value.get('ref') if isinstance(value, dict) else value
    return candidate if isinstance(candidate, str) and candidate.startswith(('user_prompt:', 'schema_ref:')) else None


def _items(params):
    if isinstance(params, dict):
        return [{'name': k, 'value': v} for k, v in params.items()]
    return copy.deepcopy(params or [])


def _sections(op, operator_registry):
    raw = op.get('params') or {}
    details = operator_registry.get_op_details(op['name']) or {}
    definitions = details.get('parameter', {})
    init_names = {p['name'] for p in definitions.get('init', [])}
    if isinstance(raw, dict) and ('init' in raw or 'run' in raw):
        sections = {section: _items(raw.get(section)) for section in ('init', 'run')}
    else:
        sections = {'init': [], 'run': []}
        for item in _items(raw):
            sections['init' if item['name'] in init_names else 'run'].append(item)
    for section, items in sections.items():
        kinds = {p['name']: p.get('kind') for p in definitions.get(section, [])}
        for item in items:
            if kinds.get(item['name']):
                item.setdefault('kind', kinds[item['name']])
    return sections


def _bindings(run):
    mapping = {}
    for item in run:
        if item['name'] in ('storage', 'output_key'):
            continue
        value = item.get('value')
        if item['name'] == 'input_keys' or item.get('kind') == 'VAR_KEYWORD':
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except ValueError:
                    raise ResourceReferenceError('模板字段绑定必须是 JSON 对象或键值列表')
            for pair in _items(value):
                key = pair.get('name') or pair.get('key')
                if not isinstance(key, str) or not key or key in mapping:
                    raise ResourceReferenceError('模板字段绑定名称为空或重复')
                mapping[key] = pair.get('value')
        else:
            mapping[item['name']] = value
    return mapping


def resolve_pipeline_resources(config):
    """Return a detached executable config and frozen content+hash records.

    Resolve every resource once per submission; repeated references share the
    same captured record. Never write resolved text into the Pipeline registry.
    """
    result = copy.deepcopy(config)
    snapshots, captured = [], {}
    operator_registry = container.operator_registry
    for index, op in enumerate(result.get('operators', [])):
        # Native text controls serialize untouched optional fields as empty strings.
        # Normalize only verified SFT optional slots; required field names stay strict.
        raw = op.get('params') or {}
        if (op['name'] in CONTRACTS or op['name'] in {'TrainingReviewParser', 'HashDeduplicateFilter', 'TrainingPairFormatter'}) and isinstance(raw, dict) and ('init' in raw or 'run' in raw):
            normalized = {part:_items(raw.get(part)) for part in ('init','run')}
            optional = {'init': {'llm_serving', *CONTRACTS.get(op['name'], {}), *SCHEMA_PARAMS}, 'run': set()}
            if op['name'] == 'Text2QASampleEvaluator':
                optional['run'] = {'input_context_key', 'input_supporting_facts_key'}
            if op['name'] == 'APIImagePairGenerator':
                optional['run'] = {'input_context_key'}
            if op['name'] == 'TrainingReviewParser':
                optional['run'] = {'input_question_key'}
            if op['name'] == 'HashDeduplicateFilter':
                optional['run'] = {'input_key', 'input_keys'}
            changed = False
            for part, names in optional.items():
                for param in normalized[part]:
                    if param['name'] in names and param.get('value') == '':
                        param['value'] = None
                        changed = True
            # Frozen/inline adapters obey the same slot contract as managed refs.
            if op['name'] != 'FormatStrPromptedGenerator':
                init_values = {p['name']: p.get('value', p.get('default_value')) for p in normalized['init']}
                for part, params in normalized.items():
                    for param in params:
                        value = param.get('value')
                        if isinstance(value, dict) and 'resource_template' in value:
                            if part != 'init':
                                raise ResourceReferenceError('Prompt 只能绑定到构造参数')
                            try:
                                validate_managed_template(op['name'], param['name'], value['resource_template'], value.get('bindings'))
                            except ValueError as exc:
                                raise ResourceReferenceError(str(exc)) from exc
                            value.update(contract_operator=op['name'], contract_param=param['name'], lang=value.get('lang') or init_values.get('lang') or 'en')
                            changed = True
            if changed:
                op['params'] = normalized
        raw = op.get('params') or {}
        candidates = _items(raw.get('init')) + _items(raw.get('run')) if isinstance(raw, dict) and ('init' in raw or 'run' in raw) else _items(raw)
        has_schema = any(p.get('name') in SCHEMA_PARAMS and p.get('value') not in (None, '') for p in candidates)
        if not any(_ref(p.get('value')) for p in candidates) and not has_schema:
            continue
        if operator_registry is None:
            # Ray workers import a fresh AppContainer, without the web app's
            # startup lifecycle. Frozen prompts/schemas still need signatures,
            # but must not initialize stores, scan datasets or seed templates.
            from app.services.operator_registry import OperatorRegistry
            operator_registry = OperatorRegistry()
        sections = _sections(op, operator_registry)
        details = operator_registry.get_op_details(op['name']) or {}
        declared = {section: {p['name'] for p in details.get('parameter', {}).get(section, [])}
                    for section in ('init', 'run')}
        for section, params in sections.items():
            for item in params:
                value = item.get('value')
                ref = _ref(value)
                if not ref:
                    if item['name'] in SCHEMA_PARAMS and value is not None and value != '':
                        try:
                            validate_schema(value)
                        except ValueError as exc:
                            raise ResourceReferenceError(f"{op['name']}.{item['name']}: {exc}") from exc
                    continue
                name = item['name']
                if name not in declared[section]:
                    raise ResourceReferenceError(f"{op['name']}.{name}: 算子没有此参数契约")
                prefix, resource_id = ref.split(':', 1)
                if ref not in captured:
                    manager = container.user_prompt_registry if prefix == 'user_prompt' else container.json_schema_manager
                    record = manager.get(resource_id) if manager and resource_id else None
                    if record is None:
                        raise ResourceReferenceError(f'资源引用不存在: {ref}')
                    captured[ref] = copy.deepcopy(record)
                record = captured[ref]
                if prefix == 'user_prompt':
                    if section != 'init':
                        raise ResourceReferenceError('Prompt 只能绑定到构造参数')
                    try:
                        validate_managed_template(op['name'], name, record['template'], value.get('bindings') if isinstance(value, dict) else None)
                    except ValueError as exc:
                        raise ResourceReferenceError(str(exc)) from exc
                    allowed = record.get('allowed_operators') or []
                    if allowed and op['name'] not in allowed:
                        raise ResourceReferenceError(f"模板未允许算子 {op['name']}")
                    if op['name'] == 'FormatStrPromptedGenerator' and isinstance(value, dict) and 'bindings' in value:
                        binding = value['bindings']
                        if not isinstance(binding, dict) or not all(isinstance(k, str) and isinstance(v, str) and v.strip() for k, v in binding.items()):
                            raise ResourceReferenceError('模板绑定必须是 变量名 → 非空数据列名')
                        if any(k in ('storage', 'output_key', 'input_keys') for k in binding):
                            raise ResourceReferenceError('模板变量不能使用 storage、output_key 或 input_keys')
                        sections['run'] = [p for p in sections['run'] if p['name'] != 'input_keys']
                        sections['run'].append({'name': 'input_keys', 'kind': 'VAR_KEYWORD', 'value': _items(binding)})
                    binding = _bindings(sections['run'])
                    required = _extract_placeholders(record['template']) if op['name'] == 'FormatStrPromptedGenerator' else []
                    missing = [p for p in required if not isinstance(binding.get(p), str) or not binding[p].strip()]
                    if missing:
                        raise ResourceReferenceError('模板缺少变量绑定: ' + ', '.join(missing))
                    # Do not allow arbitrary kwargs to shadow named run parameters.
                    if any(k in ('storage', 'output_key', 'input_keys') for k in binding):
                        raise ResourceReferenceError('模板变量不能使用 storage、output_key 或 input_keys')
                    if not record['template'].strip():
                        raise ResourceReferenceError('模板内容不能为空')
                    init_values = {p['name']: p.get('value', p.get('default_value')) for p in sections['init']}
                    content = {'template': record['template']}
                    if op['name'] != 'FormatStrPromptedGenerator':
                        content.update(contract_operator=op['name'], contract_param=name,
                                       lang=init_values.get('lang') or 'en')
                    item['value'] = {'cls_name': 'FormatStrPrompt', 'resource_template': record['template'], **{k:v for k,v in content.items() if k!='template'}}
                else:
                    if name not in SCHEMA_PARAMS and not name.endswith('_schema'):
                        raise ResourceReferenceError(f'{name}: 不是声明结构输出的 Schema 参数')
                    try:
                        content = validate_schema(record['schema'])
                    except ValueError as exc:
                        raise ResourceReferenceError(f'{ref}: {exc}') from exc
                    item['value'] = content
                snapshots.append({'operator_index': index, 'operator_name': op['name'],
                                  'section': section, 'param_name': name, 'ref': ref,
                                  'name': record['name'], 'updated_at': record.get('updated_at'),
                                  'content': copy.deepcopy(content), 'sha256': content_hash(content)})
        op['params'] = sections
    return result, snapshots


def instantiate_prompt(value):
    """Common constructor, preserving built-in registry semantics."""
    from dataflow.utils.registry import PROMPT_REGISTRY
    if isinstance(value, dict) and 'resource_template' in value:
        if value.get('contract_operator'):
            return instantiate_contracted_prompt(value)
        from dataflow.core.prompt import DIYPromptABC
        class ResourceTemplatePrompt(DIYPromptABC):
            def build_prompt(self, need_fields, **kwargs):
                rendered = render_template(value['resource_template'], kwargs)
                if rendered['missing']:
                    raise ResourceReferenceError('模板缺少变量: ' + ', '.join(rendered['missing']))
                return rendered['rendered']
        return ResourceTemplatePrompt()
    if isinstance(value, dict):
        cls_name = value.get('cls_name', 'FormatStrPrompt')
        kwargs = {p['name']: p.get('value') if p.get('value') is not None else p.get('default_value')
                  for p in value['params']} if 'params' in value else {k: v for k, v in value.items() if k != 'cls_name'}
    else:
        cls_name, kwargs = value, {}
    if isinstance(cls_name, str) and "<class '" in cls_name:
        cls_name = cls_name.split("'")[1].split('.')[-1]
    cls = PROMPT_REGISTRY.get(cls_name)
    if not cls:
        raise ResourceReferenceError(f'Prompt class not found: {cls_name}')
    return cls(**kwargs)


def instantiate_contracted_prompt(value):
    from dataflow.core.prompt import DIYPromptABC
    operator, param = value['contract_operator'], value['contract_param']
    validate_managed_template(operator, param, value['resource_template'])
    class ContractPrompt(DIYPromptABC):
        def build_prompt(self, text=None):
            result = render_template(value['resource_template'], {'text': text} if text is not None else {})
            if result['missing']:
                raise ResourceReferenceError('模板缺少变量: ' + ', '.join(result['missing']))
            rendered = result['rendered']
            if operator == 'KBCTextCleaner':
                rendered += '\nReturn only cleaned source text between <cleaned_start> and <cleaned_end>. Preserve facts; do not invent content.'
            elif operator == 'Text2MultiHopQAGenerator':
                rendered += '\nReturn a JSON object with nonempty question and answer strings, reasoning_steps array of step objects, supporting_facts array of source quotations, and type string. Use only the provided context.'
            return rendered
        def build_system_prompt(self):
            from dataflow.prompts.text2qa import Text2MultiHopQAGeneratorPrompt
            return Text2MultiHopQAGeneratorPrompt(lang=value.get('lang','en')).build_system_prompt()
    return ContractPrompt()
