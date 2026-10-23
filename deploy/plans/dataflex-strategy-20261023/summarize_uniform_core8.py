"""Verify the common numerical cohort before publishing its compact comparison."""
import argparse
import json
from pathlib import Path
import yaml
from summarize_results import summarize,sha,read_rows
from prepare_uniform_core8 import PROTOCOL,DATA_SHA

COMMON_KEYS = ['model_name_or_path','model_revision','stage','finetuning_type','template','enable_thinking',
    'quantization_method','quantization_bit','quantization_type','double_quantization','bf16','fp16','flash_attn',
    'gradient_checkpointing','lora_rank','lora_alpha','lora_dropout','lora_target','freeze_vision_tower',
    'freeze_multi_modal_projector','freeze_language_model','dataset_dir','dataset','eval_dataset','val_size',
    'packing','train_on_prompt','cutoff_len','per_device_eval_batch_size','learning_rate','optim',
    'lr_scheduler_type','warmup_steps','max_grad_norm','max_steps','eval_strategy','eval_steps','logging_steps',
    'save_steps','save_total_limit','seed','data_seed','dataloader_num_workers','report_to','full_determinism','save_only_model']


def read(path):return json.loads(path.read_text())


def validate_protocol(receipt):
    assert receipt['deterministic_execution_requested']==PROTOCOL
    assert receipt['deterministic_algorithms'] and receipt['cudnn_deterministic']
    assert not receipt['cudnn_benchmark'] and not receipt['full_determinism_requested']
    assert receipt['cublas_workspace_config']==':4096:8' and receipt['cuda_launch_blocking'] is None
    assert receipt['sdp_backends']=={'flash':False,'math':True,'mem_efficient':False,'cudnn':False}


def collect(root):
    plan=read(root/'cohort-plan.json')
    assert plan['protocol']==PROTOCOL and sha(root/'data-manifest.json')==DATA_SHA
    resolved=Path(plan['reused_pair_root'])
    assert sha(resolved/'resolution-verdict.json')==plan['reused_pair_verdict_sha256']
    assert sha(resolved/'resolution-summary.json')==plan['reused_pair_summary_sha256']
    pair=read(resolved/'resolution-verdict.json')
    assert pair['status']=='PAIR_GRADIENT_MISMATCH_RESOLVED'
    result=summarize(root)
    assert not result['missing_or_failed'] and not result['inconclusive']
    expected_model=read(resolved/'G06/attempt1/initial-model-hashes.json')
    assert len(expected_model)==3049
    configs={};identities={};common=None;batch={};backend_runtime={}
    for i in range(8):
        name='G%02d'%i
        folder=root/name/'attempt1'
        cfg=yaml.safe_load((folder/'actual-config.yaml').read_text());configs[name]=cfg
        identity=read(folder/'manifest.json');identities[name]=identity
        assert identity['components_sha256']==sha(Path(cfg['components_cfg_file']))
        assert read(folder/'resource.json')['config_sha256']==sha(folder/'actual-config.yaml')
        assert identity['observer_sha256']==sha(Path(__file__).with_name('observed_run.py'))
        assert read(folder/'initial-model-hashes.json')==expected_model
        control=read(folder/'paired-control-receipt.json');validate_protocol(control)
        assert control['initial_adapter_tensor_sha256']==plan['initial_adapter_tensor_sha256']
        assert control['micro_rng_seed_base']==420000 and control['lora_dropout']==.05
        settings={key:cfg.get(key) for key in COMMON_KEYS}
        if common is None:common=settings
        else:assert settings==common,('Unexpected shared configuration difference',name,{k:(common[k],v) for k,v in settings.items() if common[k]!=v})
        batch[name]={'microbatch':cfg['per_device_train_batch_size'],'accumulation':cfg['gradient_accumulation_steps']}
        assert batch[name]['microbatch']*batch[name]['accumulation']==4
        runtime=read_rows(folder/'diagnostic-runtime.jsonl')[0]
        assert runtime['script_sha256']==sha(Path(__file__).with_name('diagnose_pair_runtime.py'))
        assert runtime['deterministic'] and runtime['sdp_backends']==control['sdp_backends']
        backend_runtime[name]={k:runtime[k] for k in ['deterministic','sdp_backends','allow_tf32_matmul','allow_tf32_cudnn']}
        assert len(identity['source_files'])==75
    assert all(value==backend_runtime['G06'] for value in backend_runtime.values())
    first=identities['G00']
    assert all(v['source_files']==first['source_files'] and v['packages']==first['packages'] and v['model_config_sha256']==first['model_config_sha256'] and v['dataset_info_sha256']==first['dataset_info_sha256'] for v in identities.values())
    for name,ev in result['evaluations'].items():
        protocol=ev['execution_protocol']
        assert protocol['deterministic_execution']==PROTOCOL and protocol['deterministic_algorithms']
        assert not protocol['full_determinism'] and protocol['cublas_workspace_config']==':4096:8'
        assert ev['model_config_sha256']==first['model_config_sha256']
        assert ev['evaluation_script_sha256']==sha(Path(__file__).with_name('evaluate_frozen.py'))
        if name not in ['G06','G07']:
            assert protocol['wrapper_sha256']==sha(Path(__file__).with_name('evaluate_uniform_core8.py'))
            assert protocol['observer_sha256']==first['observer_sha256']
            assert protocol['sdp_backends']=={'flash':False,'math':True,'mem_efficient':False,'cudnn':False}
        else:
            assert protocol['wrapper_sha256']==sha(Path(__file__).with_name('evaluate_resolved_pair.py'))
        if name!='BASE':
            assert ev['adapter_sha256']==result['core_runs'][name]['adapter_sha256']
    # Do not mistake identical numerical switches for observed bitwise repeatability.
    import torch
    from safetensors.torch import load_file
    left,right=[root/n/'attempt1' for n in ['G01','G02']]
    consumed=[read_rows(p/'consumption.jsonl')[:16] for p in [left,right]]
    assert consumed[0]==consumed[1] and len(consumed[0])==16
    assert all(r['step']<4 for r in consumed[0])
    assert read_rows(left/'paired-rng.jsonl')[:16]==read_rows(right/'paired-rng.jsonl')[:16]
    raw=[]
    for micro in range(1,9):
        for part in ['A','B']:
            a,b=[load_file(str(p/('gradient-%02d-%s.safetensors'%(micro,part))))['gradient'].float() for p in [left,right]]
            raw.append({'micro':micro,'part':part,'torch_equal':torch.equal(a,b),
                        'relative_l2_difference':float((a-b).norm()/a.norm().clamp_min(1e-6)),
                        'maximum_absolute_difference':float((a-b).abs().max())})
    grad_maps=[{(r['micro'],r['parameter']):r for r in read_rows(p/'gradient.jsonl') if r['micro']<=16} for p in [left,right]]
    assert set(grad_maps[0])==set(grad_maps[1]) and len(grad_maps[0])==32
    norm_differences=[abs(v['norm']-grad_maps[1][k]['norm'])/max(abs(v['norm']),1e-4) for k,v in grad_maps[0].items()]
    outside=sum(abs(v['norm']-grad_maps[1][k]['norm'])>1e-4+.02*abs(v['norm']) for k,v in grad_maps[0].items())
    residual={'status':'PRESELECTION_NUMERICAL_ATTRIBUTION_INCONCLUSIVE','runs':['G01','G02'],
        'first_16_consumption_records_equal':True,'first_16_micro_rng_receipts_equal':True,
        'initial_parameter_hashes_equal':3049,'representative_raw_gradient_comparisons':raw,
        'warmup_norm_pairs':32,'warmup_norm_pairs_outside_original_tolerance':outside,
        'warmup_max_norm_relative_difference':max(norm_differences),
        'original_tolerance':{'atol':1e-4,'rtol':.02},
        'scope':'Same recorded microbatch1 preselection token identities/supervision boundaries, initial parameters and protocol still differ numerically; unrecorded input/runtime state has not been fully excluded. This is not the already-verified microbatch2 G06/G07 pair. Individual cause remains unisolated; scores are descriptive, not strict strategy-effect attribution.'}
    assert outside>0
    result['inconclusive'].append(residual)
    result.update(status='UNIFORM_PROTOCOL_CORE8_COMPLETE_WITH_REPRODUCIBILITY_LIMITATION',
        preselection_numerical_diagnostic=residual,
        protocol=PROTOCOL,common_training_settings=common,batch_settings=batch,backend_runtime_settings=backend_runtime,
        initial_parameter_quantization_buffer_hashes_equal=3049,
        initial_model_hash_file_sha256={'G%02d'%i:sha(root/('G%02d'%i)/'attempt1/initial-model-hashes.json') for i in range(8)},
        common_initial_adapter_tensor_sha256=plan['initial_adapter_tensor_sha256'],
        new_optimizer_updates=144,new_predictions=448,reused_optimizer_updates=48,reused_predictions=128,
        new_training_runs=plan['new_training_runs'],new_evaluations=plan['new_evaluations'],
        reused_runs=plan['reused_runs'],reused_pair_verdict_sha256=plan['reused_pair_verdict_sha256'],
        batch_scope=plan['batch_scope'],
        comparison_boundary='Common numerical backend, shared initial adapter, frozen data, 24 updates, effective batch4. Microbatch/accumulation differ by strategy family. Residual microbatch1 preselection numerical differences observed. Single seed and 16 test rows per task; no strict strategy-effect attribution or statistical algorithm ranking.',
        source_script_sha256={p.name:sha(p) for p in Path(__file__).parent.glob('*.py')},
        script_sha256=sha(Path(__file__)))
    # Keep the same two preselected SciTLDR examples as the original campaign.
    # Extraction is not semantic/factual acceptance of the generated summaries.
    metadata=[r for r in read_rows(root/'data/metadata.jsonl') if r['official_split']=='test']
    test_rows=read_rows(root/'data/test.jsonl')
    examples=[]
    for meta,sample in zip(metadata,test_rows):
        if meta['task']!='scitldr_aic' or len(examples)>=2:continue
        predictions={}
        for name in ['BASE']+['G%02d'%i for i in range(8)]:
            prediction=next(r for r in read_rows(root/'evaluation'/name/'predictions.jsonl') if r['sample_id']==meta['_instance_id'])
            predictions[name]=prediction['prediction']
        examples.append({'sample_id':meta['_instance_id'],'instruction':sample['instruction'],
                         'reference':sample['output'],'predictions':predictions})
    assert [r['sample_id'] for r in examples]==['scitldr_aic:test:76','scitldr_aic:test:481']
    (root/'manual-review-examples.json').write_text(json.dumps(examples,ensure_ascii=False,indent=2)+'\n')
    result['manual_examples']={'status':'EXTRACTED_NOT_FACT_REVIEWED','ids':[r['sample_id'] for r in examples],
                               'model_outputs':18,'sha256':sha(root/'manual-review-examples.json')}
    (root/'uniform-results-summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'status':result['status'],'new_updates':144,'new_predictions':448,'cohort_predictions':576}),flush=True)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True)
    collect(parser.parse_args().root)
