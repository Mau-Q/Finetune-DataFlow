"""Task-scoped actual DataFlex CLI runner; observers do not change model inputs/loss/RNG."""
import argparse, collections, functools, hashlib, json, math, os, subprocess, sys, time, types
from pathlib import Path
import torch
import yaml
ROOT=Path('/runs/strategy-20261023')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def tensor_hash(ids):return hashlib.sha256(json.dumps(ids).encode()).hexdigest()
def emit(path,record):
 with path.open('a') as f:f.write(json.dumps(record,allow_nan=False)+'\n')
def scalar(x):return float(x.detach().float().cpu())
def install(cls,folder):
 from transformers import TrainerCallback
 records=json.loads((ROOT/'data/token-map.json').read_text());mapping={r['token_sha256']:r for r in records};assert len(mapping)==len(records)
 current={}; counters=collections.Counter(); refs={}; started=time.monotonic()
 def log(kind,**kwargs):emit(folder/(kind+'.jsonl'),kwargs)
 def identities(inputs):
  ids=inputs['input_ids'].detach().cpu(); labels=inputs['labels'].detach().cpu(); mask=inputs['attention_mask'].detach().cpu()
  result=[]
  for i in range(len(ids)):
   tokens=ids[i][mask[i].bool()].tolist(); meta=mapping.get(tensor_hash(tokens))
   if meta is None:raise RuntimeError('Actual consumed token sequence is outside frozen identities')
   valid=(labels[i]!=-100)&mask[i].bool()
   assert valid.sum()>0 and all(v==-100 for v in labels[i][~mask[i].bool()].tolist())
   n=int(valid.sum());assert n==meta['supervised_tokens'],(n,meta)
   assert valid[mask[i].bool()].tolist()==[False]*(len(tokens)-n)+[True]*n, 'Prompt/answer supervision boundary changed'
   assert (labels[i][valid]==ids[i][valid]).all()
   result.append(dict(meta,valid_labels=n,effective_tokens=len(tokens)))
  return result
 class Callback(TrainerCallback):
  def on_train_begin(self,args,state,control,**kw):
   model=kw['model']; params=[(n,p) for n,p in model.named_parameters() if p.requires_grad]
   assert params and all('lora_' in n for n,p in params)
   log('events',event='train_begin',max_steps=state.max_steps,args_max_steps=args.max_steps,gradient_accumulation=args.gradient_accumulation_steps,trainable_tensors=len(params),base_frozen=True,remove_unused_columns=args.remove_unused_columns,train_sampling_strategy=getattr(args,'train_sampling_strategy',None),scheduler_state=kw['lr_scheduler'].state_dict())
   # Read-only gradient hooks on two representative LoRA matrices.
   for part in ['lora_A','lora_B']:
    name,p=next((n,p) for n,p in params if part in n)
    refs[name]=p.detach().float().cpu().clone()
    def hook(g,name=name):
     log('gradient',step=current.get('step'),micro=current.get('micro'),parameter=name,norm=scalar(g.norm()),sum=scalar(g.sum()),finite=bool(torch.isfinite(g).all()))
     return None
    p.register_hook(hook)
  def on_step_end(self,args,state,control,**kw):
   assert state.global_step<=args.max_steps
   log('events',event='optimizer_step',step=state.global_step,lr=kw['lr_scheduler'].get_last_lr(),max_steps=state.max_steps)
  def on_train_end(self,args,state,control,**kw):
   changed={n:scalar((dict(kw['model'].named_parameters())[n].detach().float().cpu()-v).norm()) for n,v in refs.items()}
   log('events',event='train_end',step=state.global_step,representative_parameter_changes=changed)
 orig_init=cls.__init__
 @functools.wraps(orig_init)
 def init(self,*a,**kw):
  orig_init(self,*a,**kw);self.add_callback(Callback());current['trainer']=self
  attributes=['seed','focus','focus_weight','quantiles','replacement','temperature','score_batch_size','score_num_workers','window_size','strategy','delta','r','warmup_steps','alpha','reward_scale','min_exploration_rate','initial_proportions']
  for family in ['selector','mixer','weighter']:
   component=getattr(self,family,None)
   if component is not None:
    params={k:getattr(component,k) for k in attributes if hasattr(component,k)}
    params={k:(v.tolist() if hasattr(v,'tolist') else v) for k,v in params.items()}
    log('events',event='actual_component',family=family,component_class=type(component).__name__,parameters=params)
  log('events',event='actual_schedule',parameters={k:getattr(self.finetuning_args,k,None) for k in ['train_type','train_step','warmup_step','update_step','update_times','static_mix']})
  original_backward=self.accelerator.backward
  def backward(value,**kwargs):
   if current.get('active'):log('backward-input',step=self.state.global_step,micro=current['micro'],loss=scalar(value),kwargs=kwargs)
   return original_backward(value,**kwargs)
  self.accelerator.backward=backward
  if hasattr(self,'weighter'):
   original=self.weighter.get_weighted_loss
   def weighted(w,losses,**kw):
    value=original(losses,**kw)
    if losses.ndim!=1:raise RuntimeError('Scalar fallback is invalid for this acceptance')
    coeff=torch.autograd.grad(value,losses,retain_graph=True)[0].detach()
    assert torch.isfinite(value) and torch.isfinite(coeff).all()
    log('weights',step=self.state.global_step,micro=current['micro'],losses=losses.detach().float().cpu().tolist(),weights=coeff.float().cpu().tolist(),weighted_loss=scalar(value),uniform_loss=scalar(losses.mean()))
    losses.register_hook(lambda g:log('weight-gradient',step=self.state.global_step,micro=current['micro'],coefficients=g.detach().float().cpu().tolist()))
    return value
   self.weighter.get_weighted_loss=types.MethodType(weighted,self.weighter)
  selector=getattr(self,'selector',None)
  if selector is not None:
   original=selector.select
   def select(s,*a,**kw):
    t=time.monotonic();idx=original(*a,**kw)
    log('strategy',event='select',step=kw.get('step_id'),indices=list(map(int,idx)),seconds=time.monotonic()-t)
    return idx
   selector.select=types.MethodType(select,selector)
   if hasattr(selector,'_compute_losses'):
    original_score=selector._compute_losses
    def score(s,positions,model,step_id):
     positions=list(positions);t=time.monotonic();values=original_score(positions,model,step_id)
     log('scores',step=step_id,positions=positions,losses=values,seconds=time.monotonic()-t,score_batch_size=s.score_batch_size)
     return values
    selector._compute_losses=types.MethodType(score,selector)
  mixer=getattr(self,'mixer',None)
  if mixer is not None:
   original_mix=mixer.mix
   def mix(m,*a,**kw):
    prev=dict(m.prev_batch_info) if getattr(m,'prev_batch_info',None) else None
    old=m.domain_weights.tolist() if hasattr(m,'domain_weights') else None
    t=time.monotonic();value=original_mix(*a,**kw)
    log('strategy',event='mix',step=kw.get('step_id'),previous_feedback=prev,previous_weights=old,weights=value.tolist(),estimated_rewards=m.estimated_rewards.tolist() if hasattr(m,'estimated_rewards') else None,seconds=time.monotonic()-t)
    return value
   mixer.mix=types.MethodType(mix,mixer)
 cls.__init__=init
 orig_loss=cls.compute_loss
 @functools.wraps(orig_loss)
 def loss(self,model,inputs,return_outputs=False,num_items_in_batch=None):
  value,outputs=orig_loss(self,model,inputs,return_outputs=True,num_items_in_batch=num_items_in_batch)
  if model.training and current.get('active'):
   log('loss',step=self.state.global_step,micro=current['micro'],compute_loss=scalar(value),num_items_in_batch=int(num_items_in_batch) if num_items_in_batch is not None else None)
  return (value,outputs) if return_outputs else value
 cls.compute_loss=loss
 orig_step=cls.training_step
 @functools.wraps(orig_step)
 def step(self,model,inputs,num_items_in_batch=None):
  counters['micro']+=1;current.update(step=self.state.global_step,micro=counters['micro'],active=True)
  # Identity/mask reads are CPU only and consume no random numbers.
  rng=torch.get_rng_state().clone();crng=torch.cuda.get_rng_state().clone()
  items=identities(inputs)
  assert torch.equal(rng,torch.get_rng_state()) and torch.equal(crng,torch.cuda.get_rng_state())
  for x in items:assert x['split']=='train'
  log('consumption',step=self.state.global_step,micro=counters['micro'],items=items,domain_id=inputs['domain_id'].detach().cpu().tolist() if 'domain_id' in inputs else None)
  t=time.monotonic();value=orig_step(self,model,inputs,num_items_in_batch=num_items_in_batch)
  assert torch.isfinite(value)
  log('backward',step=self.state.global_step,micro=counters['micro'],backward_return_loss=scalar(value),accumulation=getattr(self,'current_gradient_accumulation_steps',self.args.gradient_accumulation_steps),seconds=time.monotonic()-t)
  current['active']=False
  return value
 cls.training_step=step
 return current

def train(config,folder):
 folder.mkdir(parents=True,exist_ok=False)
 torch.cuda.set_per_process_memory_fraction(.42,0);torch.cuda.reset_peak_memory_stats()
 cfg=yaml.safe_load(config.read_text());(folder/'actual-config.yaml').write_text(yaml.safe_dump(cfg,sort_keys=False))
 if cfg['train_type']=='dynamic_select':
  components=yaml.safe_load(Path(cfg['components_cfg_file']).read_text());cache=Path(components['selectors'][cfg['component_name']]['params']['cache_dir'])
  if folder.resolve() not in cache.resolve().parents:raise ValueError('Selector cache must be inside this attempt')
  if cache.exists() and any(cache.iterdir()):raise FileExistsError('Refusing a nonempty selector cache')
 import dataflex,importlib.metadata
 source=Path(dataflex.__file__).parent
 manifest={'source_files':{str(p.relative_to(source)):sha(p) for p in sorted(source.rglob('*')) if p.suffix in ('.py','.yaml')},'observer_sha256':sha(Path(__file__)),'components_sha256':sha(Path(cfg['components_cfg_file'])),'dataset_info_sha256':sha(Path(cfg['dataset_dir'])/'dataset_info.json'),'model_config_sha256':sha(Path(cfg['model_name_or_path'])/'config.json'),'model_revision':cfg['model_revision'],'packages':{m:importlib.metadata.version(m) for m in ['dataflex','torch','transformers','peft','accelerate','bitsandbytes','llamafactory']},'launch_environment':{k:os.environ.get(k) for k in ['HF_HUB_OFFLINE','HF_DATASETS_OFFLINE','TORCHINDUCTOR_COMPILE_THREADS','PYTORCH_CUDA_ALLOC_CONF']},'started_unix':time.time()}
 (folder/'manifest.json').write_text(json.dumps(manifest,indent=2))
 from dataflex import cli
 original=cli.patch_trainer
 def patch(kind):
  original(kind)
  import llamafactory.train.sft.workflow as wf
  install(wf.CustomSeq2SeqTrainer,folder)
 cli.patch_trainer=patch
 t=time.monotonic();status='FAIL';error=None
 try:
  sys.argv=['dataflex-cli','train',str(config)];cli.main();status='TRAIN_FINISHED'
 except Exception as e:error=repr(e);raise
 finally:
  output=Path(cfg['output_dir']);adapter=output/'adapter_model.safetensors'
  receipt={'status':status,'error':error,'seconds':time.monotonic()-t,'peak_allocated_gib':torch.cuda.max_memory_allocated()/2**30,'peak_reserved_gib':torch.cuda.max_memory_reserved()/2**30,'allocator_fraction':.42,'gpu_name':torch.cuda.get_device_name(0),'config_sha256':sha(config),'adapter_sha256':sha(adapter) if adapter.exists() else None,'data_manifest_sha256':sha(ROOT/'data-manifest.json')}
  (folder/'resource.json').write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt),flush=True)
 if status=='TRAIN_FINISHED':
  from safetensors import safe_open
  with safe_open(adapter,framework='pt',device='cpu') as f:
   nonzero=0
   for k in f.keys():
    v=f.get_tensor(k);assert torch.isfinite(v).all()
    if 'lora_B' in k and torch.count_nonzero(v):nonzero+=1
  states=list(output.glob('checkpoint-*/trainer_state.json'));states.sort(key=lambda p:int(p.parent.name.split('-')[-1]));s=json.loads(states[-1].read_text());assert s['global_step']==cfg['max_steps'];assert nonzero
  receipt.update(status='TRAIN_VERIFIED',optimizer_steps=s['global_step'],nonzero_lora_b_tensors=nonzero,losses=[r['loss'] for r in s['log_history'] if 'loss' in r])
  assert receipt['losses'] and all(math.isfinite(x) for x in receipt['losses'])
  (folder/'resource.json').write_text(json.dumps(receipt,indent=2))
  (folder.parent/'successful-attempt.json').write_text(json.dumps({'attempt':folder.name,'observation_dir':str(folder),'output_dir':str(output)}))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('config',type=Path);p.add_argument('folder',type=Path);a=p.parse_args();train(a.config,a.folder)
