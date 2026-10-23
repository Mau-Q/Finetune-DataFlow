"""Freeze G00-G05 reruns and bind the verified G06/G07 pair; no model calls."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import yaml

PROTOCOL = 'torch-math-cublas4096-v2'
DATA_SHA = 'f2e723257b323c022729a01207b45c036d3c98d61debdc71087a252e58c66b7e'


def read(path): return json.loads(path.read_text())
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(root, source):
    if not root.is_absolute() or '..' in root.parts:
        raise ValueError('Explicit absolute output root required')
    if root.exists():
        raise FileExistsError('Preserve existing results; choose a fresh cohort root')
    assert sha(source/'data-manifest.json') == DATA_SHA
    resolved = source/'gradient-resolution-v2-20261023'
    verdict = read(resolved/'resolution-verdict.json')
    assert verdict['status'] == 'PAIR_GRADIENT_MISMATCH_RESOLVED'
    snapshot = source/'paired-initialization-v2/adapter_init.safetensors'
    assert sha(snapshot) == verdict['protocols']['G06']['snapshot_sha256']
    plans = []
    for i in range(6):
        name = 'G%02d' % i
        old = Path(read(source/name/'successful-attempt.json')['observation_dir'])
        config = yaml.safe_load((old/'actual-config.yaml').read_text())
        components_path = Path(config['components_cfg_file'])
        assert sha(components_path) == read(old/'manifest.json')['components_sha256']
        components = yaml.safe_load(components_path.read_text())
        assert config['max_steps'] == 24
        assert config['per_device_train_batch_size'] == 1 and config['gradient_accumulation_steps'] == 4
        folder = root/name
        config.update(full_determinism=False, output_dir=str(folder/'attempt1/output'),
                      components_cfg_file=str(folder/'components.yaml'))
        if config['train_type'] == 'dynamic_select':
            components['selectors'][config['component_name']]['params']['cache_dir'] = str(folder/'attempt1/strategy-cache')
        control = {'role':'restore','initial_adapter':str(snapshot),'micro_rng_seed_base':420000,
                   'lora_dropout':.05,'capture_optimizer_gradients':True,'deterministic_execution':PROTOCOL}
        plans.append((name, config, components, control, sha(old/'actual-config.yaml')))
    root.mkdir()
    (root/'data').symlink_to(os.path.relpath(source/'data',root), target_is_directory=True)
    (root/'data-manifest.json').symlink_to(os.path.relpath(source/'data-manifest.json',root))
    (root/'evaluation').mkdir()
    for name, config, components, control, _ in plans:
        folder = root/name; folder.mkdir()
        (folder/'train.yaml').write_text(yaml.safe_dump(config, sort_keys=False))
        (folder/'components.yaml').write_text(yaml.safe_dump(components, sort_keys=False))
        (folder/'paired-control-attempt1.json').write_text(json.dumps(control,indent=2)+'\n')
    for name in ['G06','G07']:
        (root/name).symlink_to(os.path.relpath(resolved/name,root), target_is_directory=True)
        (root/'evaluation'/name).symlink_to(os.path.relpath(resolved/'evaluation'/name,root/'evaluation'), target_is_directory=True)
    manifest = {'status':'PREPARED_NOT_TRAINED','protocol':PROTOCOL,'data_manifest_sha256':DATA_SHA,
                'new_training_runs':[p[0] for p in plans],'new_evaluations':['BASE']+[p[0] for p in plans],
                'reused_runs':['G06','G07'],'reused_pair_root':str(resolved),
                'reused_pair_verdict_sha256':sha(resolved/'resolution-verdict.json'),
                'reused_pair_summary_sha256':sha(resolved/'resolution-summary.json'),
                'initial_adapter_tensor_sha256':verdict['protocols']['G06']['initial_adapter_tensor_sha256'],
                'source_config_sha256':{p[0]:p[4] for p in plans},
                'new_optimizer_updates':144,'new_predictions':448,'cohort_updates':192,'cohort_predictions':576,
                'batch_scope':'Effective batch 4 throughout; G00-G05 microbatch1/accumulation4, G06-G07 microbatch2/accumulation2. Required by existing ODM and nonuniform weighting implementations.',
                'script_sha256':sha(Path(__file__))}
    (root/'cohort-plan.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(manifest),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--source-root',type=Path,default=Path('/runs/strategy-20261023'))
    args=parser.parse_args();prepare(args.root,args.source_root)
