"""Inspect DataFlex YAML and AST without importing training dependencies."""
from pathlib import Path
import ast,json,subprocess,hashlib
import yaml
import argparse
parser=argparse.ArgumentParser();parser.add_argument('--source',required=True);args=parser.parse_args()
base=Path(__file__).resolve().parents[2];src=Path(args.source).resolve()
presets=yaml.safe_load((src/'src/dataflex/configs/components.yaml').read_text()); commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=src,text=True).strip()
catalog={}
for family,bucket in [('selection','selectors'),('mixture','mixers'),('reweighting','weighters'),('reorder','reorders'),('lego','pipelines')]:
 for name,c in presets[bucket].items():
  impl=[];args=[];imports=[]
  for path in (src/'src/dataflex/train').rglob('*.py'):
   tree=ast.parse(path.read_text())
   for node in ast.walk(tree):
    if isinstance(node,ast.ClassDef) and any(isinstance(d,ast.Call) and any(isinstance(a,ast.Constant) and a.value in [name,c.get('params',{}).get('kind')] for a in d.args) for d in node.decorator_list):
     if family!='lego' and {'selection':'selector','mixture':'mixer','reweighting':'weighter','reorder':'reorder'}[family] not in str(path):continue
     impl.append(str(path.relative_to(src)));imports+= [ast.unparse(n) for n in tree.body if isinstance(n,(ast.Import,ast.ImportFrom))]
     for fun in node.body:
      if isinstance(fun,ast.FunctionDef) and fun.name=='__init__':args += [a.arg for a in fun.args.args[1:]+fun.args.kwonlyargs]
  params=c.get('params',{}); fields={}
  for k,v in params.items():
   typ='boolean' if isinstance(v,bool) else 'integer' if isinstance(v,int) else 'number' if isinstance(v,float) else 'array' if isinstance(v,list) else 'object' if isinstance(v,dict) else 'string' if isinstance(v,str) else 'any'
   fields[k]={'type':typ,'default':v}
  reference='eval_dataset' in args or name in ['adapt','joint_update_aware','dynamic_moe']
  modalities=['image_text'] if name in ['coincide'] else ['text','image_text']
  prerequisites=[]
  if name in ['tsds','near']:prerequisites.append('离线索引/概率文件，需要显式快照')
  if name in ['nice']:prerequisites.append('奖励模型或 API 环境，需额外准备')
  if name=='doremi':prerequisites.append('独立参考模型 checkpoint；三阶段训练需分别建立方案')
  if name=='dynamic_moe':prerequisites.append('MoE 模型与 gate 指标')
  if name in ['less','cluster_less','icons','adapt_inf']:prerequisites.append('梯度投影/聚类依赖与额外显存')
  if name=='coincide':prerequisites.append('多模态模型内部表示与图像处理环境')
  catalog[family+':'+name]={'id':family+':'+name,'family':family,'bucket':bucket,'name':name,'implementation_name':c.get('name',name),'fields':fields,'defaults':params,'tasks':['sft','pt'],'modalities':modalities,'requires_reference':reference,'prerequisites':prerequisites,'source':impl,'constructor_args':sorted(set(args)),'imports':sorted(set(imports)),'source_commit':commit,'validation':'source_inspected_runtime_not_run','adaptation':'configuration; environment/GPU validation pending'}
# Every registered selector, even where upstream has no preset.
for path in (src/'src/dataflex/train/selector').glob('*.py'):
 tree=ast.parse(path.read_text())
 for node in ast.walk(tree):
  if isinstance(node,ast.ClassDef):
   for d in node.decorator_list:
    if isinstance(d,ast.Call) and isinstance(d.func,ast.Name) and d.func.id=='register_selector' and d.args and isinstance(d.args[0],ast.Constant):
     name=d.args[0].value
     if 'selection:'+name not in catalog:
      fun=next(n for n in node.body if isinstance(n,ast.FunctionDef) and n.name=='__init__')
      defaults={}
      for a,v in zip(fun.args.args[-len(fun.args.defaults):],fun.args.defaults):
       try:defaults[a.arg]=ast.literal_eval(v)
       except ValueError:pass
      defaults.pop('eval_dataset',None)
      catalog['selection:'+name]={'id':'selection:'+name,'family':'selection','bucket':'selectors','name':name,'implementation_name':name,'defaults':defaults,'fields':{k:{'type':'any','default':v} for k,v in defaults.items()},'tasks':['sft','pt'],'modalities':['text','image_text'],'requires_reference':True,'prerequisites':['梯度投影与参考集；依赖需环境预检'],'source':[str(path.relative_to(src))],'source_commit':commit,'constructor_args':[a.arg for a in fun.args.args[1:]],'validation':'source_inspected_runtime_not_run','adaptation':'configuration; environment/GPU validation pending'}
(base/'backend/app/templates/dataflex_catalog.json').write_text(json.dumps({'schema_version':1,'source_commit':commit,'source_config_sha256':hashlib.sha256((src/'src/dataflex/configs/components.yaml').read_bytes()).hexdigest(),'components':list(catalog.values())},ensure_ascii=False,indent=2))
