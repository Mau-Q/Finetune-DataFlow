"""CPU evidence gate for the bounded G01/G02 numerical investigation."""
import argparse
import hashlib
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text())


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pair(left, right):
    names = ['initial-model-hashes.json', 'probe-inputs.jsonl', 'probe-model-inputs.jsonl',
             'consumption.jsonl', 'paired-rng.jsonl', 'loss.jsonl', 'diagnostic-layers.jsonl',
             'optimizer-gradients.jsonl', 'probe-updates.jsonl']
    checks = {}
    for name in names:
        parse = read if name.endswith('.json') else rows
        checks[name] = parse(left/name) == parse(right/name)
    a, b = [rows(p/'gradient.jsonl') for p in (left, right)]
    assert len(a) == len(b) == 32
    assert [(x['micro'], x['parameter']) for x in a] == [(x['micro'], x['parameter']) for x in b]
    differences = [abs(x['norm']-y['norm'])/max(abs(x['norm']), 1e-4) for x, y in zip(a, b)]
    outside = sum(abs(x['norm']-y['norm']) > 1e-4+.02*abs(x['norm']) for x, y in zip(a, b))
    raw = {p.name: sha(p) == sha(right/p.name) for p in sorted(left.glob('gradient-*.safetensors'))}
    assert len(raw) == 16
    return {'checks': checks, 'raw_representative_gradient_files_equal': raw,
            'max_representative_norm_relative_difference': max(differences),
            'norm_pairs_outside_original_tolerance': outside,
            'optimizer_input_tensors_compared': sum(len(x['tensors']) for x in rows(left/'optimizer-gradients.jsonl')),
            'post_update_parameter_tensors_compared': sum(len(x['trainable_parameter_hashes']) for x in rows(left/'probe-updates.jsonl'))}


def verify(root, prefix='fixed2'):
    cases = [prefix+'-'+n for n in ['G01-A', 'G01-B', 'G02-A']]
    policy_name = 'fla-compile-ordered-config-v3' if prefix == 'fixed3' else 'fla-linear-fixed-v2'
    folders = [root/n/'probe' for n in cases]
    for p in folders:
        receipt = read(p/'probe-complete.json')
        assert receipt['status'] == 'BOUNDED_PROBE_COMPLETED' and receipt['stop_step'] == 4
        assert [x['step'] for x in rows(p/'events.jsonl') if x.get('event') == 'optimizer_step'] == [1, 2, 3, 4]
        assert len(rows(p/'consumption.jsonl')) == len(rows(p/'loss.jsonl')) == 16
        assert len(read(p/'initial-model-hashes.json')) == 3049
        assert rows(p/'probe-state.jsonl')[0]['max_steps_unchanged'] == 24
        for filename, key in [('optimizer-gradients.jsonl', 'tensors'),
                              ('probe-updates.jsonl', 'trainable_parameter_hashes')]:
            values = rows(p/filename)
            assert [x['step'] for x in values] == [1, 2, 3, 4]
            assert all(len(x[key]) == 496 for x in values)
        assert not (p/'strategy.jsonl').exists(), 'No selection may execute during this warmup gate'
        assert read(p.parent/'fla-policy.json')['policy'] == policy_name
    assert all(read(p.parent/'fla-policy.json') == read(folders[0].parent/'fla-policy.json') for p in folders)
    assert all(read(p/'manifest.json')['source_files'] == read(folders[0]/'manifest.json')['source_files'] for p in folders)
    assert all(len(read(p/'manifest.json')['source_files']) == 75 for p in folders)
    results = {cases[i]: pair(folders[0], folders[i]) for i in (1, 2)}
    passed = all(all(x['checks'].values()) and all(x['raw_representative_gradient_files_equal'].values())
                 and x['norm_pairs_outside_original_tolerance'] == 0 for x in results.values())
    updates = {}
    for p in sorted(root.glob('*/probe/events.jsonl')):
        steps = [x['step'] for x in rows(p) if x.get('event') == 'optimizer_step']
        updates[p.parent.parent.name] = len(steps)
    return {'status': 'G01_G02_NUMERICAL_WARMUP_RESOLVED' if passed else 'WARMUP_REPRODUCIBILITY_GATE_FAILED',
            'scope': 'Three independent real CLI processes, same frozen warmup; 4 optimizer updates and 16 microbatches each. No full strategy training or evaluation claimed.',
            'comparisons': results, 'optimizer_updates_by_attempt': updates,
            'new_observed_optimizer_updates': sum(updates.values()), 'new_predictions': 0,
            'protocol': 'torch-math-cublas4096-v2 plus '+policy_name,
            'initial_state_entries': len(read(folders[0]/'initial-model-hashes.json')),
            'policy': read(folders[0].parent/'fla-policy.json'),
            'evidence_sha256': {str(p.relative_to(root)): sha(p) for folder in folders
                               for p in sorted(folder.glob('*')) if p.suffix in ('.json', '.jsonl', '.yaml')},
            'script_sha256': sha(Path(__file__))}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--prefix', choices=['fixed2', 'fixed3'], default='fixed2')
    args = parser.parse_args()
    result = verify(args.root, args.prefix)
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'evidence_sha256'}), flush=True)
    if result['status'] != 'G01_G02_NUMERICAL_WARMUP_RESOLVED':
        raise SystemExit(1)
