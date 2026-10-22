"""Representative generation workflows without model scoring."""
import copy
import json
from pathlib import Path
from app.services.data_library import _now, _json_bytes, _hash
from app.services.dataset_persistence import atomic_write

LEGACY_IDS = {f'simple-{mode}-{kind}-v1' for mode in ('text', 'image_text') for kind in ('sft', 'dpo')}


def resources():
    text = {'type': 'string', 'minLength': 1, 'pattern': r'\S'}
    score = {'type': 'integer', 'minimum': 1, 'maximum': 5}
    def schema(key, name, properties):
        return dict(id=key, name=name, schema={'type': 'object', 'properties': properties,
                    'required': list(properties), 'additionalProperties': False})
    schemas = [
        schema('representative-sft-sample-v1', '代表性 SFT · 候选结构', {'question':text, 'answer':text}),
        schema('representative-dpo-sample-v1', '代表性 DPO · 偏好结构', {'question':text, 'chosen':text, 'rejected':text}),
        schema('representative-sft-review-v1', '代表性 SFT · 评价结构', {'score':score, 'grounded':{'type':'boolean'}, 'reason':text}),
        schema('representative-dpo-review-v1', '代表性 DPO · 评价结构', {'score_a':score, 'score_b':score,
            'grounded_a':{'type':'boolean'}, 'grounded_b':{'type':'boolean'}, 'reason':text}),
    ]
    prompts = []
    def prompt(key, name, operator, content, purpose='生成', usage='通用'):
        prompts.append(dict(id=key, name=name, allowed_operators=[operator], template=content, purpose=purpose, usage=usage))
    prompt('representative-qa-v1', '代表性文本 · 多跳问答', 'Text2MultiHopQAGenerator',
           '依据下面的相邻事实生成一个需要关联至少两条事实的问题和完整答案。必须可由材料回答。'
           'supporting_facts 必须逐字引用材料；不要自造前提。材料：\n{text}')
    rubrics = {
        'question_quality': '评价问题是否清晰、自包含，条件是否明确，是否关联了材料中的事实。',
        'answer_alignment': '评价回答是否直接回答问题、覆盖必要条件，避免遗漏和无关扩展。',
        'answer_verifiability': '只依据后附原始来源核对回答中的事实、数字、单位和推理。候选 supporting_facts 不是可信来源。超出来源或存在矛盾时最高 2 分。',
        'downstream_value': '评价此问答是否有明确学习价值，避免模糊问题、重复复述和无意义回答。',
    }
    for key, rubric in rubrics.items():
        prompt('representative-'+key+'-v1', '代表性文本 SFT · '+key, 'Text2QASampleEvaluator',
               rubric + '按 1–5 整数评分，5 最好。', '评分', '文本 SFT')
    prompt('representative-text-alternative-v1', '代表性文本 DPO · 独立回答 B', 'FormatStrPromptedGenerator',
           '根据原始材料独立回答所给问题。尽量简洁，必须保留关键条件；不参考其他候选，不故意编造错误。'
           '仅输出 JSON：question 为原问题原文，answer 为你的回答。\n材料：{text}\n问题：{question}', usage='文本 DPO')
    preference = ('独立评价两个未排序候选。只依据来源，逐一核对事实、完整性、条件和问题相关性；'
                  '不得因候选位置或长度直接判优。分别给 1–5 整数分，grounded 表示该回答的事实是否均有来源支持。'
                  '同等质量应同分；不能为了生成 DPO 强行拉开分数。仅返回 JSON：'
                  'score_a、score_b、grounded_a、grounded_b、reason。')
    prompt('representative-text-preference-v1', '代表性文本 DPO · 来源评价与排序', 'FormatStrPromptedGenerator',
           preference + '\n原始材料：{text}\n同题候选：{alternatives}', '评分', '文本 DPO')
    prompt('representative-image-question-v1', '代表性图片 · 问题生成', 'APIImagePairGenerator',
           '仔细看图，生成一个需要读取表格、比较数值或理解图示关系的问题。只问图片能确定的内容，'
           '不用外部知识，不生成答案。仅返回 JSON 对象，字段 question。')
    for variant, style in [('a', '完整解释必要依据和条件'), ('b', '简洁直接，但不省略问题所需的关键条件')]:
        prompt('representative-image-answer-'+variant+'-v1', '代表性图片 · 独立回答 '+variant.upper(), 'APIImagePairGenerator',
               '依据图片独立回答后附问题，'+style+'。不参考其他候选，不故意编造错误。'
               '仅返回 JSON 对象，question 必须逐字保留后附问题，answer 为回答。')
    prompt('representative-image-review-v1', '代表性图片 SFT · 看图核验', 'APIImagePairGenerator',
           '结合图片独立核对后附问答。检查问题是否可由图片回答，以及答案的事实、数字、单位、条件是否正确完整。'
           '按 1–5 整数评分；grounded 仅当答案事实均有图片依据时为 true。无法辨认时给低分，不能猜测。'
           '仅返回 JSON 对象，字段 score、grounded、reason。', '评分', '图文 SFT')
    prompt('representative-image-preference-v1', '代表性图片 DPO · 看图评价与排序', 'APIImagePairGenerator',
           preference + '来源为所附图片，无法辨认时不要假设事实。', '评分', '图文 DPO')
    prompt('representative-text-negative-v1', '文本 DPO · 合成负例', 'FormatStrPromptedGenerator',
           '为后附问题生成一个用于偏好训练的合成负例。回答应有一个明确的事实、计算或关键条件错误；'
           '不要在回答中声明自己是负例。仅输出 JSON：question 为原问题原文，answer 为负例回答。'
           '不评分、不比较候选。材料：{text}\n问题：{question}', usage='文本 DPO')
    prompt('representative-image-negative-v1', '图片 DPO · 合成负例', 'APIImagePairGenerator',
           '根据图片和后附问题生成一个用于偏好训练的合成负例。回答应有一个明确的读图、计算或关键条件错误；'
           '不要在回答中声明自己是负例。不评分、不比较候选。仅输出 JSON：question 必须逐字保留后附问题，answer 为负例回答。', usage='图文 DPO')
    return prompts, schemas


def synthetic_pair_operator():
    return dict(name='PandasOperator', pipeline_role='正例写入 chosen、合成负例写入 rejected；标签未经独立评价',
                params={'init':[{'name':'process_fn','value':[
                    "lambda df: df.assign(preference_candidate=df['alternatives'].map(lambda pair: {'question': pair['question'], 'chosen': pair['answer_a'], 'rejected': pair['answer_b']}), preference_basis='synthetic_positive_negative')"]}],
                        'run':[{'name':'output_key','value':'preference_candidate'}]},location=[0,0])


def remove_scoring(config):
    """Migrate representative configs only; retain input, serving and user names."""
    config = copy.deepcopy(config)
    options = config['execution_options']
    if options.get('scoring_policy') == 'none':
        return config
    mode = options['simple_training']
    dpo = mode['training_type'] == 'dpo'
    target = 'preference_candidate' if dpo else 'candidate_a'
    operators = []
    for operator in config['operators']:
        op = copy.deepcopy(operator)
        sections = op.get('params', {})
        def values(part):
            data = sections.get(part, [])
            return [{'name':k,'value':v} for k,v in data.items()] if isinstance(data,dict) else data
        init, run = values('init'), values('run')
        run_values = {p['name']:p.get('value') for p in run}
        rules = str(next((p.get('value') for p in init if p['name']=='filter_rules'), ''))
        if op['name'] in {'Text2QASampleEvaluator','TrainingReviewParser'} or run_values.get('output_key') == 'review':
            continue
        if op['name']=='GeneralFilter' and any(key in rules for key in ('question_score','alignment_score','grounding_score','value_score',"['accepted']")):
            continue
        if dpo and run_values.get('output_key') == 'candidate_b':
            for param in init:
                if param['name']=='prompt_template':
                    param['value']='user_prompt:representative-'+('text' if mode['modality']=='text' else 'image')+'-negative-v1'
            op['pipeline_role']='生成同题合成负例；不评分'
        if op['name']=='TrainingPreferenceBuilder':
            op['pipeline_role']='组合同题正例与合成负例；检查问题一致性，不评分'
        for param in run:
            value = param.get('value')
            if op['name']=='TrainingPairFormatter' and param['name']=='input_key':param['value']=target
            elif op['name']=='HashDeduplicateFilter':
                if value == 'admitted_candidate':param['value']=target
                elif isinstance(value,list):param['value']=[target if v=='admitted_candidate' else v for v in value]
        op['params']={'init':init,'run':run}
        operators.append(op)
        if op['name']=='TrainingPreferenceBuilder':operators.append(synthetic_pair_operator())
    # Preserve existing canvas positions; place only the added formatter between its neighbours.
    for i,op in enumerate(operators):
        if op['name']=='PandasOperator' and any(p.get('value')=='preference_candidate' for p in op['params']['run']):
            x,y=operators[i-1].get('location',[320*i,150]);op['location']=[x+160,y+180]
    config['operators']=operators
    options.update(scoring_policy='none',preference_policy='synthetic_positive_negative' if dpo else None)
    return config


def definitions():
    result = []
    def op(name, role, init=None, run=None):
        return dict(name=name, pipeline_role=role, params={part:[{'name':k,'value':v} for k,v in values.items()]
                    for part,values in [('init',init or {}), ('run',run or {})]})
    def gen(ref, output, bindings):
        role = '依据原文生成同题合成负例；不评分'
        return op('FormatStrPromptedGenerator', role,
                  {'llm_serving':None, 'prompt_template':'user_prompt:'+ref},
                  {'output_key':output, 'input_keys':[{'name':k,'value':v} for k,v in bindings.items()]})
    def image(ref, output, context=None):
        role = {'image_question':'看图生成问题，不生成答案', 'candidate_a':'看图生成完整回答 A，保留原问题',
                'candidate_b':'根据图片生成同题合成负例；不评分'}[output]
        return op('APIImagePairGenerator', role,
                  {'llm_serving':None, 'prompt_template':'user_prompt:'+ref},
                  {'input_image_key':'source', 'input_context_key':context, 'output_key':output})
    def dedup(keys, label):
        return op('HashDeduplicateFilter', '按来源与候选精确去重，保留首次出现', {'hash_func':'sha256'},
                  {'input_key':keys[0], 'output_key':label} if len(keys)==1 else {'input_keys':keys,'output_key':label})
    for modality, label in [('text','文本'), ('image_text','图片')]:
        for kind in ('sft','dpo'):
            ops = []
            if modality == 'text':
                ops += [op('GeneralFilter', '按结构过滤：剔除不足 100 字或不足 3 句的输入',
                           {'filter_rules':["lambda df: df['text'].fillna('').str.len().ge(100) & df['text'].fillna('').str.count('。').ge(3)"]}),
                        dedup(['text'], 'source_unique'),
                        op('PandasOperator', '复制原文到清洗列，原文单独保留供核验',
                           {'process_fn':["lambda df: df.assign(cleaned_text=df['text'])"]}, {'output_key':'cleaned_text'}),
                        op('RemoveExtraSpacesRefiner', '本地规范多余空白，不改写事实、数字和条件', run={'input_key':'cleaned_text'}),
                        op('Text2MultiHopQAGenerator', '从清洗材料关联事实，最多生成一条问答',
                           {'llm_serving':None, 'lang':'zh','num_q':1,'prompt_template':'user_prompt:representative-qa-v1'},
                           {'input_key':'cleaned_text','output_key':'qa_pairs','output_meta_key':'qa_metadata'}),
                        op('TrainingQAExpander', '展开嵌套 QA，保留来源、问题和回答', run={
                            'input_key':'qa_pairs','output_key':'candidate_a','output_question_key':'question','output_answer_key':'answer'})]
                final_candidate = 'candidate_a'
                if kind == 'dpo':
                    ops += [gen('representative-text-negative-v1','candidate_b',{'text':'text','question':'question'})]
            else:
                ops += [dedup(['material_id'],'source_unique'), image('representative-image-question-v1','image_question'),
                        image('representative-image-answer-a-v1','candidate_a','image_question')]
                final_candidate = 'candidate_a'
                if kind == 'dpo':
                    ops += [image('representative-image-negative-v1','candidate_b','image_question')]
            if kind == 'dpo':
                ops += [op('TrainingPreferenceBuilder','组合同题正负例；相同回答最多重生成负例 2 次，不评分',init={'llm_serving':None,'max_negative_retries':2},run={
                            'input_key':'candidate_a','input_alternative_key':'candidate_b','output_key':'alternatives'}),
                        synthetic_pair_operator()]
                final_candidate = 'preference_candidate'
            ops += [dedup(['text' if modality=='text' else 'material_id', final_candidate], 'sample_unique'),
                    op('TrainingPairFormatter','校验输出结构并导出训练字段；不做模型评分或质量筛选',
                       {'training_type':kind,'modality':modality,'json_schema':f'schema_ref:representative-{kind}-sample-v1','allow_empty':True},
                       {'input_key':final_candidate,'output_key':'training_sample'})]
            for index, item in enumerate(ops):
                item['location'] = [320+index*320,150]
            key = f'representative-{modality}-{kind}-v1'
            result.append(dict(id=key, name=f'代表性{label} {kind.upper()}',tags=['template','representative-training',modality,kind],
                config={'file_path':'','input_dataset':{'id':'','location':[30,150]},'operators':ops,'execution_options':{
                    'simple_training':{'modality':modality,'training_type':kind},'representative_training':True,
                    'capture_responses':True,'training_output':True,'additional_retries':0,
                    'scoring_policy':'none','preference_policy':'synthetic_positive_negative' if kind=='dpo' else None}}))
    return result


def install_templates(c):
    """Install and migrate representative configurations with recoverable backups."""
    data = c.pipeline_registry._read()
    legacy = {key:data['pipelines'][key] for key in LEGACY_IDS if key in data['pipelines']}
    if legacy:
        # A recoverable snapshot precedes removal, including independently edited
        # legacy resource content. Never include serving records/credentials.
        old = dict(pipelines=legacy, prompts=[r for r in c.user_prompt_registry.list_all() if r['id'] in LEGACY_IDS],
                   schemas=[r for r in c.json_schema_manager.list_all() if r['id'] in LEGACY_IDS])
        backup = Path(c.pipeline_registry.path).parent/'backups'/'replaced-simple-training'
        atomic_write(backup/(_hash(_json_bytes(old))+'.json'), _json_bytes(old))
        for key in legacy:
            del data['pipelines'][key]
        c.pipeline_registry._write(data)
        # Delete old resources only if no remaining saved pipeline references them.
        remaining = json.dumps(data,ensure_ascii=False)
        for manager in (c.user_prompt_registry, c.json_schema_manager):
            with manager.store.writing() as records:
                for key in legacy:
                    if key not in remaining:
                        records.pop(key,None)
    prompts, schemas = resources()
    templates = definitions()
    now = _now()
    # Seed shared resources only on initial installation. Recreating one removed
    # template must not resurrect resources deleted from independent managers.
    if not any(d['id'] in data['pipelines'] for d in templates):
        for manager, defaults in ((c.user_prompt_registry,prompts),(c.json_schema_manager,schemas)):
            with manager.store.writing() as records:
                for default in defaults:
                    if default['id'] not in records:
                        record = dict(default,description='代表性流程验收资源；结构和模型评分均不等于训练收益。',
                                      created_at=now,updated_at=now,usage=default.get('usage','通用'))
                        if 'template' in record:
                            record.setdefault('example_variables',{})
                        else:
                            record.update(schema=json.dumps(record['schema'],ensure_ascii=False),example='',purpose='模型输出')
                        records[record['id']] = record
    old = {key:copy.deepcopy(record) for key,record in data['pipelines'].items()
           if record.get('config',{}).get('execution_options',{}).get('representative_training')
           and record['config']['execution_options'].get('scoring_policy') != 'none'}
    if old:
        backup = Path(c.pipeline_registry.path).parent/'backups'/'removed-training-scoring'
        atomic_write(backup/(_hash(_json_bytes(old))+'.json'), _json_bytes(old))
        with c.user_prompt_registry.store.writing() as records:
            for prompt in prompts:
                if prompt['id'] in {'representative-text-negative-v1','representative-image-negative-v1'} and prompt['id'] not in records:
                    records[prompt['id']]=dict(prompt,description='合成负例，无独立评分',created_at=now,updated_at=now)
        for key,record in old.items():
            record['config']=remove_scoring(record['config'])
            record['updated_at']=now
            data['pipelines'][key]=record
        c.pipeline_registry._write(data)
    for definition in templates:
        data = c.pipeline_registry._read()
        if definition['id'] in data['pipelines']:
            continue
        pipeline = copy.deepcopy(definition)
        pipeline.update(created_at=now,updated_at=now,status='queued')
        for item in pipeline['config']['operators']:
            item['params'] = c.pipeline_registry._parse_frontend_params(item['params'])
        data['pipelines'][pipeline['id']] = c.pipeline_registry._enrich_pipeline_operators_internal(pipeline)
        c.pipeline_registry._write(data)
    data = c.pipeline_registry._read()
    old = {key:copy.deepcopy(record) for key,record in data['pipelines'].items()
           if record.get('config',{}).get('execution_options',{}).get('representative_training')
           and record['config']['execution_options'].get('row_isolation_version') != 1}
    if old:
        backup = Path(c.pipeline_registry.path).parent/'backups'/'training-row-isolation'
        atomic_write(backup/(_hash(_json_bytes(old))+'.json'), _json_bytes(old))
        for key,record in old.items():
            record['config'] = isolate_rows(record['config'])
            record['updated_at'] = now
            data['pipelines'][key] = record
        c.pipeline_registry._write(data)


def isolate_rows(config):
    config = copy.deepcopy(config)
    options = config.setdefault('execution_options', {})
    if options.get('row_isolation_version') == 1:
        return config
    service = None
    for op in config.get('operators', []):
        for param in op['params']['init']:
            if param['name'] == 'llm_serving' and param.get('value'):
                service = param['value']
        if op['name'] == 'TrainingPreferenceBuilder':
            params = op['params']['init']
            values = {p['name']: p for p in params}
            if 'llm_serving' not in values:
                params.append(dict(name='llm_serving', value=service, default_value=None))
            elif not values['llm_serving'].get('value'):
                values['llm_serving']['value'] = service
            if 'max_negative_retries' not in values:
                params.append(dict(name='max_negative_retries', value=2, default_value=2))
            op['pipeline_role'] = '组合同题正负例；相同回答有界重生成负例，失败样本单独记录'
    options['row_isolation_version'] = 1
    return config
