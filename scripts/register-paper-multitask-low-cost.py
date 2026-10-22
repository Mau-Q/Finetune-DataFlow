"""Create an independent PDF multitask pipeline and managed prompts; never run it.

Uses the authenticated local-development gateway, never the private worker port.
Only service IDs are copied into the portable configuration; no credentials.
"""
import argparse
import hashlib
import http.cookiejar
import json
from pathlib import Path
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
RESOURCES = ROOT / 'pipelines/paper-multitask-low-cost'
STATE = RESOURCES / 'registration.json'
NAME = '论文 PDF → 科研多任务 SFT · 低成本生成与批量审核 v1'


class API:
    def __init__(self, base):
        self.base = base.rstrip('/')
        self.client = urllib.request.build_opener(urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.csrf = ''
        self.version = None
        self.csrf = self.call('/team/dev-login', {})['csrf']

    def call(self, path, body=None, method=None):
        headers = {'Origin': self.base, 'Content-Type': 'application/json', 'X-CSRF-Token': self.csrf}
        if self.version is not None:
            headers['If-Match'] = self.version
        req = urllib.request.Request(self.base + path,
            data=None if body is None else json.dumps(body, ensure_ascii=False).encode(),
            method=method, headers=headers)
        try:
            with self.client.open(req, timeout=210) as response:
                result = json.load(response)
                self.version = response.headers.get('X-Resource-Version', self.version)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f'{path}: HTTP {exc.code}: {exc.read().decode()}') from exc
        if result.get('success') is False:
            raise RuntimeError(result.get('message'))
        return result.get('data', result)


def schemas():
    def obj(properties):
        return dict(type='object', additionalProperties=False,
                    properties=properties, required=list(properties))
    string = {'type': 'string'}
    sample = obj({k: string for k in ('reader_level', 'user_goal', 'task_type', 'instruction', 'answer_format', 'answer')})
    sample['properties']['answer_format'] = dict(type='string', enum=['text', 'json'])
    generation = obj(dict(keywords=dict(type='array', maxItems=8, items=string),
                          samples=dict(type='array', maxItems=4, items=sample)))
    status = dict(type='string', enum=['PASS', 'FAIL', 'UNCERTAIN'])
    review = obj(dict(reviews=dict(type='array', maxItems=4, items=obj(dict(
        sample_id=string, grounded=status, task_fit=status, usefulness=status, reason=string)))))
    return generation, review


def op(name, role, init=None, run=None):
    return dict(name=name, pipeline_role=role, location=[0, 0], params={
        part: [dict(name=k, value=v) for k, v in values.items()]
        for part, values in [('init', init or {}), ('run', run or {})]})


def transform(function, outputs, args=''):
    expression = f"lambda df: __import__('paper_dataflow.low_cost_sft', fromlist=['{function}']).{function}(df{args})"
    return op('PandasOperator', '', {'process_fn': [expression]}, {'output_key': outputs})


def config(dataset, generator, reviewer, prompts, schema_ids):
    tokenizer = str(ROOT / 'models/tokenizers/Qwen2.5-7B-Instruct')
    nodes = [
        transform('prepare_sources', ['source_path', 'document_id', 'split', 'source_aliases']),
        op('MinerU4PDFParser', '保留 PDF 快照与结构化解析产物，不调用生成/审核模型。',
           dict(mineru_script=str(ROOT / 'scripts/mineru.sh'), output_dir=str(ROOT / 'outputs/paper-multitask-low-cost/parsing'),
                tier='standard', timeout_seconds=900), dict(input_key='source_path', output_key='parsed_document')),
        op('MinerU4PageExtractor', '逐页提取正文、表格、公式和可追溯块位置。',
           run=dict(input_key='parsed_document', output_key='source_page')),
        op('PaperStructuredChunker', '章节优先、完整结构块切分；正文不经过模型改写。',
           dict(tokenizer_path=tokenizer, chunk_size=5800),
           dict(input_key='source_page', output_key='raw_chunk', output_meta_key='chunk_metadata')),
        transform('build_contexts', ['unit_id', 'context', 'context_scope', 'context_valid', 'source_map', 'generation_input'],
                  f', tokenizer_path={tokenizer!r}, context_tokens=6000, max_samples=4'),
        op('GeneralFilter', '暂缓超预算或已标记缺损的上下文；原记录仍在上一步产物。',
           dict(filter_rules=["lambda df: df['context_valid'].fillna(False).astype(bool)"])),
        op('FormatStrPromptedGenerator', '结合重要内容、读者背景与阅读目的生成最多四条不同科研任务。',
           dict(llm_serving=generator, system_prompt='你负责依据所给论文材料生成准确、清楚的中文科研任务训练样本。',
                prompt_template='user_prompt:' + prompts[0], json_schema='schema_ref:' + schema_ids[0]),
           dict(output_key='generation_raw', material='generation_input')),
        transform('parse_candidates', ['keywords', 'candidates', 'invalid_candidates', 'candidate_count', 'review_input']),
        op('GeneralFilter', '只有结构合格的候选进入审核；无效响应保留在上一步产物。',
           dict(filter_rules=["lambda df: df['candidate_count'].fillna(0).gt(0)"])),
        op('FormatStrPromptedGenerator', '同一上下文批量逐条审核，检查事实依据、任务完成与学习价值。',
           dict(llm_serving=reviewer, system_prompt='你是独立科研数据审核者，依据材料逐条核对，不改写答案。',
                prompt_template='user_prompt:' + prompts[1], json_schema='schema_ref:' + schema_ids[1]),
           dict(output_key='review_raw', batch='review_input')),
        transform('parse_reviews', ['sample_id', 'task_type', 'instruction', 'input', 'output', 'review_status', 'review_reason', 'dedup_text']),
        transform('export_results', ['export_status', 'sft_row', 'export_dir'],
                  f', output_dir={str(ROOT / "outputs/paper-multitask-low-cost/exports")!r}'),
    ]
    roles = {0: '检查 PDF 文件并按内容哈希去重，保留重复来源映射；不修改原材料。',
             4: '整篇解析文字可放入预算时合并；否则保留章节/结构块上下文，超长不截断。',
             7: '严格解析生成 JSON、逐候选检查、分配稳定 ID，并复用上下文准备审核批次。',
             10: '按样本 ID 匹配审核，未知或重复 ID 拒绝自动准入；展开为独立样本。',
             11: '先保留全部审核审计，再筛选 PASS、精确去重，导出 SFT、映射与汇总。'}
    for index, node in enumerate(nodes):
        if index in roles: node['pipeline_role'] = roles[index]
        row, column = divmod(index + 1, 4)
        node['location'] = [40 + (column if row % 2 == 0 else 3 - column) * 330, 80 + row * 260]
    return dict(file_path=str(RESOURCES / 'pipeline.webui.json'),
        input_dataset=dict(id=dataset, location=[40, 80], pipeline_role='现有受管 PDF 论文来源，未复制或修改原文。'),
        operators=nodes, execution_options=dict(simple_training=dict(modality='text', training_type='sft'),
            paper_multitask_low_cost=dict(version=1, max_samples=4, context_tokens=6000,
                                         automatic_semantic_retry=False)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='http://127.0.0.1:8001')
    parser.add_argument('--dataset-id', default='a5f3dd5c5d')
    parser.add_argument('--generator-id', default='586e578e9e102ac5')
    parser.add_argument('--reviewer-id', default='9fb9ebf1ed9ee33e')
    args = parser.parse_args()
    if args.base not in ('http://127.0.0.1:8001', 'http://localhost:8001'):
        raise ValueError('This registration helper only supports the local development gateway')
    api = API(args.base)
    datasets = {d['id']: d for d in api.call('/api/v1/datasets/')}
    columns = api.call('/api/v1/datasets/columns/' + args.dataset_id)
    if args.dataset_id not in datasets or not ({'source', 'source_path', 'path'} & set(columns)):
        raise ValueError('Select a PDF source dataset with a file path column')
    services = {s['id']: s for s in api.call('/api/v1/serving/')}
    if not {args.generator_id, args.reviewer_id}.issubset(services):
        raise ValueError('Configured model services are missing; no model will be called')
    prior = json.loads(STATE.read_text()) if STATE.exists() else {}
    prompt_ids, schema_ids = [], []
    specs = schemas()
    for index, stage in enumerate(('generate', 'review')):
        text = (RESOURCES / (stage + '.txt')).read_text()
        prompt_body = dict(name='论文多任务低成本 v1 · ' + ('生成' if index == 0 else '批量审核'),
            description='PDF 原文驱动；仅保存资源不调用模型。', template=text,
            allowed_operators=['FormatStrPromptedGenerator'], usage='文本 SFT',
            purpose='生成' if index == 0 else '评分')
        if prior:
            p = api.call('/api/v1/prompts/user/' + prior['prompt_ids'][index])
            if p['template'] != text:
                raise ValueError('Existing prompt differs; review it before creating a new version')
        else: p = api.call('/api/v1/prompts/user', prompt_body)
        prompt_ids.append(p['id'])
        if prior: s = api.call('/api/v1/json_schemas/' + prior['schema_ids'][index])
        else: s = api.call('/api/v1/json_schemas', dict(name=prompt_body['name'] + ' · 输出协议',
            schema=json.dumps(specs[index], ensure_ascii=False), usage='文本 SFT', purpose='模型输出'))
        schema_ids.append(s['id'])
        (RESOURCES / (stage + '.schema.json')).write_text(json.dumps(specs[index], ensure_ascii=False, indent=2) + '\n')
    conf = config(args.dataset_id, args.generator_id, args.reviewer_id, prompt_ids, schema_ids)
    validation = api.call('/api/v1/pipelines/validate', conf)
    (RESOURCES / 'validation.json').write_text(json.dumps(validation, ensure_ascii=False, indent=2) + '\n')
    if not validation.get('valid'):
        raise RuntimeError(json.dumps(validation, ensure_ascii=False))
    payload = dict(name=NAME, config=conf, tags=['paper', 'sft', 'multitask', 'low-cost', 'not-run'])
    if prior:
        saved = api.call('/api/v1/pipelines/' + prior['pipeline_id'])
        if saved['name'] != NAME:
            raise ValueError('Pipeline identity changed; refusing overwrite')
        # Never overwrite a later edit just because this helper was run again.
        if saved['config'] != conf:
            raise ValueError('Existing Pipeline differs; preserve it and review before updating')
    else: saved = api.call('/api/v1/pipelines/', payload)
    readback = api.call('/api/v1/pipelines/' + saved['id'])
    result = dict(pipeline_id=saved['id'], name=NAME, dataset_id=args.dataset_id,
        generator_id=args.generator_id, reviewer_id=args.reviewer_id,
        prompt_ids=prompt_ids, schema_ids=schema_ids, validation=validation,
        readback_operator_count=len(readback['config']['operators']), model_calls=0,
        execution_submitted=False,
        prompt_sha256=[hashlib.sha256((RESOURCES / (s + '.txt')).read_bytes()).hexdigest() for s in ('generate', 'review')])
    STATE.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    (RESOURCES / 'pipeline.webui.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
