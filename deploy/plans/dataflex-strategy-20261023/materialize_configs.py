"""Materialize isolated CLI test configs; never run training or fetch data.

The four task files and validation.jsonl must be prepared separately. The
readiness report remains false until every bound dataset is present.
"""
import argparse
import json
from pathlib import Path

import yaml


def materialize(destination: Path, runtime_root='/runs/strategy-20261023'):
    matrix = json.loads((Path(__file__).parent/'test-matrix.json').read_text())
    root = Path(runtime_root)
    if not root.is_absolute() or '..' in root.parts:
        raise ValueError('runtime_root must be an explicit absolute container path')
    if destination.exists():
        raise FileExistsError(f'Refusing to replace existing configurations: {destination}')
    destination.mkdir(parents=True)
    sources = matrix['data']['tasks_proposed']
    info = {name: {'file_name': name+'.jsonl',
                   'columns': {'prompt': 'instruction', 'query': 'input', 'response': 'output'}}
            for name in sources+['validation']}
    (destination/'dataset_info.json').write_text(json.dumps(info, indent=2)+'\n')
    configs = []
    for run in matrix['core_runs']:
        run_root = root/run['id']
        config = dict(
            model_name_or_path='/models/Qwen3.5-9B',
            model_revision=matrix['model']['revision'],
            stage='sft', do_train=True, do_eval=True,
            finetuning_type='lora', template='qwen3_5_nothink', enable_thinking=False,
            quantization_method='bnb', quantization_bit=4, quantization_type='nf4',
            double_quantization=True, bf16=True, fp16=False, flash_attn='sdpa',
            gradient_checkpointing=True, lora_rank=16, lora_alpha=32, lora_dropout=.05,
            lora_target='all', freeze_vision_tower=True,
            freeze_multi_modal_projector=True, freeze_language_model=False,
            dataset_dir=str(root/'data'), dataset=','.join(sources), eval_dataset='validation',
            val_size=0, packing=False, train_on_prompt=False,
            cutoff_len=matrix['data']['max_full_training_sequence_tokens'],
            per_device_train_batch_size=run['per_device_train_batch_size'],
            per_device_eval_batch_size=1,
            gradient_accumulation_steps=run['gradient_accumulation_steps'],
            learning_rate=2e-5, optim='adamw_torch', lr_scheduler_type='constant',
            warmup_steps=0, max_grad_norm=1., max_steps=24,
            eval_strategy='steps', eval_steps=12, logging_steps=1,
            save_steps=12, save_total_limit=2, seed=42, data_seed=42,
            dataloader_num_workers=0, report_to='none',
            output_dir=str(run_root/'output'), overwrite_output_dir=False,
            train_type=run['train_type'], components_cfg_file=str(run_root/'components.yaml'),
        )
        components = {k: {} for k in ['selectors','mixers','weighters','reorders','pipelines']}
        family = {'dynamic_select':'selectors','dynamic_mix':'mixers','dynamic_weight':'weighters'}.get(run['train_type'])
        if family:
            name = run['component_name']; config['component_name'] = name
            params = dict(run['component_overrides'])
            if family == 'selectors':params['cache_dir'] = str(run_root/'strategy-cache')
            if family == 'mixers' and name == 'static':params['proportions'] = run['init_mixture_proportions']
            components[family][name] = {'name': name, 'params': params}
        for key in ['train_step','warmup_step','update_step','update_times','static_mix',
                    'mixture_sample_rule','init_mixture_proportions']:
            if key in run:config[key] = run[key]
        folder = destination/run['id']; folder.mkdir()
        (folder/'train.yaml').write_text(yaml.safe_dump(config, sort_keys=False))
        (folder/'components.yaml').write_text(yaml.safe_dump(components, sort_keys=False))
        configs.append({'run_id':run['id'], 'path':str(folder/'train.yaml'), 'ready_for_training':False})
    report = {'status':'CONFIGS_MATERIALIZED_DATA_NOT_PREPARED', 'training_started':False,
              'runtime_root':str(root), 'data_root':str(root/'data'),
              'model_root':'/models/Qwen3.5-9B', 'runs':configs,
              'required_launch_environment':{
                  'HF_HUB_OFFLINE':'1', 'HF_DATASETS_OFFLINE':'1',
                  'TORCHINDUCTOR_COMPILE_THREADS':'1',
                  'PYTORCH_CUDA_ALLOC_CONF':'expandable_segments:True'},
              'required_before_launch':['Prepare and hash the frozen real data; install dataset_info.json in data_root.',
                                        'Recheck GPU UUID, free memory and effective allocator cap.',
                                        'Verify microbatch1 and microbatch2 capacity separately.',
                                        'Implement and verify consumption/weight observation hooks.',
                                        'Never launch the old /work/smoke.py with the new configs.']}
    (destination/'readiness.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--runtime-root', default='/runs/strategy-20261023')
    args=parser.parse_args()
    print(json.dumps(materialize(args.output,args.runtime_root)))
