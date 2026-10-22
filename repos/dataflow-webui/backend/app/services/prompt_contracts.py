"""Explicit managed-Prompt slots; protocol ownership stays with each operator."""
from app.services.user_prompt_registry import _extract_placeholders

RUBRICS = {
    'question_quality_prompt_template': ('问题质量评分', 'Text2QAQuestionQualityPrompt'),
    'answer_alignment_prompt_template': ('答案对齐评分', 'Text2QAAnswerAlignmentPrompt'),
    'answer_verifiability_prompt_template': ('答案可验证性评分', 'Text2QAAnswerVerifiabilityPrompt'),
    'downstream_value_prompt_template': ('下游价值评分', 'Text2QADownstreamValuePrompt'),
}
CONTRACTS = {
    'APIImagePairGenerator': {'prompt_template': dict(label='图片训练样例提示词', required=[], variables=[], protocol='图片由程序附加。只编辑生成要求；输出 JSON 由下一步 Schema 和训练契约校验。', builtin='')},
    'FormatStrPromptedGenerator': {'prompt_template': dict(label='通用生成模板', required=[], variables=None, protocol='由字段绑定填充模板；保留输出列。', builtin='FormatStrPrompt')},
    'KBCTextCleaner': {'prompt_template': dict(label='文本清洗模板', required=['text'], variables=['text'], protocol='必须保留 {text}；程序追加 cleaned_start / cleaned_end 输出标记要求。', builtin='KnowledgeCleanerPrompt')},
    'Text2MultiHopQAGenerator': {'prompt_template': dict(label='多跳 QA 模板', required=['text'], variables=['text'], protocol='必须保留 {text}；固定系统提示和 JSON 问答结构，保留 question、answer、reasoning_steps、supporting_facts。', builtin='Text2MultiHopQAGeneratorPrompt')},
    'Text2QASampleEvaluator': {key:dict(label=label, required=[], variables=[], protocol='只编辑评分标准；问题、答案和来源上下文由算子追加。固定 1–5 整数及 Grading / Feedback 字段。', builtin=builtin) for key,(label,builtin) in RUBRICS.items()},
    'AlpagasusSampleEvaluator': {'prompt_template': dict(label='Alpagasus 评分标准', required=[], variables=[], protocol='只编辑评分标准；指令、输入、回答由算子追加。固定首行 0–5 分，次行说明。', builtin='AlpagasusPrompt')},
}


def validate_managed_template(operator, param, template, bindings=None):
    contract = CONTRACTS.get(operator, {}).get(param)
    if contract is None:
        raise ValueError(f'{operator}.{param}: 不支持自定义 Prompt；尚未接入已验证契约')
    if not isinstance(template, str) or not template.strip():
        raise ValueError('模板内容不能为空')
    fields = set(_extract_placeholders(template))
    missing = set(contract['required']) - fields
    if missing:
        raise ValueError('模板必须包含变量: ' + ', '.join(sorted(missing)))
    if contract['variables'] is not None and fields - set(contract['variables']):
        raise ValueError('此位置只允许变量: ' + (', '.join(contract['variables']) or '无变量；数据由算子追加'))
    if operator != 'FormatStrPromptedGenerator' and bindings:
        raise ValueError('此位置使用固定输入语义，不接受自定义数据列绑定')
    return contract
