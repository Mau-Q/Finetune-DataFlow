"""Read-only catalogs of owned resources and actual saved-flow usage."""
import copy
from app.core.container import container
from app.services.builtin_resources import builtin_schemas
from app.services.dataset_visibility import visibility_settings
from app.services.resource_store import ResourceStore
from app.services.user_prompt_registry import _extract_placeholders
from app.services.prompt_contracts import CONTRACTS, validate_managed_template

TEXT_SFT = {'KnowledgeCleanerPrompt', 'Text2MultiHopQAGeneratorPrompt', 'Text2QAQuestionQualityPrompt',
            'Text2QAAnswerAlignmentPrompt', 'Text2QAAnswerVerifiabilityPrompt', 'Text2QADownstreamValuePrompt', 'AlpagasusPrompt'}


PROMPT_LABELS = {
    'KnowledgeCleanerPrompt': '文本清洗',
    'Text2MultiHopQAGeneratorPrompt': '多跳 QA 生成',
    'Text2QAQuestionQualityPrompt': '问题质量评分',
    'Text2QAAnswerAlignmentPrompt': '答案对齐评分',
    'Text2QAAnswerVerifiabilityPrompt': '答案可验证性评分',
    'Text2QADownstreamValuePrompt': '下游价值评分',
    'AlpagasusPrompt': 'Alpagasus 质量评分',
}
# Verified against the corresponding core operator constructors / _build_prompts.
# This is actual execution behavior, not the registry's allowed-prompts list.
OPERATOR_PROMPTS = {
    'KBCTextCleaner': ('operator_default', ['KnowledgeCleanerPrompt'], {'lang': 'en'}),
    'Text2MultiHopQAGenerator': ('operator_default', ['Text2MultiHopQAGeneratorPrompt'], {'lang': 'en'}),
    'Text2QASampleEvaluator': ('operator_default', [
        'Text2QAQuestionQualityPrompt', 'Text2QAAnswerAlignmentPrompt',
        'Text2QAAnswerVerifiabilityPrompt', 'Text2QADownstreamValuePrompt'], {}),
    'AlpagasusSampleEvaluator': ('operator_default', ['AlpagasusPrompt'], {'dimension': 'quality'}),
}


def _value(param):
    return param.get('value') if param.get('value') is not None else param.get('default_value')


def _safe(value):
    """Do not echo credentials when presenting saved operator parameters."""
    if isinstance(value, dict):
        secret_keys = {'api_key', 'password', 'secret', 'token', 'access_token', 'authorization'}
        named_secret = str(value.get('name', '')).lower() in secret_keys
        return {k: '[已隐藏]' if str(k).lower() in secret_keys or
                (named_secret and k in {'value', 'default_value'}) else _safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_safe(v) for v in value]
    return copy.deepcopy(value)


def _sections(op):
    raw = op.get('params') or {}
    if isinstance(raw, dict) and ('init' in raw or 'run' in raw):
        return {section: _safe({p['name']: _value(p) for p in values}) if isinstance(values, list)
                else _safe(values) for section in ('init', 'run') if (values := raw.get(section))}
    return {'init': _safe({p['name']: _value(p) for p in _params(op)})}


def _constructor(value):
    if not isinstance(value, dict):
        return {}
    params = value.get('params')
    return _safe({p['name']: _value(p) for p in params}) if isinstance(params, list) else _safe(params or {})


def _params(op):
    raw = op.get('params') or {}
    if isinstance(raw, list):
        return raw
    if 'init' in raw or 'run' in raw:
        result = []
        for values in (raw.get('init') or [], raw.get('run') or []):
            result.extend([{'name': k, 'value': v} for k, v in values.items()] if isinstance(values, dict) else values)
        return result
    return [{'name': k, 'value': v} for k, v in raw.items()]


def _reference(value):
    if isinstance(value, dict):
        return value.get('ref')
    return value if isinstance(value, str) and value.startswith(('user_prompt:', 'schema_ref:', 'builtin:')) else None


class ResourceCatalog:
    def __init__(self, app_container=None):
        self.c = app_container or container

    def _pipelines(self):
        from app.services.text_generation import template as text_template
        from app.services.multimodal_templates import template as mm_template
        records = []
        if self.c.pipeline_registry:
            records = [dict(p, source='builtin' if self.c.pipeline_registry._is_preset_pipeline(p) else 'user', catalog_id='pipeline:' + p['id'], route={'path': '/m/', 'query': {'pipeline': p['id']}})
                       for p in self.c.pipeline_registry.list_pipelines()]
        text = text_template()
        records.append(dict(text, source='builtin', id='text-sft-template', catalog_id='template:text-sft', route={'path': '/m/generation'}))
        mm = mm_template()
        records.append(dict(mm, source='builtin', id='image-sft-template', catalog_id='template:image-sft', route={'path': '/m/multimodal'}))
        if self.c.data_library:
            path = self.c.data_library.root / 'multimodal_configs.json'
            # Reading the catalog never creates a config file.
            if path.is_file():
                for p in ResourceStore(path).list_all():
                    records.append(dict(p, source='user', catalog_id='multimodal:' + p['id'], route={'path': '/m/multimodal', 'query': {'config': p['id']}}))
        return records

    def _finish(self, resources):
        pipelines = self._pipelines()
        by_ref = {r['ref']: r for r in resources}
        mm_schema = by_ref.get('schema_ref:builtin-mm-qa-v1')
        if mm_schema:
            by_ref['builtin:mm-qa-schema-v1'] = mm_schema
        from app.services.resource_resolution import SCHEMA_PARAMS
        options = []
        for pipeline in pipelines:
            config = pipeline.get('config') or {}
            operators = config.get('operators') or []
            steps = config.get('steps') or []
            op_names = [op['name'] for op in operators] + [s['kind'].split(':')[-1] for s in steps]
            schema_ops = []
            for op in operators:
                declared = [p['name'] for p in _params(op)]
                if self.c.operator_registry:
                    details = self.c.operator_registry.get_op_details(op['name']) or {}
                    declared += [p['name'] for section in ('init', 'run') for p in details.get('parameter', {}).get(section, [])]
                if any(name in SCHEMA_PARAMS or name.endswith('_schema') for name in declared):
                    schema_ops.append(op['name'])
            if any(s['id'] == 'validate' for s in steps):
                schema_ops.append('platform:validate')
            family = 'image-sft' if steps and any(s['kind'].startswith('mm:') for s in steps) else 'text-sft' if ('platform-text' in pipeline.get('tags', []) or any(op['name'] in {'Text2MultiHopQAGenerator', 'Text2QASampleEvaluator'} for op in operators) or pipeline['catalog_id'] == 'template:text-sft') else None
            origin = 'platform_template' if pipeline['catalog_id'].startswith('template:') else 'preset' if pipeline['source'] == 'builtin' else 'custom'
            options.append({'family': family, 'origin': origin, 'source': pipeline['source'], 'schema_operators': schema_ops, 'id': pipeline['catalog_id'], 'name': pipeline['name'], 'operators': op_names, 'route': pipeline['route']})
            def attach(ref, step, field, bindings=None, kind='explicit', parameters=None, evidence=None):
                target = by_ref.get(ref)
                if target is None:
                    return
                usage = {'pipeline_id': pipeline['catalog_id'], 'pipeline_name': pipeline['name'],
                         'pipeline_source': pipeline['source'], 'step': step, 'field': field,
                         'bindings': _safe(bindings or {}), 'route': pipeline['route'],
                         'kind': kind, 'parameters': _safe(parameters or {}), 'evidence': evidence}
                if usage not in target['references']:
                    target['references'].append(usage)
            for index, op in enumerate(operators):
                step_name = f"{index + 1}. {op['name']}"
                params = _params(op)
                for param in params:
                    value = _value(param)
                    ref = _reference(value)
                    if ref:
                        attach(ref, step_name, param['name'], value.get('bindings') if isinstance(value, dict) else None,
                               parameters={'operator': _sections(op)})
                    elif param.get('name') == 'prompt_template':
                        cls = value.get('cls_name') if isinstance(value, dict) else value
                        if isinstance(cls, str):
                            if "<class '" in cls:
                                cls = cls.split("'")[1].split('.')[-1]
                            attach('builtin_prompt:' + cls, step_name, 'prompt_template',
                                   parameters={'constructor': _constructor(value), 'operator': _sections(op)})
                contracts = CONTRACTS.get(op['name'], {})
                for field, contract in contracts.items():
                    chosen = next((_value(p) for p in params if p['name']==field), None)
                    if not chosen:
                        init = _sections(op).get('init', {})
                        constructor = {key:init.get(key) or default for key,default in OPERATOR_PROMPTS.get(op['name'], ('',[],{}))[2].items()}
                        attach('builtin_prompt:'+contract['builtin'], step_name, field, kind='operator_default',
                               parameters={'constructor':constructor,'operator':_sections(op)}, evidence=op['name']+'.__init__ / _build_prompts')
            for step in steps:
                attach(step.get('resource_ref'), step['id'], 'resource_ref', step.get('bindings'),
                       parameters={key: step[key] for key in ('inputs', 'output', 'bindings', 'resource_ref') if key in step})
        for resource in resources:
            resource['personal'] = resource['source'] == 'user' or any(
                r['pipeline_source'] == 'user' for r in resource['references'])
        return {'resources': resources, 'pipelines': options,
                'reference_scope': '使用记录来自已保存流程的显式绑定及已核实的算子默认/固定 Prompt；表示配置用法，不表示已运行。'}

    def prompts(self):
        records = []
        for item in self.c.user_prompt_registry.list_all():
            operators = []
            for op, slots in CONTRACTS.items():
                for field in slots:
                    try:
                        validate_managed_template(op, field, item['template'])
                        operators.append(op)
                        break
                    except ValueError:
                        pass
            if set(_extract_placeholders(item['template'])) <= {'question'}:
                operators.append('PromptedVQAGenerator')
            allowed = item.get('allowed_operators') or []
            if allowed:
                operators = [op for op in operators if op in allowed]
            records.append(dict(copy.deepcopy(item), source='user', readonly=False, kind='text', ref='user_prompt:' + item['id'],
                                usages=[item.get('usage', '通用')], purpose=item.get('purpose', '通用'), operators=operators,
                                variables=_extract_placeholders(item['template']), references=[]))
        info = self.c.prompt_registry.list_prompt_info().model_dump()['prompts'] if self.c.prompt_registry else {}
        for name, item in info.items():
            usage = '文本 SFT' if name in TEXT_SFT or item['primary_type'] == 'text_sft' else '通用'
            records.append({'id': name, 'name': PROMPT_LABELS.get(name, name), 'source': 'builtin', 'readonly': True, 'kind': 'python',
                            'ref': 'builtin_prompt:' + name, 'description': item['description'], 'usages': [usage],
                            'purpose': '清洗' if name == 'KnowledgeCleanerPrompt' else '评分' if name in TEXT_SFT - {'KnowledgeCleanerPrompt', 'Text2MultiHopQAGeneratorPrompt'} else '生成' if name == 'Text2MultiHopQAGeneratorPrompt' else '通用',
                            'operators': item['operator'], 'variables': [p['name'] for p in item['parameter']['build_prompt']],
                            'parameters': item['parameter'], 'class_path': item['class_str'], 'references': []})
        from app.services.multimodal_templates import QUESTION, ANSWER
        for key, name, text in [('mm-question-v1', '图片 SFT · 生成问题', QUESTION), ('mm-answer-v1', '图片 SFT · 回答问题', ANSWER)]:
            records.append({'id': key, 'name': name, 'source': 'builtin', 'readonly': True, 'kind': 'text', 'ref': 'builtin:' + key,
                            'description': '图片 VQA 流程的内置文本 Prompt；复制后可在图片流程中绑定自己的模板。',
                            'usages': ['图文 SFT'], 'purpose': '生成', 'operators': ['PromptedVQAGenerator'],
                            'template': text, 'variables': _extract_placeholders(text), 'references': [], 'version': 'v1'})
        hidden = set(visibility_settings().get('hidden_prompt_ids', []))
        return self._finish([r for r in records if r['id'] not in hidden])

    def schemas(self):
        records = []
        for item in self.c.json_schema_manager.list_all() + builtin_schemas():
            own = item.get('source') != 'builtin'
            records.append(dict(copy.deepcopy(item), source='user' if own else 'builtin', readonly=not own,
                                ref='schema_ref:' + item['id'], resource_kind='schema', usages=[item.get('usage', '通用')],
                                purpose=item.get('purpose', '通用'), operators=[], references=[]))
        return self._finish(records)
