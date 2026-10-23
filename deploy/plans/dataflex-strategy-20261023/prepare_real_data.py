"""Freeze English SciRIFF subset using the actual installed LF/Qwen template, offline."""
import collections, hashlib, json, random, re
from pathlib import Path
import pyarrow.parquet as pq
from transformers import AutoTokenizer
from llamafactory.data import get_template_and_fix_tokenizer
from llamafactory.hparams import DataArguments
ROOT=Path('/runs/strategy-20261023')
TASKS=['scicite_classification','genia_ner','bioasq_factoid_qa','scitldr_aic']
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def digest(s):return hashlib.sha256(s.encode()).hexdigest()
def main():
 raw=ROOT/'raw'; out=ROOT/'data'
 if out.exists():
  assert sorted(p.name for p in out.iterdir()) == ['dataset_info.json'], 'Never overwrite frozen data'
  (ROOT/'dataset_info.placeholder.json').write_bytes((out/'dataset_info.json').read_bytes())
 else:out.mkdir()
 download=json.loads((raw/'download-manifest.json').read_text())
 for f in download['files']:assert sha(raw/Path(f['path']).name)==f['sha256']
 tokenizer=AutoTokenizer.from_pretrained('/models/Qwen3.5-9B',local_files_only=True)
 template=get_template_and_fix_tokenizer(tokenizer,DataArguments(template='qwen3_5_nothink',enable_thinking=False))
 pools={s:{t:[] for t in TASKS} for s in ['train','validation','test']}; denominators={}; rejected=collections.Counter()
 for split in pools:
  rows=pq.read_table(raw/f'{split}-00000-of-00001.parquet').to_pylist()
  counts=collections.Counter(r['_instance_id'].split(':')[0] for r in rows); denominators[split]={t:counts[t] for t in TASKS}
  for row in rows:
   task=row['_instance_id'].split(':')[0]
   if task not in TASKS:continue
   prompt,response=template.encode_oneturn(tokenizer,[{'role':'user','content':row['input']},{'role':'assistant','content':row['output']}])
   if len(prompt)+len(response)>1024:rejected[f'{split}/{task}/length']+=1;continue
   if not response or not row['output'].strip():rejected[f'{split}/{task}/empty']+=1;continue
   # Public export has no paper/document IDs. Extract the evidence segment when
   # possible; conservatively also group full normalized input. No invented IDs.
   content=row['input']
   patterns=[r'(?:Abstract|ABSTRACT|Context|CONTEXT|Passage|PASSAGE|Text|TEXT):\s*(.*)',r'\n\n(.*)']
   evidence=content
   for pat in patterns:
    m=re.search(pat,content,re.S)
    if m:evidence=m.group(1);break
   row.update(task=task,official_split=split,total_tokens=len(prompt)+len(response),supervised_tokens=len(response),
     input_sha256=digest(content),content_group_sha256=digest(' '.join(evidence.split())),token_sha256=digest(json.dumps(prompt+response)))
   pools[split][task].append(row)
 print(json.dumps({'available':{s:{t:len(v) for t,v in p.items()} for s,p in pools.items()},'denominators':denominators}),flush=True)
 # Select test first, then validation then training, preventing exact input or
 # extracted-content overlap across all chosen records. Same-task duplicates drop.
 selected={s:[] for s in pools}; seen=set(); quotas={'train':64,'validation':8,'test':16}
 for split in ['test','validation','train']:
  for task in TASKS:
   candidates=sorted(pools[split][task],key=lambda r:digest('42/'+r['_instance_id']))
   chosen=[]
   for r in candidates:
    keys={r['input_sha256'],r['content_group_sha256']}
    if keys&seen:rejected[f'{split}/{task}/duplicate']+=1;continue
    seen.update(keys);chosen.append(r)
    if len(chosen)==quotas[split]:break
   assert len(chosen)==quotas[split],(split,task,len(chosen),quotas[split])
   selected[split].extend(chosen)
 info={}; sidecars=[]; token_map=[]
 for split,rows in selected.items():
  files={t:[r for r in rows if r['task']==t] for t in TASKS} if split=='train' else {split:rows}
  for name,rs in files.items():
   p=out/f'{name}.jsonl';p.write_text(''.join(json.dumps({'instruction':r['input'],'input':'','output':r['output']},ensure_ascii=False)+'\n' for r in rs))
   info[name]={'file_name':p.name,'columns':{'prompt':'instruction','query':'input','response':'output'}}
  for r in rows:
   sidecars.append({k:v for k,v in r.items() if k not in ['input','output','metadata']})
   token_map.append({'sample_id':r['_instance_id'],'task':r['task'],'domain_id':TASKS.index(r['task']),'split':split,'token_sha256':r['token_sha256'],'total_tokens':r['total_tokens'],'supervised_tokens':r['supervised_tokens']})
 (out/'dataset_info.json').write_text(json.dumps(info,indent=2))
 (out/'metadata.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in sidecars))
 (out/'token-map.json').write_text(json.dumps(token_map))
 # 32 gate records drawn ONLY from training, including each task's eight longest.
 gates=[]
 for t in TASKS:gates+=sorted([r for r in selected['train'] if r['task']==t],key=lambda r:r['total_tokens'],reverse=True)[:8]
 # Make the first consumption near cutoff, with realistic non-classification labels.
 gates.sort(key=lambda r:r['total_tokens'],reverse=True)
 (out/'gate.jsonl').write_text(''.join(json.dumps({'instruction':r['input'],'input':'','output':r['output']})+'\n' for r in gates))
 info['gate']={'file_name':'gate.jsonl','columns':{'prompt':'instruction','query':'input','response':'output'}}
 (out/'dataset_info.json').write_text(json.dumps(info,indent=2))
 manifest={'task_substitution':{'original':'covid_deepset_qa','replacement':'bioasq_factoid_qa','reason':'1024-token intact filtering leaves original 1/1/2 rows; qasper_extractive_qa has zero fitting rows. Replacement preserves short-answer QA and EM/token-F1 scoring but is labeled qa.abstractive by SciRIFF, not extractive.'},'status':'FROZEN','download':download,'tasks':TASKS,'counts':{s:len(r) for s,r in selected.items()},'denominators':denominators,'rejected':dict(rejected),
 'available_after_length_filter':{s:{t:len(v) for t,v in p.items()} for s,p in pools.items()},
 'lengths':{s:{'min':min(r['total_tokens'] for r in rs),'max':max(r['total_tokens'] for r in rs),'supervised_min':min(r['supervised_tokens'] for r in rs),'supervised_max':max(r['supervised_tokens'] for r in rs)} for s,rs in selected.items()},
 'gate_ids':[r['_instance_id'] for r in gates], 'gate_lengths':[r['total_tokens'] for r in gates],
 'template':'qwen3_5_nothink','enable_thinking':False,'cutoff_len':1024,'no_truncation':True,
 'grouping_limit':'Official export only contains instance IDs, no original document IDs; exact normalized evidence/input groups deduplicated. Same-paper different-context overlap cannot be ruled out.',
 'licenses':{'SciRIFF':'ODC-By','genia_ner':'CC BY (card)','bioasq_factoid_qa':'CC BY (SciRIFF task-provenance card)','scitldr_aic':'Apache 2.0 (card)','scicite_classification':'Apache 2.0; https://github.com/allenai/scicite/blob/master/LICENSE (checked 2026-10-23)'},
 'files':{p.name:sha(p) for p in sorted(out.iterdir()) if p.is_file()}}
 (ROOT/'data-manifest.json').write_text(json.dumps(manifest,indent=2));print(json.dumps(manifest),flush=True)
if __name__=='__main__':main()
