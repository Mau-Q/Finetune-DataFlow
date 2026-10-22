"""Standard profile extends the existing portable paper pipeline and resources."""
import copy
import json
from pathlib import Path
from app.services.data_library import _now
from app.core.config import settings

ASSETS = Path(__file__).resolve().parents[1]/'templates/paper_multitask'
ID = 'paper-standard-sft-v1'


def definition(reuse=False):
    from app.services.paper_multitask import definition as base
    rec = base()
    rec.update(id=ID+('-reuse' if reuse else ''), name='论文科研 SFT · 标准低成本'+(' · 复用候选' if reuse else ''))
    config = rec['config'];ops = config['operators']
    config['execution_options']['paper_multitask_low_cost'].update(profile='standard-reuse' if reuse else 'standard',
        max_candidates_per_paper=8, fixed_context_count=None, fixed_samples_per_context=None)
    def transform(op, expression, columns):
        for param in op['params']['init']:
            if param['name'] == 'process_fn':param['value'] = [expression]
        op['params']['run'] = [dict(name='output_key', value=columns)]
    tokenizer = next(p['value'] for p in ops[3]['params']['init'] if p['name']=='tokenizer_path')
    tokens = config['execution_options']['paper_multitask_low_cost']['context_tokens']
    for op, stage in [(ops[6], 'generate'), (ops[9], 'review')]:
        for param in op['params']['init']:
            if param['name'] == 'prompt_template':param['value'] = 'user_prompt:paper-standard-'+stage+'-v1'
            elif param['name'] == 'json_schema' and stage == 'generate':param['value'] = 'schema_ref:paper-standard-generate-v1'
    if reuse:
        # Input already contains selected, source-bound candidates; never rerun generation.
        config['operators'] = [copy.deepcopy(ops[i]) for i in (9, 10, 11)]
        return rec
    transform(ops[4], "lambda df: __import__('paper_dataflow.standard_sft', fromlist=['planning_rows']).planning_rows(df, tokenizer_path="+
              repr(tokenizer)+", context_tokens="+str(tokens)+")", ['planning_input','all_contexts'])
    planner = copy.deepcopy(ops[6])
    planner['pipeline_role'] = '论文级核心目标与带证据任务规格规划，不生成答案。'
    for param in planner['params']['init']:
        if param['name'] == 'prompt_template':param['value'] = 'user_prompt:paper-standard-plan-v1'
        elif param['name'] == 'json_schema':param['value'] = 'schema_ref:paper-standard-plan-v1'
    planner['params']['run'] = [dict(name='output_key', value='planning_raw'), dict(name='index', value='planning_input')]
    apply = copy.deepcopy(ops[4])
    apply['pipeline_role'] = '按核心目标覆盖贪心选择与删冗余，按 token 组卷，每篇至多 8 条候选。'
    transform(apply, "lambda df: __import__('paper_dataflow.standard_sft', fromlist=['apply_plans']).apply_plans(df, tokenizer_path="+
              repr(tokenizer)+", context_tokens="+str(tokens)+")", ['context_valid','generation_input','context','source_map',
              'generation_sample_budget','planned_instructions','paper_plan_audit'])
    transform(ops[7], "lambda df: __import__('paper_dataflow.standard_sft', fromlist=['parse_planned_candidates']).parse_planned_candidates(df)",
              ['keywords','candidates','invalid_candidates','candidate_count','review_input'])
    config['operators'] = ops[:5]+[planner, apply]+ops[5:]
    for index, op in enumerate(config['operators']):
        op['location'] = [40+(index%4)*330, 80+(index//4)*260]
    return rec


def install(c):
    now = _now()
    for stage in ('plan','generate','review'):
        rid = 'paper-standard-'+stage+'-v1'
        with c.user_prompt_registry.store.writing() as records:
            records.setdefault(rid, dict(id=rid, name='论文标准 · '+stage, description='论文级规划和来源约束审核。',
                template=(ASSETS/('standard-'+stage+'.txt')).read_text(), allowed_operators=['FormatStrPromptedGenerator'],
                example_variables={}, usage='文本 SFT', purpose='评分' if stage=='review' else '生成', created_at=now, updated_at=now))
    for stage in ('plan', 'generate'):
        rid='paper-standard-'+stage+'-v1'
        with c.json_schema_manager.store.writing() as records:
            records.setdefault(rid, dict(id=rid, name='论文标准协议 · '+stage, description='',
                schema=(ASSETS/('standard-'+stage+'.schema.json')).read_text(), example='', usage='文本 SFT',
                purpose='模型输出', created_at=now, updated_at=now))
    data = c.pipeline_registry._read()
    for reuse in (False, True):
        rec=definition(reuse)
        data.setdefault('pipelines', {}).setdefault(rec['id'], rec)
    c.pipeline_registry._write(data)
