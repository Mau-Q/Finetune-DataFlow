"""Compact verified results; full predictions, observations and adapters stay on school.

No model calls. Do not use --allow-incomplete output as final acceptance.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

from run_core8_suite import evaluation_folder, require_evaluation, require_mechanism, successful_folder

DEFAULT_ROOT = Path('/sharedata/home/huruiqian/DataFlow/runs/qwen35-9b/20261022-smoke/strategy-20261023')


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def finite_tree(value):
    if isinstance(value, float):
        assert math.isfinite(value)
    elif isinstance(value, dict):
        for item in value.values():
            finite_tree(item)
    elif isinstance(value, list):
        for item in value:
            finite_tree(item)


def summarize(root, allow_incomplete=False):
    manifest = json.loads((root / 'data-manifest.json').read_text(encoding='utf-8'))
    metadata = read_rows(root / 'data/metadata.jsonl')
    test = {row['_instance_id']: row for row in metadata if row['official_split'] == 'test'}
    train = {row['_instance_id'] for row in metadata if row['official_split'] == 'train'}
    assert len(test) == 64 and len(train) == 256 and not train.intersection(test)
    targets = read_rows(root / 'data/test.jsonl')
    expected = dict(zip(test, targets))
    summary = {'status': 'INCOMPLETE', 'scope': 'Direct DataFlex CLI GPU2 engineering acceptance; no platform SSH or algorithm ranking claim',
               'data_manifest_sha256': sha(root / 'data-manifest.json'),
               'dataset_revision': manifest['download']['revision'], 'tasks': manifest['tasks'],
               'data_counts': manifest['counts'], 'task_substitution': manifest['task_substitution'],
               'core_runs': {}, 'evaluations': {}, 'missing_or_failed': [], 'inconclusive': [],
               'artifact_root': str(root), 'full_artifacts_retained_on_school': True}
    for index in range(8):
        name = 'G%02d' % index
        try:
            audit = require_mechanism(name, root)
            folder = successful_folder(name, root)
            observed = read_rows(folder / 'consumption.jsonl')
            assert all(item['sample_id'] in train for batch in observed for item in batch['items'])
            assert audit['optimizer_steps'] == 24 and audit['sample_presentations'] == 96
            resource = json.loads((folder / 'resource.json').read_text(encoding='utf-8'))
            identity = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
            assert sha(folder / 'output/adapter_model.safetensors') == resource['adapter_sha256']
            output = folder / 'output'
            assert (output / 'checkpoint-12/trainer_state.json').exists()
            result = dict(audit)
            result['attempt'] = folder.name
            result['observer_sha256'] = identity['observer_sha256']
            result['source_files_sha256'] = identity['source_files']
            result['packages'] = identity['packages']
            result['source_proportions'] = {name: count / 96 for name, count in audit['source_counts'].items()}
            result['repetition_fraction'] = 1 - audit['distinct_samples'] / 96
            result['adapter_sha256'] = resource['adapter_sha256']
            result['reload_status'] = 'PENDING_EVALUATION'
            paired = result.get('paired_control') or {}
            if paired.get('trajectory_status') == 'INCONCLUSIVE_WARMUP_MISMATCH':
                summary['inconclusive'].append({'name': name, 'scope': 'Separate G06/G07 trajectory gradient attribution',
                    'reason': paired['cross_run_gradient_attribution'],
                    'separate_same_forward_weight_effect_verified': True})
            states = sorted(output.glob('checkpoint-*/trainer_state.json'), key=lambda p: int(p.parent.name.split('-')[-1]))
            history = json.loads(states[-1].read_text(encoding='utf-8'))['log_history']
            result['validation_runs'] = [row for row in history if 'eval_loss' in row]
            result['final_cli_validation'] = json.loads((output / 'eval_results.json').read_text(encoding='utf-8'))
            result['validation_complete_loops_including_final'] = len(result['validation_runs']) + 1
            # These budgets are derived from observed complete evaluation loops
            # and frozen no-truncation lengths, not direct collator observations.
            validation = [m for m in metadata if m['official_split'] == 'validation']
            result['validation_token_budget_derived'] = (sum(m['total_tokens'] for m in validation)
                                                        * result['validation_complete_loops_including_final'])
            summary['core_runs'][name] = result
        except (OSError, KeyError, ValueError, AssertionError) as error:
            summary['missing_or_failed'].append({'name': name, 'phase': 'mechanism', 'error': repr(error)})
    for name in ['BASE'] + ['G%02d' % index for index in range(8)]:
        try:
            receipt = require_evaluation(name, 64, root)
            folder = evaluation_folder(name, root)
            predictions = read_rows(folder / 'predictions.jsonl')
            assert len(predictions) == 64 and {r['sample_id'] for r in predictions} == set(test)
            assert sha(folder / 'predictions.jsonl') == receipt['prediction_sha256']
            for row in predictions:
                assert row['task'] == test[row['sample_id']]['task']
                assert row['reference'] == expected[row['sample_id']]['output']
                assert 0 < row['generated_tokens'] <= 256
            assert all(value['n'] == 16 for value in receipt['metrics'].values())
            finite_tree(receipt)
            receipt['prompt_tokens'] = sum(row['prompt_tokens'] for row in predictions)
            receipt['generated_tokens'] = sum(row['generated_tokens'] for row in predictions)
            receipt['cap_hits'] = sum(row['cap_hit'] for row in predictions)
            summary['evaluations'][name] = receipt
            if name in summary['core_runs']:
                summary['core_runs'][name]['reload_status'] = 'VERIFIED_WITH_64_PREDICTIONS'
        except (OSError, KeyError, ValueError, AssertionError) as error:
            summary['missing_or_failed'].append({'name': name, 'phase': 'evaluation', 'error': repr(error)})
    summary['completed_core_optimizer_updates'] = sum(r['optimizer_steps'] for r in summary['core_runs'].values())
    summary['completed_predictions'] = sum(r['n'] for r in summary['evaluations'].values())
    summary['core_cli_seconds'] = sum(r['resource']['seconds'] for r in summary['core_runs'].values())
    summary['scoring_seconds_included_in_cli'] = sum(r['scoring_seconds'] for r in summary['core_runs'].values())
    summary['evaluation_seconds'] = sum(r['total_seconds'] for r in summary['evaluations'].values())
    if not summary['missing_or_failed']:
        assert summary['completed_core_optimizer_updates'] == 192 and summary['completed_predictions'] == 576
        summary['status'] = ('CORE8_EXECUTION_AND_FROZEN_EVALUATION_VERIFIED_WITH_LIMITATION'
                             if summary['inconclusive'] else 'CORE8_MECHANISMS_AND_FROZEN_EVALUATION_VERIFIED')
    elif not allow_incomplete:
        raise RuntimeError(json.dumps(summary['missing_or_failed']))
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--allow-incomplete', action='store_true')
    args = parser.parse_args()
    result = summarize(args.root, args.allow_incomplete)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps({'status': result['status'], 'optimizer_updates': result['completed_core_optimizer_updates'],
                      'predictions': result['completed_predictions'], 'missing': len(result['missing_or_failed'])}))
