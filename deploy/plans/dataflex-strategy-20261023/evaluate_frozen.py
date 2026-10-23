"""Greedy 64-case evaluation, isolated process per base/adapter; full records stay on school."""
import argparse,collections,hashlib,json,math,re,string,time
from pathlib import Path
import torch
ROOT=Path('/runs/strategy-20261023')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def normalize(s):
 s=str(s).lower().translate(str.maketrans('','',string.punctuation));return ' '.join(re.sub(r'\b(a|an|the)\b',' ',s).split())
def qa(p,t):
 a,b=normalize(p),normalize(t);x,y=a.split(),b.split();n=sum((collections.Counter(x)&collections.Counter(y)).values())
 return {'em':int(a==b),'token_f1':2*n/(len(x)+len(y)) if x or y else 1.}
def ner(s):
 s=s.strip()
 if s.startswith('```'):
  s=re.sub(r'^```(?:json)?\s*','',s);s=re.sub(r'\s*```$','',s)
 obj=json.loads(s)
 if not isinstance(obj,dict):raise ValueError('Expected dict of entity-type to list of spans')
 entities=set()
 for k,vals in obj.items():
  if not isinstance(vals,list) or not all(isinstance(v,str) for v in vals):raise ValueError('Expected list of strings')
  for v in vals:entities.add((str(k),v))
 return entities

def rouge_l(p,t):
 a,b=re.findall(r'\w+|[^\w\s]',p.lower()),re.findall(r'\w+|[^\w\s]',t.lower());row=[0]*(len(b)+1)
 for x in a:
  new=[0]
  for j,y in enumerate(b):new.append(row[j]+1 if x==y else max(row[j+1],new[-1]))
  row=new
 return 2*row[-1]/(len(a)+len(b)) if a or b else 1.
def metrics(rows):
 out={}
 for task in sorted({r['task'] for r in rows}):
  rs=[r for r in rows if r['task']==task];d={'n':len(rs),'empty':sum(not r['prediction'].strip() for r in rs),'generation_cap_hits':sum(r['cap_hit'] for r in rs)}
  if task=='scicite_classification':
   targets=[r['reference'].strip().lower() for r in rs];preds=[r['prediction'].strip().lower() for r in rs];labs=sorted(set(targets));fs=[]
   for l in labs:
    tp=sum(p==t==l for p,t in zip(preds,targets));fp=sum(p==l and t!=l for p,t in zip(preds,targets));fn=sum(t==l and p!=l for p,t in zip(preds,targets));fs.append(2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.)
   d.update(accuracy=sum(p==t for p,t in zip(preds,targets))/len(rs),macro_f1=sum(fs)/len(fs),labels=labs,invalid_labels=sum(p not in labs for p in preds))
  elif task=='genia_ner':
   tp=fp=fn=parsed=0;parsed_tp=parsed_fp=parsed_fn=0;sample_f1=[];by_type=collections.defaultdict(lambda:[0,0,0])
   for r in rs:
    truth=ner(r['reference'])
    valid=True
    try:pred=ner(r['prediction']);parsed+=1
    except (ValueError,TypeError):pred=set();valid=False
    a,b,c=len(pred&truth),len(pred-truth),len(truth-pred)
    sample_f1.append((2*a/(2*a+b+c) if 2*a+b+c else 1.) if valid else 0.)
    if valid:parsed_tp+=a;parsed_fp+=b;parsed_fn+=c
    tp+=len(pred&truth);fp+=len(pred-truth);fn+=len(truth-pred)
    for typ in {x[0] for x in truth|pred}:
     t={x for x in truth if x[0]==typ};p={x for x in pred if x[0]==typ};v=by_type[typ];v[0]+=len(t&p);v[1]+=len(p-t);v[2]+=len(t-p)
   d.update(entity_exact_macro_sample_f1=sum(sample_f1)/len(rs),successful_parse_subset_entity_micro_f1=(2*parsed_tp/(2*parsed_tp+parsed_fp+parsed_fn) if 2*parsed_tp+parsed_fp+parsed_fn else 1.) if parsed else None,entity_exact_micro_f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else float(parsed==len(rs)),tp=tp,fp=fp,fn=fn,json_success=parsed/len(rs),per_type={k:{'tp':v[0],'fp':v[1],'fn':v[2],'f1':2*v[0]/(2*v[0]+v[1]+v[2]) if sum(v) else 1.} for k,v in by_type.items()})
  elif task=='bioasq_factoid_qa':
   vals=[qa(r['prediction'],r['reference']) for r in rs];d.update({k:sum(v[k] for v in vals)/len(rs) for k in ['em','token_f1']});d['reference_scope']='Single SciRIFF released answer; no hidden alternatives'
  elif task=='scitldr_aic':d.update(rouge_l_f1=sum(rouge_l(r['prediction'],r['reference']) for r in rs)/len(rs),rouge_tokenizer='lowercase Unicode word/punctuation regex, no stemming; LCS token F1')
  out[task]=d
 return out

def generation_prompt(tokenizer, instruction):
 # LF's generic qwen3_5_nothink encode_oneturn produces a training prompt but
 # does not add Qwen3.5's native generation-only empty-thinking prefill.
 messages=[{'role':'user','content':instruction}]
 text=tokenizer.apply_chat_template(messages,tokenize=False,add_generation_prompt=True,enable_thinking=False)
 if not text.rstrip().endswith('</think>'):
  raise ValueError('Native Qwen no-think generation prefill missing')
 return tokenizer.encode(text,add_special_tokens=False)

def main(name, attempt=None):
 from transformers import AutoModelForImageTextToText,AutoTokenizer,BitsAndBytesConfig
 from peft import PeftModel
 from llamafactory.data import get_template_and_fix_tokenizer
 from llamafactory.hparams import DataArguments
 base_folder=ROOT/'evaluation'/name
 if attempt is not None and not re.fullmatch(r'attempt[1-9][0-9]*',attempt):raise ValueError('Invalid evaluation attempt')
 folder=base_folder/attempt if attempt else base_folder;folder.mkdir(parents=True,exist_ok=False)
 torch.cuda.set_per_process_memory_fraction(.42,0);torch.cuda.reset_peak_memory_stats();torch.manual_seed(42)
 modelpath='/models/Qwen3.5-9B';tokenizer=AutoTokenizer.from_pretrained(modelpath,local_files_only=True)
 template=get_template_and_fix_tokenizer(tokenizer,DataArguments(template='qwen3_5_nothink',enable_thinking=False))
 t=time.monotonic()
 model=AutoModelForImageTextToText.from_pretrained(modelpath,local_files_only=True,dtype=torch.bfloat16,device_map={'':0},attn_implementation='sdpa',quantization_config=BitsAndBytesConfig(load_in_4bit=True,bnb_4bit_quant_type='nf4',bnb_4bit_use_double_quant=True,bnb_4bit_compute_dtype=torch.bfloat16))
 adapter=None
 if name!='BASE':
  pointer=ROOT/name/'successful-attempt.json';adapter=Path(json.loads(pointer.read_text())['output_dir']) if pointer.exists() else ROOT/name/'attempt1/output';assert (adapter/'adapter_model.safetensors').exists()
  model=PeftModel.from_pretrained(model,str(adapter),is_trainable=False)
 model.eval()
 if name=='GATE2-B2':
  from dataflex.utils.loss_utils import per_sample_loss_from_logits
  rr=[json.loads(l) for l in (ROOT/'gate-representative/gate.jsonl').read_text().splitlines()]
  sample_rows=[rr[i] for i in [0,1,2,4]];encoded=[]
  for r in sample_rows:
   p,a=template.encode_oneturn(tokenizer,[{'role':'user','content':r['instruction']},{'role':'assistant','content':r['output']}]);encoded.append((p+a,[-100]*len(p)+a))
  def score_batch(es):
   length=max(len(e[0]) for e in es);ids=torch.tensor([e[0]+[tokenizer.pad_token_id]*(length-len(e[0])) for e in es],device='cuda');labels=torch.tensor([e[1]+[-100]*(length-len(e[1])) for e in es],device='cuda');mask=ids.ne(tokenizer.pad_token_id).long()
   with torch.inference_mode():v=per_sample_loss_from_logits(model(input_ids=ids,attention_mask=mask).logits,labels)
   return v.float().cpu()
  singles=torch.cat([score_batch([e]) for e in encoded]);pairs=torch.cat([score_batch(encoded[i:i+2]) for i in [0,2]]);delta=float((singles-pairs).abs().max());assert torch.allclose(singles,pairs,atol=.03,rtol=.01),(singles,pairs)
  (folder/'score-batch-check.json').write_text(json.dumps({'single':singles.tolist(),'batch2':pairs.tolist(),'max_abs_difference':delta,'atol':.03,'rtol':.01,'valid_labels':[sum(x!=-100 for x in e[1]) for e in encoded],'forward_samples':8,'forward_full_tokens':2*sum(len(e[0]) for e in encoded)}))
 rows=[json.loads(l) for l in (ROOT/'data/test.jsonl').read_text().splitlines()]
 meta=[json.loads(l) for l in (ROOT/'data/metadata.jsonl').read_text().splitlines() if json.loads(l)['official_split']=='test']
 if name.startswith('GATE'):
  rows=[json.loads(l) for l in (ROOT/'data/gate.jsonl').read_text().splitlines()][:2]; gate_ids=json.loads((ROOT/'data-manifest.json').read_text())['gate_ids'];meta=[{'_instance_id':gate_ids[i],'task':gate_ids[i].split(':')[0]} for i in range(2)]
 order=[i for j in range(16) for i in [j,16+j,32+j,48+j]] if len(rows)==64 else list(range(len(rows)))
 predictions=[];gen_started=time.monotonic()
 for count,index in enumerate(order):
  r=rows[index];m=meta[index];prompt=generation_prompt(tokenizer,r['instruction'])
  inputs=torch.tensor([prompt],device='cuda');mask=torch.ones_like(inputs)
  with torch.inference_mode():seq=model.generate(input_ids=inputs,attention_mask=mask,max_new_tokens=256,do_sample=False,pad_token_id=tokenizer.pad_token_id,eos_token_id=tokenizer.eos_token_id)
  new=seq[0,len(prompt):].tolist();pred=tokenizer.decode(new,skip_special_tokens=True);raw=tokenizer.decode(new,skip_special_tokens=False);thought_tag=('<think>' in raw or '</think>' in raw)
  row={'reasoning_tag_emitted':thought_tag,'sample_id':m['_instance_id'],'task':m['task'],'prediction':pred,'reference':r['output'],'prompt_tokens':len(prompt),'generated_tokens':len(new),'cap_hit':len(new)>=256 and new[-1]!=tokenizer.eos_token_id,'last_token':new[-1] if new else None}
  with (folder/'predictions.jsonl').open('a') as f:f.write(json.dumps(row)+'\n')
  predictions.append(row)
  if thought_tag:raise RuntimeError('Model emitted reasoning tags under native no-think prefill; preserved failing prediction')
  print(json.dumps({'model':name,'completed':len(predictions),'total':len(rows),'last_tokens':len(new)}),flush=True)
  if count==7:
   # Parsing failures count in denominator; a total inability to generate is a
   # runtime failure. Do not tune generation using test scores.
   assert all(x['prediction'].strip() for x in predictions),'Empty output in first eight runtime checks; preserve attempt and inspect before full evaluation'
   (folder/'first-eight-check.json').write_text(json.dumps({'nonempty':sum(bool(x['prediction'].strip()) for x in predictions),'cap_hits':sum(x['cap_hit'] for x in predictions),'n':8}))
 receipt={'model':name,'adapter_reloaded':name!='BASE','adapter_sha256':sha(adapter/'adapter_model.safetensors') if adapter else None,'data_manifest_sha256':sha(ROOT/'data-manifest.json'),'n':len(predictions),'total_seconds':time.monotonic()-t,'generation_seconds':time.monotonic()-gen_started,'peak_allocated_gib':torch.cuda.max_memory_allocated()/2**30,'peak_reserved_gib':torch.cuda.max_memory_reserved()/2**30,'prediction_sha256':sha(folder/'predictions.jsonl'),'evaluation_script_sha256':sha(Path(__file__)),'model_config_sha256':sha(Path(modelpath)/'config.json'),'eos_token_id':tokenizer.eos_token_id,'pad_token_id':tokenizer.pad_token_id,'empty_outputs':sum(not r['prediction'].strip() for r in predictions),'reasoning_tag_outputs':sum(r['reasoning_tag_emitted'] for r in predictions),'generation':{'prompt_method':'hf_native_chat_template_enable_thinking_false','do_sample':False,'max_new_tokens':256,'template':'qwen3_5_nothink','enable_thinking':False}}
 if not name.startswith('GATE'):receipt['metrics']=metrics(predictions)
 (folder/'metrics.json').write_text(json.dumps(receipt,indent=2))
 (base_folder/'successful-evaluation.json').write_text(json.dumps({'attempt':attempt or 'initial'}))
 print(json.dumps(receipt),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('name');p.add_argument('--attempt');a=p.parse_args();main(a.name,a.attempt)
