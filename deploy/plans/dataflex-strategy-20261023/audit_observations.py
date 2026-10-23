"""Mechanically audit actual observations; unobserved acceptance stays explicit."""
import collections,hashlib,json,math
from pathlib import Path
import numpy as np
import torch
import yaml
ROOT=Path('/runs/strategy-20261023')
def rows(p):return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []
def expected_delta_indices(baseline, current, step, iteration, total_updates=4):
 # Independent reconstruction from recorded scores; no model calls or source
 # selector invocation. Match the documented floating-point sampling contract.
 delta=torch.tensor(baseline,dtype=torch.float32)-torch.tensor(current,dtype=torch.float32)
 order=torch.argsort(delta,descending=True);n=len(delta)
 fraction=(iteration-1)/(total_updates-1)
 left=1/(1+math.exp(-10*(fraction-.5)))*(n-.2*n)
 start,end=int(left),int(left+.2*n)
 negative=(delta[order]<0).nonzero()
 if len(negative):end=min(end,int(negative[0]))
 probability=torch.full((n,),.025);probability[order[start:end]]=1.;probability/=probability.sum()
 gen=torch.Generator().manual_seed(42+step)
 return torch.multinomial(probability,20,replacement=False,generator=gen).tolist(),[start,end]

def main(name):
 pointer=ROOT/name/'successful-attempt.json';folder=Path(json.loads(pointer.read_text())['observation_dir']) if pointer.exists() else ROOT/name/'attempt1';cfg=yaml.safe_load((folder/'actual-config.yaml').read_text());receipt=json.loads((folder/'resource.json').read_text());cons=rows(folder/'consumption.jsonl');events=rows(folder/'events.jsonl');back=rows(folder/'backward-input.jsonl');grads=rows(folder/'gradient.jsonl');strategy=rows(folder/'strategy.jsonl')
 assert receipt['status']=='TRAIN_VERIFIED'
 expected=cfg['max_steps'];effective=cfg['per_device_train_batch_size']*cfg['gradient_accumulation_steps']
 assert [e['step'] for e in events if e['event']=='optimizer_step']==list(range(1,expected+1))
 assert len(cons)==expected*cfg['gradient_accumulation_steps']
 assert len(back)==len(cons) and len(grads)==2*len(cons)
 flat=[x for c in cons for x in c['items']];assert len(flat)==expected*effective
 assert all(x['split']=='train' and 0<x['valid_labels']==x['supervised_tokens'] and x['effective_tokens']<=1024 for x in flat)
 assert all(g['finite'] for g in grads)
 end=events[-1];assert any(v>0 for v in end['representative_parameter_changes'].values())
 counts=collections.Counter(x['task'] for x in flat);by_stage={}
 if name in ['G01','G02','G03']:
  assert [s['step'] for s in strategy]==[4,9,14,19]
  allmeta=[r for r in json.loads((ROOT/'data/token-map.json').read_text()) if r['split']=='train']
  # Current frozen ordering is task-major, matching explicit dataset config.
  for s in strategy:
   assert len(s['indices'])==20 and len(set(s['indices']))==20
   stage=[x['sample_id'] for c in cons if s['step']<=c['step']<s['step']+5 for x in c['items']]
   planned=[allmeta[i]['sample_id'] for i in s['indices']]
   assert collections.Counter(stage)==collections.Counter(planned),(s['step'],'planned!=consumed')
   by_stage[s['step']]={'n':len(stage),'sources':dict(collections.Counter(x['task'] for c in cons if s['step']<=c['step']<s['step']+5 for x in c['items']))}
   if name=='G01':
    gen=torch.Generator().manual_seed(42+s['step']);assert s['indices']==torch.randperm(256,generator=gen)[:20].tolist()
  scores=rows(folder/'scores.jsonl')
  if name in ['G02','G03']:assert [s['step'] for s in scores]==[4,9,14,19] and all(s['positions']==list(range(256)) and len(s['losses'])==256 and all(math.isfinite(v) for v in s['losses']) for s in scores)
  if name=='G02':
   for s,v in zip(strategy,scores):
    loss=torch.tensor(v['losses']);q1,q2=torch.quantile(loss,torch.tensor([.33,.66]));weights=torch.ones_like(loss);weights[loss>q2]*=5;probs=(weights+1e-12)/(weights+1e-12).sum();gen=torch.Generator().manual_seed(42+s['step']);assert s['indices']==torch.multinomial(probs,20,replacement=False,generator=gen).tolist()
  if name=='G03':
   initial=torch.Generator().manual_seed(42);assert strategy[0]['indices']==torch.randperm(256,generator=initial)[:20].tolist()
   for iteration,(event,score) in enumerate(zip(strategy[1:],scores[1:]),start=2):
    expected_indices,window=expected_delta_indices(scores[0]['losses'],score['losses'],event['step'],iteration)
    assert event['indices']==expected_indices
    by_stage[event['step']]['delta_window']=window
 if name=='G04':assert not strategy and sorted(counts.values())==[24]*4
 if name in ['G04','G05']:
  assert all(c['domain_id'] is not None and c['domain_id']==[x['domain_id'] for x in c['items']] for c in cons)
 if name=='G05':
  assert [s['step'] for s in strategy]==[4,9,14,19]
  estimates=np.zeros(4);previous_eps=.25
  for s in strategy:
   p=np.array(s['previous_weights']);fb=s['previous_feedback'];d=fb['domain_id'];estimates[d]=.9*estimates[d]+.1*(fb['loss']*15/p[d]);assert np.allclose(estimates,s['estimated_rewards'])
   eps=max(.03,min(.25,math.sqrt(math.log(4)/(4*s['step']))));z=np.clip(previous_eps*estimates-max(previous_eps*estimates),-5,0);e=np.exp(z);expected_p=e*(1-4*eps)/e.sum()+eps;expected_p/=expected_p.sum();assert np.allclose(expected_p,s['weights']);previous_eps=eps
   previous=next(c for c in reversed(cons) if c['step']==s['step']-1);assert previous['domain_id']==[d]
   returned=rows(folder/'backward.jsonl');v=next(b for b in returned if b['micro']==previous['micro']);assert abs(v['backward_return_loss']-fb['loss'])<1e-6
   stage=[x for c in cons if s['step']<=c['step']<s['step']+5 for x in c['items']];wanted=[int(20*x) for x in s['weights'][:3]];wanted+=[20-sum(wanted)];actual=[sum(x['domain_id']==i for x in stage) for i in range(4)];assert actual==wanted
   by_stage[s['step']]={'sources':actual,'proportions':s['weights']}
 weights=rows(folder/'weights.jsonl');coeff=rows(folder/'weight-gradient.jsonl')
 if name in ['G06','G07'] or (name.startswith('GATE') and name.endswith('B2')):
  expected_active=[c for c in cons if c['step']>=cfg['warmup_step']]
  assert len(weights)==len(coeff)==len(expected_active)>0
  for w,g,c in zip(weights,coeff,expected_active):
   assert w['micro']==g['micro']==c['micro'];a=np.array(w['weights']);l=np.array(w['losses']);assert np.isfinite(l).all() and abs(a.sum()-1)<.02
   if name=='G06':assert np.allclose(a,[.5,.5],atol=.005)
   else:
    z=2*(l-l.min())/max(l.max()-l.min(),1e-6)-1;r=np.minimum(z+1,1);v=np.exp(r-r.max());v/=v.sum();assert np.allclose(a,v,atol=.015)
   assert np.allclose(np.array(g['coefficients']),a/cfg['gradient_accumulation_steps'],atol=.005)
  if name!='G06':assert any(abs(w['weights'][0]-.5)>.05 for w in weights)
 if name=='G07':
  paired=rows(ROOT/'G06/attempt1/consumption.jsonl');assert [[x['sample_id'] for x in c['items']] for c in paired]==[[x['sample_id'] for x in c['items']] for c in cons]
  # The warmup trajectories share initialization, batches and RNG. At the first
  # weighted batch, recorded actual LoRA gradients demonstrate the effect.
  ctrl=rows(ROOT/'G06/attempt1/gradient.jsonl');start=next(w['micro'] for w in weights)
  ga=[g for g in grads if g['micro']==start];gb=[g for g in ctrl if g['micro']==start];assert any(abs(a['norm']-b['norm'])>1e-7 for a,b in zip(ga,gb))
 summary={'status':'MECHANISM_OBSERVED','name':name,'optimizer_steps':expected,'sample_presentations':len(flat),'distinct_samples':len(set(x['sample_id'] for x in flat)),'source_counts':dict(counts),'effective_tokens':sum(x['effective_tokens'] for x in flat),'supervised_tokens':sum(x['valid_labels'] for x in flat),'length_min':min(x['effective_tokens'] for x in flat),'length_max':max(x['effective_tokens'] for x in flat),'supervised_max':max(x['valid_labels'] for x in flat),'strategy_boundaries':[s['step'] for s in strategy],'stage_consumption':by_stage,'weight_batches':len(weights),'gradient_observations':len(grads),'resource':receipt,'observer_identity_rng_checks':True,'reload_status':'NOT_YET_VERIFIED','source_scope':'Direct DataFlex CLI; no platform SSH acceptance','limitations':['Single run, 24 updates maximum, engineering evidence only','Original document IDs unavailable in released SciRIFF export; different-context paper overlap unresolved']}
 score_rows=rows(folder/'scores.jsonl')
 summary['scoring_seconds']=sum(r['seconds'] for r in score_rows)
 if score_rows:
  lookup=[r for r in json.loads((ROOT/'data/token-map.json').read_text()) if r['split']=='train']
  summary['scoring_effective_tokens']=sum(lookup[i]['total_tokens'] for r in score_rows for i in r['positions'])
 summary['observation_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.glob('*.jsonl')}
 (folder/'audit.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary),flush=True)
if __name__=='__main__':import sys;main(sys.argv[1])
