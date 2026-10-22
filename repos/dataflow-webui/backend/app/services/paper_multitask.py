"""Portable paper SFT template, reusing the existing canvas and managed resources."""
import copy
import json
import os
from pathlib import Path
from app.core.config import settings
from app.services.data_library import _now

ASSETS = Path(__file__).resolve().parents[1]/'templates/paper_multitask'
ID = 'paper-multitask-low-cost-v1'


def definition():
    root = Path(settings.BASE_DIR)
    workspace = Path(__file__).resolve().parents[5]
    options = dict(parser=str(workspace/'scripts/mineru.sh'),
                   tokenizer=str(workspace/'models/tokenizers/Qwen2.5-7B-Instruct'),
                   context_tokens=3000, chunk_tokens=2800, max_samples=4, training_cutoff=6144)
    config_file = Path(os.environ.get('DATAFLOW_PAPER_CONFIG', '/work/paper-workflow.json'))
    if config_file.is_file():
        options.update(json.loads(config_file.read_text()))
    config = json.loads((ASSETS/'pipeline.json').read_text())
    config['file_path'] = ''
    config['input_dataset']['id'] = ''
    config['execution_options'].pop('simple_training', None)
    config['execution_options'].update(capture_responses=True, training_output=True, additional_retries=0,
        paper_multitask_low_cost=dict(version=1, max_samples=options['max_samples'], context_tokens=options['context_tokens']))
    for index, op in enumerate(config['operators']):
        for param in op['params']['init']:
            name = param['name']
            if name == 'mineru_script':param['value'] = options['parser']
            elif name == 'tokenizer_path':param['value'] = options['tokenizer']
            elif name == 'chunk_size':param['value'] = options['chunk_tokens']
            elif name == 'tier':param['value'] = 'advanced'
            elif name == 'timeout_seconds':param['value'] = 2700
            elif name == 'output_dir':param['value'] = str(root/'cache_local/paper-parsing')
            elif name == 'llm_serving':param['value'] = None
            elif name == 'prompt_template':param['value'] = 'user_prompt:paper-multitask-'+('generate' if index == 6 else 'review')+'-v1'
            elif name == 'json_schema':param['value'] = 'schema_ref:paper-multitask-'+('generate' if index == 6 else 'review')+'-v1'
            elif name == 'process_fn' and index == 4:
                param['value'] = ["lambda df: __import__('paper_dataflow.low_cost_sft', fromlist=['build_contexts']).build_contexts(df, tokenizer_path="+repr(options['tokenizer'])+", context_tokens="+str(options['context_tokens'])+", max_samples="+str(options['max_samples'])+")"]
            elif name == 'process_fn' and index == 7:
                param['value'] = ["lambda df: __import__('paper_dataflow.low_cost_sft', fromlist=['parse_candidates']).parse_candidates(df, max_samples="+str(options['max_samples'])+")"]
            elif name == 'process_fn' and index == 11:
                param['value'] = ["lambda df: __import__('paper_dataflow.low_cost_sft', fromlist=['export_results']).export_results(df, output_dir="+repr(str(root/'data/paper-exports'))+", tokenizer_path="+repr(options['tokenizer'])+", max_tokens="+str(options['training_cutoff'])+")"]
    return dict(id=ID, name='论文 PDF → 科研多任务 SFT · 个人 API', tags=['template','paper','sft'],
                config=config, created_at=_now(), updated_at=_now(), status='queued')


def install(c):
    data = c.pipeline_registry._read()
    if ID in data.get('pipelines', {}):
        return
    now = _now()
    for stage in ('generate', 'review'):
        rid = 'paper-multitask-'+stage+'-v1'
        with c.user_prompt_registry.store.writing() as records:
            records.setdefault(rid, dict(id=rid, name='论文多任务 · '+stage, description='论文原文驱动，不凑数。',
                template=(ASSETS/(stage+'.txt')).read_text(), allowed_operators=['FormatStrPromptedGenerator'],
                example_variables={}, usage='文本 SFT', purpose='生成' if stage == 'generate' else '评分',
                created_at=now, updated_at=now))
        with c.json_schema_manager.store.writing() as records:
            records.setdefault(rid, dict(id=rid, name='论文多任务协议 · '+stage, description='',
                schema=(ASSETS/(stage+'.schema.json')).read_text(), example='', usage='文本 SFT',
                purpose='模型输出', created_at=now, updated_at=now))
    data.setdefault('pipelines', {})[ID] = definition()
    c.pipeline_registry._write(data)
