"""Prepare a fresh isolated paired rerun; never replace historical attempts."""
import argparse
import json
from pathlib import Path
import yaml


def prepare(root, source):
    if not root.is_absolute() or '..' in root.parts:
        raise ValueError('Explicit absolute root required')
    if root.exists():
        raise FileExistsError('Preserve the existing attempt; choose a new root')
    configs = {}
    for name, attempt in [('G06', 'attempt4'), ('G07', 'attempt2')]:
        configs[name] = yaml.safe_load((source/name/('paired-'+attempt+'.yaml')).read_text())
    snapshot = source/'paired-initialization-v2/adapter_init.safetensors'
    assert snapshot.is_file() and (source/'data-manifest.json').is_file()
    root.mkdir()
    (root/'data').symlink_to(source/'data', target_is_directory=True)
    (root/'data-manifest.json').symlink_to(source/'data-manifest.json')
    for name, config in configs.items():
        folder = root/name
        folder.mkdir()
        config.update(full_determinism=False, output_dir=str(folder/'attempt1/output'))
        (folder/'train.yaml').write_text(yaml.safe_dump(config, sort_keys=False))
        control = {'role':'restore', 'initial_adapter':str(snapshot),
                   'micro_rng_seed_base':420000, 'lora_dropout':.05,
                   'capture_optimizer_gradients':True,
                   'deterministic_execution':'torch-math-cublas4096-v2'}
        (folder/'paired-control-attempt1.json').write_text(json.dumps(control,indent=2)+'\n')
    print(json.dumps({'status':'PREPARED_NOT_TRAINED', 'root':str(root),
                      'protocol':'torch-math-cublas4096-v2', 'full_determinism':False}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--source-root',type=Path,default=Path('/runs/strategy-20261023'))
    args=parser.parse_args()
    prepare(args.root,args.source_root)
