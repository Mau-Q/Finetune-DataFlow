"""Regenerate the explicit LAN business route inventory from local router source (no imports)."""
import ast
import json
from pathlib import Path

BASE=Path(__file__).resolve().parents[1]
PREFIXES={'datasets':'datasets','operators':'operators','tasks':'tasks','pipelines':'pipelines','prompts':'prompts','serving':'serving','preferences':'preferences','json_schemas':'json_schemas','data_library':'library','generation':'generation','multimodal':'multimodal','model_training':'training','team_data':'team-data'}
records=[]
for module,prefix in PREFIXES.items():
    source=BASE/'app/api/v1/endpoints'/f'{module}.py'
    for node in ast.parse(source.read_text('utf-8')).body:
        if not isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):continue
        for decorator in node.decorator_list:
            if not isinstance(decorator,ast.Call) or not isinstance(decorator.func,ast.Attribute) or decorator.func.attr not in {'get','post','put','patch','delete','head'}:continue
            if not decorator.args or not isinstance(decorator.args[0],ast.Constant):continue
            records.append({'method':decorator.func.attr.upper(),'path':'/api/v1/'+prefix+decorator.args[0].value,'source':str(source.relative_to(BASE)),'function':node.name})
records.sort(key=lambda r:(r['path'],r['method']))
target=BASE/'app/team_routes.json';target.write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n')
print(f'{len(records)} explicit business routes recorded; Agent, MCP, WebSocket and host database routes excluded.')
