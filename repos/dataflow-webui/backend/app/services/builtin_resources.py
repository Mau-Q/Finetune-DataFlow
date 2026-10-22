"""Versioned, read-only resources. These describe structure, not answer quality."""
import copy
import json

TEXT = {'type': 'string', 'minLength': 1, 'pattern': r'\S'}


def builtin_schemas():
    from app.services.multimodal_templates import SAMPLE_SCHEMA
    image_url = {'oneOf': [TEXT, {'type': 'object', 'required': ['url'], 'properties': {'url': TEXT}}]}
    blocks = {'type': 'array', 'minItems': 1, 'items': {'oneOf': [
        {'type': 'object', 'required': ['type', 'text'], 'properties': {'type': {'const': 'text'}, 'text': TEXT}},
        {'type': 'object', 'required': ['type', 'image_url'], 'properties': {'type': {'const': 'image_url'}, 'image_url': image_url}},
    ]}}
    message = {'type': 'object', 'required': ['role', 'content'], 'properties': {
        'role': {'enum': ['system', 'user', 'assistant', 'tool']}, 'content': {'oneOf': [TEXT, blocks]}}}
    messages = {'type': 'array', 'minItems': 2, 'items': message, 'allOf': [
        {'contains': {'properties': {'role': {'const': role}}, 'required': ['role']}} for role in ('user', 'assistant')]}
    flat = {'type': 'object', 'required': ['instruction', 'output'], 'properties': {'instruction': TEXT, 'input': {'type': 'string'}, 'output': TEXT}, 'not': {'required': ['messages']}}
    chat = {'type': 'object', 'required': ['messages'], 'properties': {'messages': messages}}
    media_props = {'image': TEXT, 'images': {'type': 'array', 'items': TEXT}}
    has_image = {'anyOf': [
        {'required': ['image']}, {'required': ['images'], 'properties': {'images': {'minItems': 1}}},
        {'required': ['messages'], 'properties': {'messages': {'contains': {'required': ['content'], 'properties': {'content': {'type': 'array', 'contains': {'required': ['type', 'image_url'], 'properties': {'type': {'const': 'image_url'}}}}}}}}},
    ]}
    no_image = {'not': has_image}
    sft = {'type': 'object', 'anyOf': [flat, chat], 'properties': media_props}
    dpo = {'type': 'object', 'required': ['prompt', 'chosen', 'rejected'], 'properties': {'prompt': TEXT, 'chosen': TEXT, 'rejected': TEXT, **media_props}}
    records = [
        ('text-sft-v1', '文本 SFT', '文本 SFT', {'allOf': [sft, no_image]}, {'instruction': '什么是正方形？', 'input': '', 'output': '四条边相等且四个角为直角的四边形。'}),
        ('text-dialogue-sft-v1', '文本多轮 SFT', '文本 SFT', {'allOf': [chat, {'properties': media_props}, no_image]}, {'messages': [{'role': 'user', 'content': '你好'}, {'role': 'assistant', 'content': '你好！'}]}),
        ('image-sft-v1', '图文 SFT', '图文 SFT', {'allOf': [sft, has_image]}, {'instruction': '图中是什么？', 'output': '红色正方形。', 'images': ['images/example.png']}),
        ('text-dpo-v1', '文本 DPO', '文本 DPO', {'allOf': [dpo, no_image]}, {'prompt': '什么是正方形？', 'chosen': '四条边相等且四个角为直角的四边形。', 'rejected': '三条边的图形。'}),
        ('image-dpo-v1', '图文 DPO', '图文 DPO', {'allOf': [dpo, has_image]}, {'prompt': '图形是什么颜色？', 'chosen': '红色。', 'rejected': '蓝色。', 'images': ['images/example.png']}),
    ]
    result = []
    for key, name, usage, schema, example in records:
        schema = {'$schema': 'https://json-schema.org/draft/2020-12/schema', **schema}
        fields = ['messages'] if key == 'text-dialogue-sft-v1' else ['prompt', 'chosen', 'rejected'] if 'dpo' in key else ['instruction', 'input', 'output', 'messages']
        if key.startswith('image-'):
            fields += ['image', 'images']
        result.append({'fields': fields, 'id': 'builtin-' + key, 'name': name, 'usage': usage, 'purpose': '训练样本校验',
                       'description': '结构校验参考；图片存在性、媒体绑定及 DPO 两个回答是否相同仍由导入流程检查。',
                       'schema': json.dumps(schema, ensure_ascii=False, indent=2), 'example': json.dumps(example, ensure_ascii=False, indent=2)})
    result.append({'fields': ['question', 'answer'], 'id': 'builtin-mm-qa-v1', 'name': '图片 VQA 问答输出', 'usage': '图文 SFT', 'purpose': '模型输出',
                   'description': '图片 VQA「结构检查」步骤使用的 question / answer 规则。',
                   'schema': json.dumps(SAMPLE_SCHEMA, ensure_ascii=False, indent=2),
                   'example': json.dumps({'question': '图中是什么？', 'answer': '红色正方形。'}, ensure_ascii=False, indent=2)})
    return [dict(r, created_at='', updated_at='', source='builtin', readonly=True, version='v1') for r in result]


def get_builtin_schema(key):
    return next((copy.deepcopy(r) for r in builtin_schemas() if r['id'] == key), None)
