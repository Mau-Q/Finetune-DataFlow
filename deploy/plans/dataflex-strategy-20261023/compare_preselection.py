"""Compare completed bounded probes on CPU; no model loading or GPU work."""
import argparse
import hashlib
import json
from pathlib import Path


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def compare(left, right):
    import torch
    from safetensors.torch import load_file
    for folder in (left, right):
        assert json.loads((folder/'probe-complete.json').read_text())['status'] == 'BOUNDED_PROBE_COMPLETED'
    result = {'left': str(left), 'right': str(right),
              'initial_states_equal': json.loads((left/'initial-model-hashes.json').read_text()) == json.loads((right/'initial-model-hashes.json').read_text()),
              'complete_inputs_equal': rows(left/'probe-inputs.jsonl') == rows(right/'probe-inputs.jsonl'),
              'model_inputs_equal': rows(left/'probe-model-inputs.jsonl') == rows(right/'probe-model-inputs.jsonl'),
              'module_training_states_equal': rows(left/'probe-state.jsonl')[0]['module_training'] == rows(right/'probe-state.jsonl')[0]['module_training'],
              'losses': [rows(folder/'loss.jsonl') for folder in (left, right)]}
    trace = [rows(folder/'diagnostic-layers.jsonl') for folder in (left, right)]
    result['trace_lengths'] = [len(x) for x in trace]
    differences = []
    for i, (a, b) in enumerate(zip(*trace)):
        if a != b:
            differences.append({'trace_index': i, 'left': a, 'right': b})
    result['layer_differences'] = differences
    result['first_layer_difference'] = differences[0] if differences else None
    result['gradients'] = []
    for part in ['A', 'B']:
        a, b = [load_file(str(folder/('gradient-01-'+part+'.safetensors')))['gradient'].float() for folder in (left, right)]
        result['gradients'].append({'part': part, 'equal': torch.equal(a, b),
                                    'relative_l2': float((a-b).norm()/a.norm().clamp_min(1e-6)),
                                    'maximum_absolute_difference': float((a-b).abs().max())})
    result['source_receipts_sha256'] = {
        str(folder/name): hashlib.sha256((folder/name).read_bytes()).hexdigest()
        for folder in (left, right)
        for name in ['probe-complete.json', 'initial-model-hashes.json', 'probe-inputs.jsonl',
                     'probe-model-inputs.jsonl', 'probe-state.jsonl', 'diagnostic-layers.jsonl', 'loss.jsonl']}
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('left', type=Path)
    parser.add_argument('right', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = compare(args.left, args.right)
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k: v for k, v in result.items() if k not in ['layer_differences', 'source_receipts_sha256']}), flush=True)
