"""A second gate includes all four tasks, near-cutoff inputs and longest answers."""
import hashlib,json,yaml
from pathlib import Path
R=Path('/runs/strategy-20261023');data=R/'data';out=R/'gate-representative';out.mkdir(exist_ok=False)
manifest=json.loads((R/'data-manifest.json').read_text());tasks=manifest['tasks'];meta=[json.loads(l) for l in (data/'metadata.jsonl').read_text().splitlines() if json.loads(l)['official_split']=='train']
pairs={}
for t in tasks:
 rs=[json.loads(l) for l in (data/(t+'.jsonl')).read_text().splitlines()];ms=[m for m in meta if m['task']==t];pairs[t]=list(zip(ms,rs))
chosen=[];seen=set()
def add(x):
 if x[0]['_instance_id'] not in seen:seen.add(x[0]['_instance_id']);chosen.append(x)
# First two are actual near-cutoff QA/TLDR; four tasks and the longest answer
# are within the first eight consumed presentations in both B1 and B2.
for t in [tasks[2],tasks[3],tasks[1],tasks[0]]:add(max(pairs[t],key=lambda x:x[0]['total_tokens']))
for t in [tasks[1],tasks[2],tasks[3],tasks[0]]:add(max(pairs[t],key=lambda x:x[0]['supervised_tokens']))
for t in tasks:
 for x in sorted(pairs[t],key=lambda x:(x[0]['supervised_tokens'],x[0]['total_tokens']),reverse=True):
  if sum(v[0]['task']==t for v in chosen)<8:add(x)
assert len(chosen)==32
(out/'gate.jsonl').write_text(''.join(json.dumps(r)+'\n' for m,r in chosen));(out/'dataset_info.json').write_text(json.dumps({'gate':{'file_name':'gate.jsonl','columns':{'prompt':'instruction','query':'input','response':'output'}}}))
receipt={'n':32,'first_eight':[m for m,r in chosen[:8]],'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir()}}
(out/'manifest.json').write_text(json.dumps(receipt,indent=2))
for b in [1,2]:
 f=R/f'GATE2-B{b}';f.mkdir(exist_ok=False);cfg=yaml.safe_load((R/f'GATE-B{b}/train.yaml').read_text());cfg.update(dataset_dir=str(out),eval_dataset=None,output_dir=str(f/'attempt1/output'));(f/'train.yaml').write_text(yaml.safe_dump(cfg,sort_keys=False))
print(json.dumps(receipt))
