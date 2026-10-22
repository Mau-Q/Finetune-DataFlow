"""Isolated native SFT Prompt acceptance. All writes stay under a new empty root."""
import argparse
from types import SimpleNamespace
from app.schemas.prompt import PromptInfoMapOut
from fastapi import HTTPException
from fastapi.responses import HTMLResponse
import uvicorn
from preview_task_results import create_preview
from preview_native_forms import configure as base_configure
from app.core.container import container
from app.api.v1.resp import ok
from app.api.v1.endpoints import pipelines, operators, multimodal
from app.services.prompt_contracts import CONTRACTS
from app.services.multimodal_templates import MultimodalTemplates, template as mm_template
from app.schemas.data_library import DraftCreate
from app.services.operator_registry import OperatorRegistry
from app.services.pipeline_registry import PipelineRegistry
from app.services.resource_resolution import resolve_pipeline_resources, instantiate_prompt
from app.services.data_library import _json_bytes
from dataflow.operators.knowledge_cleaning import KBCTextCleaner
from dataflow.operators.core_text import Text2MultiHopQAGenerator, Text2QASampleEvaluator
from dataflow.operators.text_sft import AlpagasusSampleEvaluator

CLASSES = {cls.__name__:cls for cls in [KBCTextCleaner,Text2MultiHopQAGenerator,Text2QASampleEvaluator,AlpagasusSampleEvaluator]}


def configure(app,root,library,records):
    base_configure(app,root,library,records)
    registry=OperatorRegistry.__new__(OperatorRegistry)
    registry.op_obj_map=CLASSES
    registry.op_to_type={}
    container.operator_registry=registry
    container.prompt_registry=SimpleNamespace(list_prompt_info=lambda:PromptInfoMapOut(prompts={}))
    # Never scan production pipelines or operator caches.
    pipeline_registry=PipelineRegistry.__new__(PipelineRegistry)
    pipeline_registry.path=str(root/'data'/'pipelines.json')
    pipeline_registry._write({'pipelines':{}})
    container.pipeline_registry=pipeline_registry
    source=root/'data'/'source.jsonl'
    source.write_text('{"text":"栈采用后进先出。","question":"栈的访问顺序？","answer":"后进先出。","context":"栈采用后进先出。","instruction":"说明栈。","input":"","output":"栈采用后进先出。"}\n')
    ds=container.dataset_registry.add_or_update(dict(name='隔离 · Prompt 输入',root=str(source),type='text',tags=[],pipeline=''))
    dataset=next(d for d in container.dataset_registry.list() if d['root']==str(source))
    created=[]
    for name,cls in CLASSES.items():
        init=[]
        for param,rule in CONTRACTS[name].items():
            text=('请保留事实并清洗：{text}' if name=='KBCTextCleaner' else '请依据材料生成多跳问答：{text}' if name=='Text2MultiHopQAGenerator' else '请严格依据来源证据评价，避免偏爱冗长答案。')
            rec=container.user_prompt_registry.create('隔离 · '+rule['label'],'SFT Prompt 接入验收',text,[name],usage='文本 SFT',purpose='评分' if 'Evaluator' in name else '生成')
            init.append(dict(name=param,value={'ref':'user_prompt:'+rec['id']}))
        run={'KBCTextCleaner':dict(input_key='text',output_key='cleaned'),
             'Text2MultiHopQAGenerator':dict(input_key='text',output_key='qa_pairs',output_meta_key='metadata'),
             'Text2QASampleEvaluator':dict(input_question_key='question',input_answer_key='answer',input_context_key='context'),
             'AlpagasusSampleEvaluator':dict(input_instruction_key='instruction',input_input_key='input',input_output_key='output')}[name]
        body=dict(name='隔离 · '+name,tags=['platform-text','sft'],config=dict(file_path='',input_dataset={'id':dataset['id'],'location':[30,100]},operators=[dict(name=name,location=[360,100],params=dict(init=init,run=[dict(name=k,value=v) for k,v in run.items()]))]))
        created.append(pipeline_registry.create_pipeline(body))
    mm_config=mm_template()['config']
    mm_config['material_ids']=[m['id'] for m in library.list_materials() if m['kind']=='image']
    mm_config['draft_id']=library.create_draft(DraftCreate(name='隔离 · 图片 SFT 输出',modality='image_text'))['id']
    for step in mm_config['steps'][:2]:
        text='观察图片，提出一个可由图像证据回答的问题。' if step['id']=='question' else '仅依据图片回答：{question}'
        resource=container.user_prompt_registry.create('隔离 · 图片'+('问题' if step['id']=='question' else '答案'),'',text,['PromptedVQAGenerator'],usage='图文 SFT',purpose='生成')
        step['resource_ref']='user_prompt:'+resource['id']
    mm_record=MultimodalTemplates().save('隔离 · 图片 SFT Prompt',mm_config)
    # Provide fresh details without touching the global on-disk ops cache.
    @app.get('/api/v1/operators/details')
    def isolated_details(lang='zh'):
        buckets={}
        for name in CLASSES:
            detail=registry.get_op_details(name,lang)
            buckets.setdefault(detail['type']['level_1'],[]).append(detail)
        return ok(buckets)
    app.include_router(operators.router,prefix='/api/v1/operators')
    app.include_router(pipelines.router,prefix='/api/v1/pipelines')
    app.include_router(multimodal.router,prefix='/api/v1/multimodal')
    @app.post('/api/v1/prompt-acceptance/verify')
    def verify():
        """Render actual current saved references; never call a model or serving."""
        results=[]
        for item in pipeline_registry.list_pipelines():
            try:
                frozen,snapshots=resolve_pipeline_resources(item['config'])
                op=frozen['operators'][0]
                for param in op['params']['init']:
                    if param['name'] not in CONTRACTS[op['name']] or not param.get('value'):
                        continue
                    prompt=instantiate_prompt(param['value'])
                    rendered=prompt.build_prompt('隔离样例材料：栈采用后进先出。') if op['name'] in ('KBCTextCleaner','Text2MultiHopQAGenerator') else prompt.build_prompt()
                    results.append(dict(pipeline_id=item['id'],operator=op['name'],slot=param['name'],rendered=rendered,resource_snapshots=snapshots))
            except ValueError as exc:
                raise HTTPException(422,str(exc)) from exc
        (root/'last-prompt-verification.json').write_bytes(_json_bytes(results))
        return ok(results)
    @app.get('/prompt-acceptance',response_class=HTMLResponse)
    def guide():
        links=f'<li><a target="_blank" href="/#/m/?workflow=multimodal&config={mm_record["id"]}">隔离 · 图片 SFT 问题与答案</a></li>'+''.join(f'<li><a target="_blank" href="/#/m/?pipeline={p["id"]}">{p["name"]}</a></li>' for p in created)
        return '''<!doctype html><meta charset="utf-8"><title>SFT Prompt 隔离验收</title><style>body{font:16px/1.8 system-ui;max-width:950px;margin:36px auto;padding:0 24px;color:#26334d}li{margin:10px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f4f8;padding:16px}button{font:inherit;padding:8px 16px}a{color:#4e5bd5}</style><h1>SFT Prompt 管理 · 隔离验收</h1><p>独立注册表和数据库，无模型调用。以下为文本 SFT 四个模型算子的最小配置，覆盖七个模板位置。运行按钮不提供真实生成服务。</p><ol><li><a target="_blank" href="/#/m/prompts">打开 Prompt 管理</a>，修改一个“隔离”模板并保存。</li><li>打开下面相应流程，点击“参数详情”，选择模板，检查协议提示，再保存并刷新确认引用保留。</li><li>清洗和 QA 模板必须含 {text}；评分模板不填写变量，问题/答案/来源由算子拼接。可尝试不符合要求的模板，保存/检查必须报错。</li><li>点击下方按钮，显示当前已保存配置解析后的模板及快照。它不调用模型。评分的实际拼接和分数解析由自动化测试覆盖。</li><li><a target="_blank" href="/#/m?workflow=multimodal">打开图片 SFT</a>：问题、答案步骤可引用模板；答案必须保留 {question} 并绑定问题字段。视觉执行仍明确阻止。</li></ol><ul>''' +links+'''</ul><button onclick="verify()">验证当前已保存的 Prompt 引用</button><pre id="result">尚未验证</pre><script>async function verify(){const r=await fetch('/api/v1/prompt-acceptance/verify',{method:'POST'});document.getElementById('result').textContent=JSON.stringify(await r.json(),null,2)}</script><p>所有修改只影响此目录：'''+str(root)+'''</p>'''

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);parser.add_argument('--port',type=int,default=8005);args=parser.parse_args()
    uvicorn.run(create_preview(args.root,configure),host='127.0.0.1',port=args.port,log_level='warning')
