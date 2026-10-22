"""Run an isolated manual-acceptance server using the built WebUI and real result APIs.

PYTHONPATH=backend:<DataFlow source> python backend/scripts/preview_task_results.py --root <empty directory> --port 8001
Only fixture task metadata is simulated; collection, SQLite, media and releases use real services.
No model execution, production configuration or production database is loaded.
"""
import argparse
import io
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
import uvicorn
from app.core.config import settings
from app.core.container import container
from app.services.data_library import DataLibrary, _json_bytes
from app.schemas.data_library import DraftCreate
from app.api.v1.endpoints import tasks, data_library, generation
from app.api.v1.handlers import install_exception_handlers
from app.api.v1.resp import ok


def create_preview(root, configure=None):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    # Hard boundary: never point this tool at an existing data directory.
    if list(root.iterdir()):
        raise ValueError('隔离验收目录必须为空；请使用一个新目录')
    settings.BASE_DIR = str(root)
    settings.RESOURCE_DIR = 'data'
    settings.CACHE_DIR = str(root/'cache')
    lib = DataLibrary(root/'data'/'library')
    container.data_library = lib
    records = {}
    now = datetime.now(timezone.utc).isoformat()
    def row(question, answer):
        return {'instruction': question, 'input': '', 'output': answer}
    q1 = row('栈采用什么访问顺序？', '后进先出（LIFO）。')
    q2 = row('队列采用什么访问顺序？', '先进先出（FIFO）。')
    q3 = row('二分查找要求什么条件？', '数据有序，并能高效访问中间位置。')
    draft = lib.create_draft(DraftCreate(name='隔离 · 已有文本 SFT'))
    lib.import_rows(draft['id'], 'existing.json', _json_bytes([q1]), {})
    buffer=io.BytesIO();Image.new('RGB',(160,100),'red').save(buffer,format='PNG')
    image=lib.add_material('red.png',buffer.getvalue(),{'name':'隔离 · 红色图片'})
    fixtures = [
        ('isolated-new', '隔离 · 新建与追加', [q1,q2,q2], 'completed'),
        ('isolated-second', '隔离 · 第二次运行', [q2,q3], 'completed'),
        ('isolated-image', '隔离 · 图文绑定', [dict(row('图片是什么颜色？','红色。'),images=['images/red.png'])], 'completed'),
        ('isolated-invalid', '隔离 · 非训练结构', [{'text':'只有普通文本，缺少训练问答字段。'}], 'completed'),
        ('isolated-empty', '隔离 · 零样本', [], 'completed'),
        ('isolated-failed', '隔离 · 失败任务', [q1], 'failed'),
    ]
    for tid,name,rows,status in fixtures:
        path=root/'cache'/tid/'final.jsonl';path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(b''.join(_json_bytes(r)+b'\n' for r in rows))
        records[tid] = dict(task_id=tid,pipeline_id=None,name=name,status=status,created_at=now,completed_at=now,
            pipeline_config={'file_path':'isolated_fixture.py','input_dataset':'isolated-source','operators':[{'name':'FixtureOutput','params':{'init':[],'run':[]}}]},
            output={'execution_results':[{'index':0,'status':'completed','file_path':str(path)}]},logs=['隔离样例：固定文件，无模型调用。'])
    container.task_registry = SimpleNamespace(get=records.get, list_executions=lambda:list(records.values()))
    (root/'fixture-tasks.json').write_bytes(_json_bytes(records))
    app=FastAPI(title='隔离验收 · Pipeline 结果收录')
    app.include_router(tasks.router,prefix='/api/v1/tasks')
    app.include_router(data_library.router,prefix='/api/v1/library')
    app.include_router(generation.router,prefix='/api/v1/generation')
    install_exception_handlers(app)
    @app.get('/acceptance',response_class=HTMLResponse)
    def guide():
        links=''.join(f'<li><a target="_blank" href="/#/m/?task={tid}">{name}</a></li>' for tid,name,_,_ in fixtures)
        return f'''<!doctype html><html lang="zh"><meta charset="utf-8"><title>隔离验收</title><style>body{{font:16px/1.8 system-ui;max-width:900px;margin:48px auto;padding:0 24px;color:#26334d}}a{{color:#4e5bd5}}li{{margin:10px 0}}code{{overflow-wrap:anywhere}}</style>
        <h1>Pipeline 结果收录 · 隔离验收</h1><p>此端口只连接隔离目录：<code>{root}</code>。任务输出是固定样例；收录、数据库、图片、来源和发布接口均使用实际实现。无模型调用。</p>
        <h2>样例入口</h2><ul>{links}</ul>
        <h2>建议验收顺序</h2><ol>
        <li>打开“新建与追加”，预览 3 行（其中 1 行重复）。新建名称自定，预期新增 2 条、跳过 1 条。</li>
        <li>保持新建方式再点确认收录，预期提示已收录，数据集仍只有 2 条。</li>
        <li>改为追加，选择“隔离 · 已有文本 SFT”（初始 1 条），预期新增 1 条、跳过 2 条，总共 2 条。</li>
        <li>打开“第二次运行”，追加到刚才新建的数据集，预期新增 1 条、跳过 1 条，总共 3 条。</li>
        <li>点击“已收录到”的数据集链接，展开“数据集详情”查看来源任务，再点任务链接返回运行记录。编辑数据集样本后，原始最终结果保持不变。</li>
        <li>打开“图文绑定”，选择“隔离 · 红色图片”后新建，预期新增 1 条；进入数据集展开样本可看到图片。</li>
        <li>非训练结构与零样本可保留结果但没有收录表单；失败任务不可收录。</li></ol>
        <p><a target="_blank" href="/#/m/training-datasets">打开隔离生成数据集列表</a> · 刷新页面会保留本次验收数据。</p><p>所有操作仅影响此目录。关闭服务后该地址失效；重新验收请使用新的空目录。</p></html>'''
    if configure is not None:
        configure(app, root, lib, records)

    # Canvas initialization reads optional catalog resources; no production registries.
    @app.get('/api/v1/{path:path}')
    def empty_catalog(path: str):
        if path.startswith(('serving','pipelines','datasets','operators','text2sql_database_manager')):
            return ok([])
        if path.startswith('preferences'):
            return ok({'language': 'cn'})
        if path.startswith('prompts'):
            return ok({})
        raise HTTPException(404,'隔离服务不提供此功能')
    dist=Path(__file__).resolve().parents[2]/'frontend'/'dist'
    if not (dist/'index.html').exists():
        raise ValueError('请先构建 frontend')
    app.mount('/',StaticFiles(directory=dist,html=True),name='ui')
    (root/'README.txt').write_text('隔离验收目录。所有数据可丢弃；无正式数据库连接。\n'+str(root),encoding='utf-8')
    return app


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);parser.add_argument('--port',type=int,default=8001)
    args=parser.parse_args()
    uvicorn.run(create_preview(args.root),host='127.0.0.1',port=args.port,log_level='warning')
