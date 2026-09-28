"""Register the bounded three-evidence baseline pipeline. Does not execute it."""
import argparse
import json
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
helpers = runpy.run_path(str(ROOT / 'scripts/register-paper-pipeline.py'))
api, operator = helpers['api'], helpers['operator']
STATE = ROOT / 'pipelines/sft2000.registration.json'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--render', action='store_true')
    args = parser.parse_args()
    datasets = {}
    for name, file in [('旧 2000 基线 · 三条证据联调', 'evidence-smoke3.jsonl'),
                       ('旧 2000 基线 · 冻结证据参考集', 'evidence-2000.jsonl'),
                       ('1199 篇 TXT · 原始来源目录', 'txt1199-source-catalog.jsonl')]:
        dataset = api('/datasets/', {'name': name, 'root': str(ROOT / 'data/sft2000' / file),
                      'pipeline': 'SFT2000', 'meta': {'scope': 'integration/source reference; not independent evaluation'}})
        datasets[file] = dataset['id']
    print('Input columns:', api('/datasets/columns/' + datasets['evidence-smoke3.jsonl']))
    config = {'file_path': str(ROOT / 'extensions/paper-dataflow/paper_dataflow/pipelines/sft2000.py'),
              'input_dataset': {'id': datasets['evidence-smoke3.jsonl'], 'location': [30, 160]},
              'operators': [
                  operator('SFT2000Generator', {'llm_serving': 'a9885c5b9907017b',
                      'tokenizer_path': str(ROOT / 'models/tokenizers/Qwen3.6-27B-6a9e13bd'),
                      'output_dir': str(ROOT / 'outputs/sft2000-runs'), 'max_records': 3},
                      {'input_key': 'evidence_record', 'output_key': 'generation_result'}, 350),
                  operator('SFT2000Verifier', {'llm_serving': '99e05909b12873c2'},
                      {'input_key': 'generation_result', 'input_evidence_key': 'evidence_record', 'output_key': 'verification_result'}, 670),
                  operator('SFT2000Exporter', {'output_dir': str(ROOT / 'outputs/sft2000-exports')},
                      {'input_key': 'verification_result', 'input_evidence_key': 'evidence_record', 'output_key': 'export_status'}, 990),
              ]}
    validation = api('/pipelines/validate', config)
    if not validation['valid']:
        raise RuntimeError(validation)
    payload = {'name': '旧 2000 基线 · Qwen 生成 → DeepSeek 审核 → SFT 导出（3 条联调）',
               'tags': ['paper', 'baseline', 'sft2000', 'bounded-integration'], 'config': config}
    if STATE.exists():
        pipeline = api('/pipelines/' + json.loads(STATE.read_text())['pipeline_id'], payload, 'PUT')
    else:
        pipeline = api('/pipelines/', payload)
    result = {'pipeline_id': pipeline['id'], 'datasets': datasets, 'validation': validation,
              'generator_serving_id': 'a9885c5b9907017b', 'verifier_serving_id': '99e05909b12873c2'}
    STATE.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    (ROOT / 'pipelines/sft2000.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.render:
        print(api('/agent/render', {'pipeline_id': pipeline['id']}))


if __name__ == '__main__':
    main()
