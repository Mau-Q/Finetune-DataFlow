"""Read-only host accounting and two fixed SciTLDR examples; no model calls."""
import collections
import hashlib
import json
import time
from pathlib import Path
from run_core8_suite import HOST, HOST_RUN, evaluation_folder, successful_folder


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect(root):
    attempts = []
    for folder in sorted(root.glob('G*/attempt*')):
        if not folder.is_dir():
            continue
        events = rows(folder/'events.jsonl')
        resource = read(folder/'resource.json') if (folder/'resource.json').exists() else {}
        attempts.append({'run': folder.parent.name, 'attempt': folder.name,
                         'status': resource.get('status', 'NO_RESOURCE_RECEIPT'),
                         'optimizer_updates_observed': sum(row.get('event') == 'optimizer_step' for row in events),
                         'sample_presentations': sum(len(row['items']) for row in rows(folder/'consumption.jsonl')),
                         'resource': resource})
    evaluation_attempts = []
    for path in sorted((root/'evaluation').rglob('predictions.jsonl')):
        predictions = rows(path)
        evaluation_attempts.append({'path': str(path.relative_to(root)), 'n': len(predictions),
                                    'sha256': sha(path), 'metrics_receipt_exists': (path.parent/'metrics.json').exists(),
                                    'generated_tokens': sum(row['generated_tokens'] for row in predictions),
                                    'reasoning_tag_outputs': (sum(row['reasoning_tag_emitted'] for row in predictions)
                                                              if all('reasoning_tag_emitted' in row for row in predictions) else None),
                                    'reasoning_tag_detection_coverage': sum('reasoning_tag_emitted' in row for row in predictions)})
    monitor = rows(HOST/'core8-logs/driver-memory.jsonl')
    gpu2 = []
    for sample in monitor:
        for line in sample.get('gpu', '').splitlines():
            fields = [part.strip() for part in line.split(',')]
            if fields[0] == '2':
                gpu2.append({'time': sample['time'], 'used_mib': int(fields[2]), 'free_mib': int(fields[3])})
    result = {'captured_unix': time.time(), 'attempts': attempts, 'evaluation_attempts': evaluation_attempts,
              'all_observed_optimizer_updates': sum(row['optimizer_updates_observed'] for row in attempts),
              'all_observed_train_presentations': sum(row['sample_presentations'] for row in attempts),
              'all_generated_prediction_rows': sum(row['n'] for row in evaluation_attempts),
              'sampled_whole_gpu2': {'samples': len(gpu2), 'interval_seconds': 5,
                                    'peak_used_mib': max(row['used_mib'] for row in gpu2),
                                    'minimum_free_mib': min(row['free_mib'] for row in gpu2),
                                    'scope': 'Whole card including other workloads; sampled, not continuous process peak'},
              'accepted_attempts': {name: successful_folder(name, root).name for name in ['G%02d' % i for i in range(8)]}}
    paired = {}
    for name in ['G06', 'G07']:
        folder = successful_folder(name, root)
        paired[name] = {'gradients': rows(folder/'gradient.jsonl')[:16], 'losses': rows(folder/'loss.jsonl')[:8],
                        'initialization': read(folder/'paired-control-receipt.json')}
    result['paired_warmup_diagnostic'] = paired
    # First two frozen SciTLDR IDs, specified without inspecting their outputs.
    metadata = [row for row in rows(root/'data/metadata.jsonl') if row['official_split'] == 'test']
    test_rows = rows(root/'data/test.jsonl')
    selected = [(meta, sample) for meta, sample in zip(metadata, test_rows) if meta['task'] == 'scitldr_aic'][:2]
    examples = []
    for meta, sample in selected:
        predictions = {}
        for name in ['BASE'] + ['G%02d' % i for i in range(8)]:
            path = evaluation_folder(name, root)/'predictions.jsonl'
            matches = [row for row in rows(path) if row['sample_id'] == meta['_instance_id']]
            if matches:
                predictions[name] = matches[0]['prediction']
        examples.append({'sample_id': meta['_instance_id'], 'instruction': sample['instruction'],
                         'reference': sample['output'], 'predictions': predictions})
    result['manual_review_scope'] = 'First two frozen SciTLDR test IDs across all nine models; no model calls or test tuning'
    (root/'manual-review-examples.json').write_text(json.dumps(examples, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    (root/'auxiliary-accounting.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'optimizer_updates': result['all_observed_optimizer_updates'],
                      'predictions': result['all_generated_prediction_rows'], 'attempts': len(attempts)}))


if __name__ == '__main__':
    collect(HOST_RUN)
