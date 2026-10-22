"""Configuration-only MM boundary. Never import MM or dispatch the core executor."""
import copy
import uuid
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from app.core.container import container
from app.services.data_library import LibraryError, _now
from app.services.resource_store import ResourceStore
from app.services.user_prompt_registry import _extract_placeholders
from app.services.json_schema_manager import validate_schema

QUESTION = 'Look at the image and write one specific question answerable from visible evidence. Return only the question.'
ANSWER = 'Answer the following question using only visible evidence in the image. If evidence is insufficient, say so. Question: {question}'
SAMPLE_SCHEMA = {'type': 'object', 'required': ['question', 'answer'], 'properties': {'question': {'type': 'string', 'minLength': 1}, 'answer': {'type': 'string', 'minLength': 1}}}


class Step(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    id: Literal['question', 'answer', 'validate', 'format']
    kind: Literal['mm:PromptedVQAGenerator', 'platform:validate', 'platform:messages']
    inputs: dict[str, str]
    output: str = Field(pattern=r'^[A-Za-z_][A-Za-z0-9_]*$')
    resource_ref: str
    bindings: dict[str, str] = Field(default_factory=dict)
    x: int = Field(ge=0, le=2000)
    y: int = Field(ge=0, le=1000)


class MMConfig(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    template_id: Literal['mm-image-vqa-v1'] = 'mm-image-vqa-v1'
    material_ids: list[str] = Field(default_factory=list, max_length=500)
    draft_id: str | None = None
    vision_service_id: str | None = None
    max_workers: int = Field(default=1, strict=True, ge=1, le=32)
    timeout: int = Field(default=1800, strict=True, ge=1, le=7200)
    steps: list[Step] = Field(min_length=4, max_length=4)
    output_contract: Literal['messages+media_bindings'] = 'messages+media_bindings'


def template():
    return {'name': '图片 VQA 配置', 'config': MMConfig(steps=[
        Step(id='question', kind='mm:PromptedVQAGenerator', inputs={'image': 'image'}, output='question', resource_ref='builtin:mm-question-v1', x=20, y=30),
        Step(id='answer', kind='mm:PromptedVQAGenerator', inputs={'image': 'image', 'question': 'question'}, output='answer', resource_ref='builtin:mm-answer-v1', bindings={'question': 'question'}, x=310, y=30),
        Step(id='validate', kind='platform:validate', inputs={'question': 'question', 'answer': 'answer'}, output='validated', resource_ref='builtin:mm-qa-schema-v1', x=600, y=30),
        Step(id='format', kind='platform:messages', inputs={'image': 'image', 'question': 'question', 'answer': 'answer'}, output='messages', resource_ref='builtin:mm-messages-v1', x=890, y=30),
    ]).model_dump(), 'builtin_resources': {'builtin:mm-question-v1': QUESTION, 'builtin:mm-answer-v1': ANSWER, 'builtin:mm-qa-schema-v1': SAMPLE_SCHEMA},
        'source': 'DataFlow-MM image_vqa.py / PromptedVQAGenerator', 'validation_status': '未配置视觉服务，未做真实运行验证'}


class MultimodalTemplates:
    def __init__(self, path=None):
        self.store = ResourceStore(path or container.data_library.root / 'multimodal_configs.json')

    def get(self, config_id):
        record = self.store.get(config_id)
        if not record:
            raise LibraryError('多模态配置不存在', 404)
        return record

    def validate(self, raw):
        try:
            config = MMConfig.model_validate(raw).model_dump()
        except ValidationError as exc:
            raise LibraryError(str(exc), 422) from exc
        steps = config['steps']
        expected = template()['config']['steps']
        if [s['id'] for s in steps] != [s['id'] for s in expected] or any(s['kind'] != e['kind'] for s, e in zip(steps, expected)):
            raise LibraryError('模板必须按问题、答案、结构检查、训练整理顺序保存')
        available = {'image'}
        semantic = {'image': 'image'}
        builtins = template()['builtin_resources']
        for step, default in zip(steps, expected):
            if set(step['inputs']) != set(default['inputs']) or not all(v in available for v in step['inputs'].values()):
                raise LibraryError(f"{step['id']}: 输入绑定缺失或引用了尚未生成的字段")
            if 'image' in step['inputs'] and step['inputs']['image'] != 'image':
                raise LibraryError('图片输入必须绑定材料 image 字段')
            if step['output'] in available:
                raise LibraryError('输出字段不能覆盖已有字段')
            if step['inputs'] != {k: semantic[k] for k in default['inputs']}:
                raise LibraryError(f"{step['id']}: 绑定必须保留图片、问题与答案的字段语义")
            if step['id'] in ('validate', 'format') and step['bindings']:
                raise LibraryError('结构检查和训练整理不接受提示词绑定')
            if step['id'] == 'format' and step['output'] != 'messages':
                raise LibraryError('训练整理输出必须为 messages')
            ref = step['resource_ref']
            if step['id'] in ('question', 'answer'):
                if ref.startswith('user_prompt:'):
                    resource = container.user_prompt_registry.get(ref.split(':', 1)[1])
                    if not resource:
                        raise LibraryError('Prompt 引用不存在')
                    allowed = resource.get('allowed_operators') or []
                    if allowed and 'PromptedVQAGenerator' not in allowed:
                        raise LibraryError('Prompt 未允许 PromptedVQAGenerator')
                    content = resource['template']
                elif ref == default['resource_ref']:
                    content = builtins[ref]
                else:
                    raise LibraryError('Prompt 引用无效')
                required = set(_extract_placeholders(content))
                if not content.strip() or set(step['bindings']) != required or not all(v in step['inputs'].values() for v in step['bindings'].values()):
                    raise LibraryError('Prompt 变量必须绑定到当前步骤输入字段')
                if step['id'] == 'answer' and step['bindings'].get('question') != step['inputs']['question']:
                    raise LibraryError('答案提示词必须通过 {question} 引用问题字段')
            elif step['id'] == 'validate':
                if ref.startswith('schema_ref:'):
                    resource = container.json_schema_manager.get(ref.split(':', 1)[1])
                    if not resource:
                        raise LibraryError('Schema 引用不存在')
                    try:
                        validate_schema(resource['schema'])
                    except ValueError as exc:
                        raise LibraryError(str(exc)) from exc
                elif ref != default['resource_ref']:
                    raise LibraryError('Schema 引用无效')
            elif ref != default['resource_ref']:
                raise LibraryError('训练整理使用固定消息与媒体契约')
            available.add(step['output'])
            semantic[step['id']] = step['output']
        if len(set(config['material_ids'])) != len(config['material_ids']):
            raise LibraryError('图片材料不能重复')
        for mid in config['material_ids']:
            material = container.data_library.get_material(mid)
            if material['kind'] != 'image':
                raise LibraryError('VQA 模板只接受图片材料')
        if config['draft_id']:
            draft = container.data_library.get_draft(config['draft_id'])
            if draft['modality'] != 'image_text' or draft['training_type'] != 'sft':
                raise LibraryError('输出目标必须是图文 SFT 草稿')
        return config

    def save(self, name, raw, config_id=None):
        if not name.strip() or len(name) > 240:
            raise LibraryError('请输入不超过 240 字的名称')
        config = self.validate(raw)
        with self.store.writing() as records:
            previous = records.get(config_id) if config_id else None
            if config_id and previous is None:
                raise LibraryError('多模态配置不存在', 404)
            key = config_id or 'mm_' + uuid.uuid4().hex
            record = {'id': key, 'name': name.strip(), 'config': config, 'created_at': previous['created_at'] if previous else _now(), 'updated_at': _now()}
            records[key] = record
        return copy.deepcopy(record)

    def check(self, raw):
        errors = []
        try:
            config = self.validate(raw)
        except LibraryError as exc:
            return {'structure_valid': False, 'ready': False, 'errors': [str(exc)], 'validation_status': '未做真实运行验证'}
        if not config['material_ids']:
            errors.append('请选择图片材料')
        for mid in config['material_ids']:
            try:
                container.data_library.material_file(mid)
            except LibraryError as exc:
                errors.append(str(exc))
        if not config['draft_id']:
            errors.append('请选择图文 SFT 输出草稿')
        if not config['vision_service_id']:
            errors.append('未配置视觉服务，未做真实运行验证')
        else:
            errors.append('视觉服务引用已保存，但尚未验证视觉能力；未做真实运行验证')
        errors.append('MM 独立进程执行桥接尚未启用，不能提交运行')
        return {'structure_valid': True, 'ready': False, 'errors': errors, 'validation_status': '未做真实运行验证'}

    def submit(self, config_id):
        result = self.check(self.get(config_id)['config'])
        raise LibraryError('；'.join(result['errors']), 409)
