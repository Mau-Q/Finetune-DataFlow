"""Isolated native forms and cross-tab synchronization acceptance, no model calls."""
import argparse
from types import SimpleNamespace
from fastapi.responses import HTMLResponse
import uvicorn
from preview_task_results import create_preview
from app.core.config import settings
from app.core.container import container
from app.services.user_prompt_registry import UserPromptRegistry
from app.services.json_schema_manager import JsonSchemaManager
from app.services.dataset_registry import DatasetRegistry
from app.api.v1.endpoints import prompts, json_schemas, datasets, preferences


def configure(app, root, library, records):
    settings.PREFERENCES_PATH=str(root/'data'/'user_preferences.json')
    (root/'data'/'user_preferences.json').write_text('{"language":"cn","theme":"light"}')
    own=UserPromptRegistry(root/'data'/'prompts.json')
    schemas=JsonSchemaManager(root/'data'/'schemas.json')
    prompt=own.create('隔离 · 问答模板','用于原生表单验收','回答问题：{question}',['FormatStrPromptedGenerator'],{'question':'什么是栈？'},usage='文本 SFT',purpose='生成')
    schema=schemas.create('隔离 · 问答 Schema','','{"type":"object","properties":{"answer":{"type":"string"}},"required":["answer"]}','{"answer":"后进先出"}',usage='文本 SFT',purpose='模型输出')
    pipeline={'id':'isolated-text','name':'隔离 · 文本 SFT','tags':['platform-text'], 'config':{'operators':[{'name':'FormatStrPromptedGenerator','params':{'init':[{'name':'prompt_template','value':{'ref':'user_prompt:'+prompt['id'],'bindings':{'question':'text'}}},{'name':'json_schema','value':'schema_ref:'+schema['id']}],'run':[]}}]}}
    container.user_prompt_registry=own
    container.json_schema_manager=schemas
    container.dataset_registry=DatasetRegistry(str(root/'data'/'registry.yaml'),scan=False)
    container.pipeline_registry=SimpleNamespace(list_pipelines=lambda:[pipeline],_is_preset_pipeline=lambda p:False)
    container.prompt_registry=SimpleNamespace(list_prompt_info=lambda:SimpleNamespace(model_dump=lambda:{'prompts':{}}))
    container.operator_registry=SimpleNamespace(get_op_details=lambda name:{'parameter':{'init':[{'name':'json_schema'}],'run':[]}})
    app.include_router(prompts.router,prefix='/api/v1/prompts')
    app.include_router(json_schemas.router,prefix='/api/v1/json_schemas')
    app.include_router(datasets.router,prefix='/api/v1/datasets')
    app.include_router(preferences.router,prefix='/api/v1/preferences')
    @app.get('/forms-acceptance',response_class=HTMLResponse)
    def guide():
        return f'''<!doctype html><html lang="zh"><meta charset="utf-8"><title>原生表单与同步验收</title><style>body{{font:16px/1.8 system-ui;max-width:900px;margin:40px auto;padding:0 24px;color:#26334d}}a{{color:#4e5bd5}}li{{margin:10px 0}}code{{overflow-wrap:anywhere}}</style><h1>原生表单与同步 · 隔离验收</h1><p>独立目录：<code>{root}</code>。使用真实资源、数据集和收录接口，固定样例任务，无模型调用。</p><ul>
        <li><a target="_blank" href="/#/m/materials">原始数据集：添加弹窗、系统选择或拖入文件</a></li>
        <li><a target="_blank" href="/#/m/training-datasets">生成数据集：新建、JSON/JSONL 导入和图片绑定</a></li>
        <li><a target="_blank" href="/#/m/prompts">Prompt：筛选、编辑、预览和复制</a></li>
        <li><a target="_blank" href="/#/m/schemas">Schema：筛选、编辑与校验</a></li>
        <li><a target="_blank" href="/#/m/?task=isolated-new">运行记录：收录并观察数据集计数</a></li></ul>
        <h2>同步检查</h2><ol><li>设置筛选后打开资源详情，再返回或刷新，筛选应保持；清除筛选后刷新应保持清除。</li><li>打开两个 Prompt 页；一页保存改名，另一页应刷新列表。若另一页正在编辑，则保留输入，取消编辑后读取新版本。</li><li>打开生成数据集列表，再在另一页收录任务；列表应出现新数据集。编辑或导入后，运行结果的关联数量应更新。</li><li>新建生成数据集后自动进入详情并打开导入；导入完成显示新计数，重复样本不重复写入。</li><li>切换原始／生成数据集、切换资源或关闭弹窗后，旧请求不应覆盖新页面。</li><li>通过设置切换明暗主题，检查控件和弹窗；此设置也只写入隔离目录。</li></ol><p>此环境不执行 Pipeline，不连接正式数据库。</p></html>'''


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);parser.add_argument('--port',type=int,default=8003);args=parser.parse_args()
    uvicorn.run(create_preview(args.root,configure),host='127.0.0.1',port=args.port,log_level='warning')
