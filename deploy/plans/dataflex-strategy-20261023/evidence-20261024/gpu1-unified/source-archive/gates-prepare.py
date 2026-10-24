"""Prepare independent gates or eight fresh strategies, preserving frozen inputs."""
import argparse
import json
from pathlib import Path
import yaml
from observed_run import sha
from extended_execution_policy import PROTOCOL

DATA_SHA = 'f2e723257b323c022729a01207b45c036d3c98d61debdc71087a252e58c66b7e'
INIT_SHA = '3bf6a156850eca6cc0a5a0f914ed9eae38002687fc94f6ec585a1dbcd321820f'


def prepare(root, source, gates):
    assert root.is_absolute() and '..' not in root.parts
    if root.exists():
        raise FileExistsError('Preserve attempts; root already exists')
    assert sha(source/'data-manifest.json') == DATA_SHA
    snapshot = source/'paired-initialization-v2/adapter_init.safetensors'
    identity = json.loads((snapshot.parent/'identity.json').read_text())
    assert identity['tensor_state_sha256'] == INIT_SHA
    assert sha(snapshot) == identity['file_sha256']
    if not gates:
        verdict = json.loads((source/'gpu1-gates-20261024/gate-verdict.json').read_text())
        assert verdict['status'] == 'GPU1_CAPACITY_RELOAD_AND_REPEATABILITY_PASS'
    plans = []
    names = (['GATE2-B1', 'GATE2-B2'] + ['P-'+n for n in ['G01-A', 'G01-B', 'G02-A', 'G06-A', 'G06-B', 'G07-A']]
             if gates else ['G%02d'%i for i in range(8)])
    for name in names:
        origin = name if name.startswith('GATE') else name.removeprefix('P-').split('-')[0]
        if origin in ['G06', 'G07']:
            old = source/'gradient-resolution-v2-20261023'/origin/'attempt1'
        elif origin.startswith('GATE'):
            old = Path(json.loads((source/origin/'successful-attempt.json').read_text())['observation_dir'])
        else:
            old = source/'uniform-core8-20261023'/origin/'attempt1'
            if not (old/'actual-config.yaml').exists():
                old = Path(json.loads((source/origin/'successful-attempt.json').read_text())['observation_dir'])
        config = yaml.safe_load((old/'actual-config.yaml').read_text())
        components_path = Path(config['components_cfg_file'])
        if origin.startswith('GATE'):
            # The original capacity gates predate source-manifest capture.
            # Verify their actual config against the successful resource receipt;
            # new gates receive full manifests under the current observer.
            assert sha(old/'actual-config.yaml') == json.loads((old/'resource.json').read_text())['config_sha256']
        else:
            assert sha(components_path) == json.loads((old/'manifest.json').read_text())['components_sha256']
        components = yaml.safe_load(components_path.read_text())
        folder = root/name
        config.update(full_determinism=False, output_dir=str(folder/'attempt1/output'),
                      components_cfg_file=str(folder/'components.yaml'))
        if config['train_type'] == 'dynamic_select':
            components['selectors'][config['component_name']]['params']['cache_dir'] = str(folder/'attempt1/strategy-cache')
        if not origin.startswith('GATE'):
            assert config['max_steps'] == 24 and config['cutoff_len'] == 1024
            assert config['per_device_train_batch_size'] == (2 if origin in ['G06', 'G07'] else 1)
            assert config['per_device_train_batch_size']*config['gradient_accumulation_steps'] == 4
        assert config['lora_dropout'] == .05
        control = {'role': 'restore', 'initial_adapter': str(snapshot), 'micro_rng_seed_base': 420000,
                   'lora_dropout': .05, 'capture_optimizer_gradients': True, 'deterministic_execution': PROTOCOL}
        plans.append((name, config, components, control, sha(old/'actual-config.yaml')))
    root.mkdir()
    for name in ['data', 'data-manifest.json', 'gate-representative']:
        (root/name).symlink_to(source/name, target_is_directory=name != 'data-manifest.json')
    (root/'evaluation').mkdir()
    for name, config, components, control, _ in plans:
        folder = root/name; folder.mkdir()
        (folder/'train.yaml').write_text(yaml.safe_dump(config, sort_keys=False))
        (folder/'components.yaml').write_text(yaml.safe_dump(components, sort_keys=False))
        (folder/'paired-control-attempt1.json').write_text(json.dumps(control, indent=2)+'\n')
    result = {'status': 'PREPARED_NOT_TRAINED', 'protocol': PROTOCOL, 'gates': gates,
              'data_manifest_sha256': DATA_SHA, 'initial_adapter_tensor_sha256': INIT_SHA,
              'snapshot_sha256': identity['file_sha256'], 'runs': names, 'reused_runs': [],
              'source_configs': {p[0]: p[4] for p in plans}, 'script_sha256': sha(Path(__file__)),
              'new_optimizer_updates': 28 if gates else 192, 'new_predictions': 4 if gates else 576,
              'batch_scope': 'G00-G05 MB1/acc4, G06-G07 MB2/acc2; effective batch4; microbatches are not bitwise equivalent'}
    (root/'cohort-plan.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=Path('/runs/strategy-20261023'))
    parser.add_argument('--gates', action='store_true')
    args = parser.parse_args(); prepare(args.root, args.source_root, args.gates)
