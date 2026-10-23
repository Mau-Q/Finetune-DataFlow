"""CPU-only compact diagnosis accounting; never promote an incomplete pair to pass."""
import argparse
import hashlib
import json
from pathlib import Path
import torch
from safetensors.torch import load_file


def read(path):return json.loads(path.read_text())
def rows(path):return [json.loads(line) for line in path.read_text().splitlines()]
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize(root):
    assert sha(root/'results-summary.json')=='6b9a112484fabe5729b99249600e5a5566a84261ad696a08eda7a6600c030bb6','Historical initial summary changed'
    diagnosis=root/'gradient-diagnosis-20261023'
    cases={}
    for name in ['trace-A','trace-B','strict-A','strict-B','math-A','math-B','native-hash-A','strict-warmup-A','strict-warmup-B','strict-math-warmup-A','strict-math-warmup-B']:
        folder=diagnosis/name/'attempt1'
        resource=read(folder/'resource.json')
        assert resource['status']=='TRAIN_VERIFIED' and resource['optimizer_steps']==(4 if 'warmup-' in name else 1)
        runtime=rows(folder/'diagnostic-runtime.jsonl')[0]
        cases[name]={'optimizer_updates':resource['optimizer_steps'],'resource':resource,'runtime':runtime,
                     'losses':rows(folder/'loss.jsonl'),
                     'initial_model_hashes_count':len(read(folder/'initial-model-hashes.json')) if (folder/'initial-model-hashes.json').exists() else None,
                     'consumption_sha256':sha(folder/'consumption.jsonl')}
    comparisons=[]
    for first,second in [('trace-A','trace-B'),('strict-A','strict-B'),('math-A','math-B'),('strict-warmup-A','strict-warmup-B'),('strict-math-warmup-A','strict-math-warmup-B')]:
        a,b=diagnosis/first/'attempt1',diagnosis/second/'attempt1'
        assert rows(a/'consumption.jsonl')==rows(b/'consumption.jsonl')
        assert read(a/'paired-control-receipt.json')['initial_adapter_tensor_sha256']==read(b/'paired-control-receipt.json')['initial_adapter_tensor_sha256']
        grads=[]
        for micro in [1,2]:
            for part in ['A','B']:
                x,y=[load_file(str(p/('gradient-%02d-%s.safetensors'%(micro,part))))['gradient'].float() for p in [a,b]]
                grads.append({'micro':micro,'part':part,'bitwise_equal':torch.equal(x,y),'norm_first':float(x.norm()),
                              'norm_second':float(y.norm()),'maximum_absolute_difference':float((x-y).abs().max()),
                              'relative_l2_difference':float((x-y).norm()/x.norm().clamp_min(1e-6))})
        def dropout_map(path):
            return {(x['micro'],x['module'],x['phase'],x['grad_enabled']):x for x in rows(path)}
        ma,mb=dropout_map(a/'diagnostic-dropout.jsonl'),dropout_map(b/'diagnostic-dropout.jsonl')
        keys=[k for k in ma if k[0]==1]
        assert set(ma)==set(mb)
        same=all(ma[k]['rng']==mb[k]['rng'] and ma[k].get('input')==mb[k].get('input') and ma[k].get('output')==mb[k].get('output') for k in keys)
        comparisons.append({'runs':[first,second],'first_micro_layer0_dropout_rng_and_prefix_signatures_equal':same,
                            'dropout_scope':'All eight LoRA dropout modules in layer0; prefix up to 65536 elements, not all layers',
                            'gradients':grads})
    hash_cases=['strict-A','strict-B','math-A','math-B','native-hash-A']
    hashes=[read(diagnosis/name/'attempt1/initial-model-hashes.json') for name in hash_cases]
    assert all(value==hashes[0] for value in hashes) and len(hashes[0])==3046
    resolved=root/'gradient-resolution-v2-20261023'
    verdict=read(resolved/'resolution-verdict.json')
    assert verdict['status']=='PAIR_GRADIENT_MISMATCH_RESOLVED'
    evaluations={}
    for name in ['G06','G07']:
        folder=resolved/'evaluation'/name
        receipt=read(folder/'metrics.json');predictions=rows(folder/'predictions.jsonl')
        assert receipt['n']==len(predictions)==64 and sha(folder/'predictions.jsonl')==receipt['prediction_sha256']
        assert receipt['reasoning_tag_outputs']==0 and receipt['adapter_reloaded']
        assert receipt['execution_protocol']['deterministic_algorithms']
        pointer=read(resolved/name/'successful-attempt.json')
        assert sha(Path(pointer['output_dir'])/'adapter_model.safetensors')==receipt['adapter_sha256']
        assert receipt['data_manifest_sha256']==sha(root/'data-manifest.json')
        receipt['generated_tokens']=sum(x['generated_tokens'] for x in predictions)
        receipt['cap_hits']=sum(x['cap_hit'] for x in predictions)
        evaluations[name]=receipt
    resources={name:read(resolved/name/'attempt1/resource.json') for name in ['G06','G07']}
    warmup_folders=[diagnosis/name/'attempt1' for name in ['strict-math-warmup-A','strict-math-warmup-B']]
    for micro in range(1,9):
        for part in ['A','B']:
            assert torch.equal(*[load_file(str(p/('gradient-%02d-%s.safetensors'%(micro,part))))['gradient'] for p in warmup_folders])
    warmup_records=[rows(p/'optimizer-gradients.jsonl') for p in warmup_folders]
    assert len(warmup_records[0])==len(warmup_records[1])==4
    for a,b in zip(*warmup_records):
        assert len(a['tensors'])==len(b['tensors'])==496
        assert all(a['tensors'][key]['sha256']==b['tensors'][key]['sha256'] for key in a['tensors'])
    layer_maps=[{(x['module'],x['grad_enabled']):x for x in rows(p/'diagnostic-layers.jsonl')} for p in warmup_folders]
    assert layer_maps[0]==layer_maps[1]
    for (module,grad),x in layer_maps[0].items():
        mate=layer_maps[0].get((module,True))
        if not grad and mate:
            assert x['input']==mate['input'] and x['output']==mate['output']
    decoder_layers={name for name,_ in layer_maps[0] if name.rsplit('.',1)[-1].isdigit()}
    assert len(decoder_layers)==32
    failed_root=root/'gradient-resolution-20261023'
    failed_resources={name:read(failed_root/name/'attempt1/resource.json') for name in ['G06','G07']}
    failed_gradients=[load_file(str(failed_root/name/'attempt1/gradient-01-B.safetensors'))['gradient'].float() for name in ['G06','G07']]
    assert all(x['optimizer_steps']==24 for x in failed_resources.values()) and not torch.equal(*failed_gradients)
    failed_protocol={'resources':failed_resources,'status':'STRICT_GRADIENT_AUDIT_FAILED_NO_EVALUATIONS',
                     'protocol':'Transformers full_determinism=True; cuBLAS :16:8 and CUDA_LAUNCH_BLOCKING=1',
                     'first_micro_B_relative_l2':float((failed_gradients[0]-failed_gradients[1]).norm()/failed_gradients[0].norm()),
                     'optimizer_updates':48,'generated_predictions':0}
    added_updates=sum(x['optimizer_updates'] for x in cases.values())+48+48
    result={'status':'PAIR_GRADIENT_MISMATCH_RESOLVED_AND_RELOAD_VERIFIED','cases':cases,'comparisons':comparisons,
            'model_parameter_and_quantization_hashes_equal':{'runs':hash_cases,'count':3046},
            'convolution_primitives':{name:read(diagnosis/name/'receipt.json') for name in ['conv-primitive','conv-layout-primitive']},
            'resolution':verdict,'resolved_resources':resources,'resolved_evaluations':evaluations,
            'failed_generic_full_determinism_pair':failed_protocol,'four_step_strict_math_repeat_warmup_exact':True,
            'strict_math_first_micro_full_layer_outputs':{'decoder_layers':len(decoder_layers),'module_phase_records':len(layer_maps[0]),'cross_run_and_checkpoint_recompute_equal':True,'scope':'Full decoder outputs and all leaf submodules of layer0, first microbatch only'},
            'new_optimizer_updates':added_updates,'new_predictions':128,
            'all_campaign_optimizer_updates_including_prior_248':248+added_updates,
            'all_campaign_generated_rows_including_prior_584':584+128,
            'historical_core8_artifacts_unchanged':True,
            'causal_scope':'Seed/RNG identity was insufficient. The explicit torch-math-cublas4096-v2 protocol resolves this current stack; the generic HF full_determinism recipe did not. Individual CUDA kernel has not been uniquely isolated; math-SDPA alone did not resolve it.',
            'script_sha256':sha(Path(__file__))}
    (resolved/'resolution-summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'status':result['status'],'new_updates':result['new_optimizer_updates'],'new_predictions':128}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True)
    summarize(parser.parse_args().root)
