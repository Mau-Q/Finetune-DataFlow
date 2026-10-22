"""Declarative component configuration. No imports of user Python or training packages."""
from app.services.model_training import training_transaction
import copy
import json
import math
from pathlib import Path
import yaml
from app.services.model_training import TrainingError

FAMILIES={'selection':('selectors','dynamic_select'),'mixture':('mixers','dynamic_mix'),'reweighting':('weighters','dynamic_weight'),'reorder':('reorders','dynamic_reorder'),'lego':('pipelines','dynamic_lego')}
CATALOG=Path(__file__).parents[1]/'templates/dataflex_catalog.json'

def catalog(service):
    result=json.loads(CATALOG.read_text(encoding='utf-8'))
    result['components'] += [r['descriptor'] for r in service.list('components')]
    return result


@training_transaction
def save_descriptor(service, descriptor):
    import re
    if not isinstance(descriptor,dict) or descriptor.get('family') not in FAMILIES or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}',descriptor.get('name','')):
        raise TrainingError('组件需要合法 family 和 name')
    if descriptor['family']=='lego': raise TrainingError('Lego 请使用阶段列表引用已注册组件')
    for key,allowed in [('tasks',{'sft','pt'}),('modalities',{'text','image_text'})]:
        values=descriptor.get(key,['sft'] if key=='tasks' else ['text'])
        if not isinstance(values,list) or not values or not all(isinstance(x,str) and x in allowed for x in values):raise TrainingError(key+': 不支持的任务/模态列表')
    if 'defaults' in descriptor and not isinstance(descriptor['defaults'],dict):raise TrainingError('defaults 需要对象')
    if not isinstance(descriptor.get('dependencies',[]),list) or not all(isinstance(x,str) for x in descriptor.get('dependencies',[])):raise TrainingError('dependencies 需要包名列表')
    if not isinstance(descriptor.get('fields'),dict): raise TrainingError('fields 必须为参数描述对象')
    for key,field in descriptor['fields'].items():
        if not isinstance(field,dict) or field.get('type') not in ['string','integer','number','boolean','array','object','any']:
            raise TrainingError(f'fields.{key}: 参数类型无效')
    descriptor=copy.deepcopy(descriptor)
    descriptor.update(id=descriptor['family']+':'+descriptor['name'],bucket=FAMILIES[descriptor['family']][0],validation='custom_not_environment_checked')
    descriptor.setdefault('defaults',{k:v.get('default') for k,v in descriptor['fields'].items()})
    descriptor.setdefault('tasks',['sft']);descriptor.setdefault('modalities',['text'])
    if descriptor['id'] in {c['id'] for c in catalog(service)['components']}: raise TrainingError('组件标识已存在',409)
    return service.put('components',{'descriptor':descriptor})


def compile_plan(service, plan):
    checks=service.check(plan)
    errors=checks['errors'];warnings=[]
    entries={c['id']:c for c in catalog(service)['components']}
    strategy=plan['strategy']
    if not isinstance(strategy,dict):raise TrainingError('strategy 必须是对象')
    family=strategy.get('family','static');component=strategy.get('component','')
    if not isinstance(family,str) or not isinstance(component,str):raise TrainingError('family/component 需要字符串')
    if not isinstance(strategy.get('params',{}),dict):raise TrainingError('strategy.params 必须是对象')
    if family!='static' and (type(strategy.get('update_step',10)) is not int or strategy.get('update_step',10)<1 or type(strategy.get('warmup_step',0)) is not int or strategy.get('warmup_step',0)<0):errors.append('strategy: update_step 必须为正整数，warmup_step 必须非负')
    components={bucket:{} for bucket,_ in FAMILIES.values()}
    effective={}
    def use(f,name,overrides):
        c=entries.get(f+':'+name)
        if not c: errors.append(f'strategy.{f}.{name}: 组件不存在');return {}
        if plan['task'] not in c.get('tasks',[]) or plan['modality'] not in c.get('modalities',[]): errors.append(f'{f}.{name}: 不支持当前任务/模态')
        if not isinstance(overrides,dict):errors.append(f'{f}.{name}: 参数必须为对象');return {}
        params=copy.deepcopy(c.get('defaults',{}));params.update(overrides)
        if c.get('requires_reference') and not any(b['role']=='reference' for b in plan['data']): errors.append(f'{f}.{name}: 需要策略目标参考集')
        for key,field in c.get('fields',{}).items():
            if field.get('required') and params.get(key) is None:errors.append(f'{f}.{name}.{key}: 必填参数缺失')
        for key,value in params.items():
            field=c.get('fields',{}).get(key)
            if not field: warnings.append(f'{f}.{name}.{key}: 未完成语义检查');continue
            typ=field.get('type','any')
            if typ in ['any','object','array']:warnings.append(f'{f}.{name}.{key}: 已检查结构，算法特定语义待环境验证')
            valid={'string':isinstance(value,str),'integer':type(value) is int,'number':type(value) in (int,float),'boolean':type(value) is bool,'array':isinstance(value,list),'object':isinstance(value,dict),'any':True}[typ]
            if value is not None and not valid: errors.append(f'{f}.{name}.{key}: 需要 {typ}')
            if type(value) in (int,float):
                if not math.isfinite(value):errors.append(f'{key}: 需要有限数值')
                if 'minimum' in field and value<field['minimum']:errors.append(f'{key}: 小于最小值')
                if 'maximum' in field and value>field['maximum']:errors.append(f'{key}: 大于最大值')
            if field.get('enum') and value not in field['enum']:errors.append(f'{key}: 不在允许值中')
        for k in ['alpha','min_exploration_rate','damping']:
            if k in params and (type(params[k]) not in (int,float) or not 0<=params[k]<=1):errors.append(f'{k}: 需要 0 到 1 之间的数值')
        if f=='mixture':
            domains=sum(b['role']=='train' for b in plan['data'])
            if domains<2:errors.append(f'{f}.{name}: 至少绑定两个训练域')
            for k in ['proportions','initial_proportions']:
                ratios=params.get(k)
                if ratios is not None and (not isinstance(ratios,list) or len(ratios)!=domains or any(type(x) not in (int,float) or x<0 for x in ratios) or abs(sum(ratios)-1)>1e-6):errors.append(f'{k}: 数量需匹配训练域，非负且总和为 1')
        if f=='reorder' and params.get('pattern') in ['stair','saw']:
            pp=params.get('pattern_params',{})
            if not isinstance(pp,dict):pp={};errors.append('pattern_params: 需要对象')
            if type(pp.get('num_sections',1)) is not int or type(pp.get('folding_ratio',0)) not in (int,float):errors.append('pattern_params: num_sections/folding_ratio 需要数值');pp={}
            if pp.get('num_sections',0)<1 or not 0<=pp.get('folding_ratio',0)<1/(2*pp.get('num_sections',1)):errors.append('pattern_params: folding_ratio 与 num_sections 不兼容')
        warnings.extend(c.get('prerequisites',[]))
        if 'cache_dir' in params: params['cache_dir']='output/strategy/'+f+'_'+name
        components[FAMILIES[f][0]][name]={'name':c.get('implementation_name',name),'params':params}
        return params
    if family!='static':
        if family not in FAMILIES:errors.append('strategy.family: 未知策略')
        else:
            effective=use(family,component,strategy.get('params',{}))
            if family=='lego':
                stages=effective.get('stages',[])
                if not isinstance(stages,list):errors.append('Lego stages 需要列表');stages=[]
                if not stages:errors.append('Lego 缺少阶段列表')
                order={'selector':0,'mixer':1,'reorder':2,'weighter':3};last=-1;draws=0
                for i,s in enumerate(stages):
                    if not isinstance(s,dict):errors.append(f'stages[{i}]: 阶段必须为对象');continue
                    if not s.get('enabled',True):continue
                    sf={'selector':'selection','mixer':'mixture','reorder':'reorder','weighter':'reweighting'}.get(s.get('family'))
                    if not sf:errors.append(f'stages[{i}].family: 无效');continue
                    rank=order[s['family']]
                    if rank<last:errors.append(f'stages[{i}]: 顺序需为 select → mix → reorder → weight')
                    last=rank
                    if type(s.get('every',1)) is not int or s.get('every',1)<1 or type(s.get('keep_ratio',1)) not in (int,float) or not 0<s.get('keep_ratio',1)<=1:errors.append(f'stages[{i}]: every/keep_ratio 无效')
                    if s['family']=='selector' and s.get('mode','draw')=='draw':draws+=1
                    stage_name=s.get('component','')
                    if not isinstance(stage_name,str):errors.append(f'stages[{i}].component: 需要字符串');continue
                    use(sf,stage_name,s.get('params',{}))
                if draws>1:errors.append('Lego 不能有多个 draw 阶段')
    if family!='static' and plan['task']=='dpo':errors.append('DPO 动态训练尚未适配')
    if plan['modality']=='image_text': warnings.append('图文模型/媒体处理能力待 G1 验证')
    train=dict(plan.get('advanced',{}))
    # Paths and identity are owned by the compiler, never arbitrary advanced overrides.
    if train.get('use_swanlab') or any(k in train for k in ['api_key','hub_token','password','secret']):errors.append('advanced: 不接受遥测或凭据字段')
    reserved={'dataset_dir','dataset','eval_dataset','mixer_eval_dataset','output_dir','components_cfg_file','train_type','component_name','packing','report_to','push_to_hub','resume_from_checkpoint'}
    if reserved.intersection(train): errors.append('advanced: 不允许覆盖运行身份、路径、packing、遥测或恢复配置')
    train.update(model_name_or_path=plan['model'],stage=plan['task'],do_train=True,finetuning_type=plan['finetuning_type'],template=plan['template'],max_steps=plan['max_steps'],per_device_train_batch_size=plan['batch_size'],gradient_accumulation_steps=plan['gradient_accumulation_steps'],learning_rate=plan['learning_rate'],seed=plan['seed'],dataset_dir='data',output_dir='output',packing=False,report_to='none',logging_steps=1,save_steps=plan['max_steps'],components_cfg_file='components.yaml',train_type=FAMILIES.get(family,('', 'static'))[1],component_name=component)
    if family!='static':train.update(update_step=strategy.get('update_step',10),update_times=strategy.get('update_times',1),warmup_step=strategy.get('warmup_step',0))
    if plan.get('tokenizer'):train['tokenizer_name_or_path']=plan['tokenizer']
    if plan.get('model_revision'):train['model_revision']=plan['model_revision']
    info={};roles={'train':[],'validation':[],'reference':[]}
    for i,b in enumerate(plan['data']):
        key='dataset_'+str(i);roles[b['role']].append(key)
        info[key]={'file_name':key+'.jsonl','columns':b.get('columns',{})}
        if b['kind']=='huggingface':info[key]={'hf_hub_url':b['ref'],'subset':b.get('subset') or None,'split':b.get('split','train'),'columns':b.get('columns',{})}
    train['dataset']=','.join(roles['train'])
    if roles['validation']:train['eval_dataset']=','.join(roles['validation'])
    if roles['reference']:
        if family=='mixture' and component=='dynamic_moe':train['mixer_eval_dataset']=','.join(roles['reference'])
        else:
            if roles['validation'] and roles['validation']!=roles['reference']:errors.append('当前组件通过 eval_dataset 读取参考集；请使用独立评测记录检验泛化，不混合不同角色')
            train['eval_dataset']=','.join(roles['reference']);warnings.append('策略参考集进入 eval_dataset；其 loss 不是独立测试证据')
    checks.update(compatibility='failed' if errors else 'passed',warnings=sorted(set(warnings)),parameter_semantics='partial' if any('语义' in w for w in warnings) else 'checked')
    return {'checks':checks,'train':train,'components':components,'dataset_info':info,'yaml':{name:(json.dumps(value,ensure_ascii=False,indent=2) if name.endswith('.json') else yaml.safe_dump(value,allow_unicode=True,sort_keys=False)) for name,value in [('train.yaml',train),('components.yaml',components),('dataset_info.json',info)]}}
