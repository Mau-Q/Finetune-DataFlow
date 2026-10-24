"""GPU gate acceptance from durable observations; original tolerances stay fixed."""
import argparse
import json
from pathlib import Path
import torch
from run_core8_suite import require_gates
from observed_run import sha
from extended_execution_policy import PROTOCOL


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def compare(a, b, accumulation):
    checks = {}
    for name in ['initial-model-hashes.json', 'probe-inputs.jsonl', 'probe-model-inputs.jsonl',
                 'consumption.jsonl', 'paired-rng.jsonl', 'loss.jsonl', 'diagnostic-layers.jsonl',
                 'optimizer-gradients.jsonl', 'probe-updates.jsonl', 'fla-policy.json']:
        parse = json.loads if name.endswith('.json') else lambda s: [json.loads(l) for l in s.splitlines()]
        checks[name] = parse((a/name).read_text()) == parse((b/name).read_text())
    for folder in [a, b]:
        assert json.loads((folder/'probe-complete.json').read_text())['stop_step'] == 4
        assert len(rows(folder/'consumption.jsonl')) == 4*accumulation
        assert [r['step'] for r in rows(folder/'probe-updates.jsonl')] == [1, 2, 3, 4]
        assert all(len(r['tensors']) == 496 for r in rows(folder/'optimizer-gradients.jsonl'))
        assert all(len(r['trainable_parameter_hashes']) == 496 for r in rows(folder/'probe-updates.jsonl'))
    raw = {p.name: sha(p) == sha(b/p.name) for p in a.glob('gradient-*.safetensors')}
    assert len(raw) == 16
    left, right = rows(a/'gradient.jsonl'), rows(b/'gradient.jsonl')
    assert len(left) == len(right) == 8*accumulation
    outside = sum(abs(x['norm']-y['norm']) > 1e-4+.02*abs(x['norm']) for x, y in zip(left, right))
    assert all(checks.values()) and all(raw.values()) and outside == 0, (checks, raw, outside)
    return {'checks': checks, 'raw_gradient_files_equal': raw, 'norm_pairs_outside_original_tolerance': outside,
            'optimizer_input_tensors_compared': 4*496, 'post_update_tensors_compared': 4*496}


def verify(root):
    identity = json.loads((root/'frozen-identity.json').read_text())
    assert identity['status'] == 'MODEL_SHARDS_FROZEN_DATA_AND_INITIAL_FILE_HASHES_MATCH'
    require_gates(root)
    result = {'status': 'GPU1_CAPACITY_RELOAD_AND_REPEATABILITY_PASS', 'protocol': PROTOCOL,
              'comparisons': {}, 'capacity': {}, 'new_optimizer_updates': 28, 'new_predictions': 4}
    for batch in [1, 2]:
        folder = root/('GATE2-B'+str(batch))/'attempt1'
        assert json.loads((folder/'paired-control-receipt.json').read_text())['deterministic_execution_requested'] == PROTOCOL
        result['capacity'][str(batch)] = json.loads((folder/'resource.json').read_text())
    for left, right, acc in [('G01-A', 'G01-B', 4), ('G01-A', 'G02-A', 4), ('G06-A', 'G06-B', 2), ('G06-A', 'G07-A', 2)]:
        result['comparisons'][left+'__'+right] = compare(root/('P-'+left)/'attempt1', root/('P-'+right)/'attempt1', acc)
    result['attempt_costs'] = {}
    for folder in sorted(root.glob('*/attempt1')):
        consumption = rows(folder/'consumption.jsonl')
        items = [item for batch in consumption for item in batch['items']]
        resource = json.loads((folder/'resource.json').read_text())
        result['attempt_costs'][folder.parent.name] = {
            'optimizer_updates': sum(r.get('event') == 'optimizer_step' for r in rows(folder/'events.jsonl')),
            'sample_presentations': len(items), 'effective_tokens': sum(r['effective_tokens'] for r in items),
            'supervised_tokens': sum(r['valid_labels'] for r in items),
            'seconds': resource['seconds'], 'peak_allocated_gib': resource['peak_allocated_gib'],
            'peak_reserved_gib': resource['peak_reserved_gib']}
    assert sum(r['optimizer_updates'] for r in result['attempt_costs'].values()) == 28
    assert sum(r['sample_presentations'] for r in result['attempt_costs'].values()) == 112
    evidence = [p for p in root.rglob('*') if p.is_file() and p.suffix in ['.json', '.jsonl', '.yaml']]
    result['evidence_sha256'] = {str(p.relative_to(root)): sha(p) for p in evidence}
    (root/'gate-verdict.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'status': result['status'], 'capacity': result['capacity']}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--root', type=Path, required=True)
    verify(parser.parse_args().root)
