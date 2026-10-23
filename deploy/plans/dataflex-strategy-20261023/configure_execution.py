"""Materialize immutable attempt configs against a frozen dataset; never launch training."""
import argparse
import json
from pathlib import Path

import yaml

ROOT = Path('/runs/strategy-20261023')


def configure(root=ROOT, include_initial_gates=True):
    tasks = json.loads((root / 'data-manifest.json').read_text())['tasks']
    destinations = [root / f'G{i:02d}' / name for i in range(8)
                    for name in ['execution-v2.yaml', 'execution-components-v2.yaml']]
    if include_initial_gates:
        destinations += [root / f'GATE-B{b}' for b in [1, 2]]
    if any(p.exists() for p in destinations):
        raise FileExistsError('Execution configs already exist; preserve them and use a new attempt identity.')
    configs = []
    for i in range(8):
        folder = root / f'G{i:02d}'
        config = yaml.safe_load((folder / 'train.yaml').read_text())
        components = yaml.safe_load((folder / 'components.yaml').read_text())
        config.update(dataset=','.join(tasks), output_dir=str(folder / 'attempt1/output'),
                      save_only_model=True,
                      components_cfg_file=str(folder / 'execution-components-v2.yaml'))
        if config['train_type'] == 'dynamic_select':
            name = config['component_name']
            components['selectors'][name]['params']['cache_dir'] = str(folder / 'attempt1/strategy-cache')
        configs.append((folder, config, components))
    for folder, config, components in configs:
        (folder / 'execution-v2.yaml').write_text(yaml.safe_dump(config, sort_keys=False))
        (folder / 'execution-components-v2.yaml').write_text(yaml.safe_dump(components, sort_keys=False))
    if include_initial_gates:
        for batch in [1, 2]:
            folder = root / f'GATE-B{batch}'
            folder.mkdir(exist_ok=False)
            config = dict(configs[0][1])
            config.update(dataset='gate', eval_dataset=None, do_eval=False, eval_strategy='no',
                          per_device_train_batch_size=batch, gradient_accumulation_steps=4 // batch,
                          max_steps=2, save_steps=2, output_dir=str(folder / 'attempt1/output'),
                          train_sampling_strategy='sequential')
            if batch == 2:
                config.update(train_type='dynamic_weight', component_name='loss', warmup_step=0,
                              components_cfg_file=str(root / 'G07/execution-components-v2.yaml'))
            (folder / 'train.yaml').write_text(yaml.safe_dump(config, sort_keys=False))
    return {'tasks': tasks, 'gate_configured': include_initial_gates,
            'selector_caches': 'inside each immutable attempt'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--core-only', action='store_true')
    args = parser.parse_args()
    print(json.dumps(configure(args.root, not args.core_only)))
