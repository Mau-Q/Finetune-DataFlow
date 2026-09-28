"""Offline replay of frozen accepted records. No model or network calls."""
import hashlib
import json
from pathlib import Path
import pandas as pd
from paper_dataflow.baseline import quality as q
from paper_dataflow.baseline.production import checkpoint_rows, derive_production_terminal_fields
from paper_dataflow.operators.paper.generate.sft2000 import finalize_generation, tokenizer_at, SFT2000Exporter

ROOT = Path(__file__).resolve().parents[1]


class MemoryStorage:
    def __init__(self, rows):
        self.frame = pd.DataFrame(rows)

    def read(self, kind):
        return self.frame.copy()

    def write(self, frame):
        self.frame = frame


def main():
    manifest = json.loads((ROOT / 'data/sft2000/manifest.json').read_text())
    archive = Path(manifest['checkpoint'])
    for name, expected in manifest['checkpoint_asset_hashes'].items():
        assert hashlib.sha256((archive / name).read_bytes()).hexdigest() == expected, name
    evidence_path = ROOT / 'data/sft2000/evidence-2000.jsonl'
    assert hashlib.sha256(evidence_path.read_bytes()).hexdigest() == manifest['datasets'][evidence_path.name]
    audit = [json.loads(line) for line in (archive / 'audit.jsonl').read_text().splitlines()]
    evidence = [json.loads(line)['evidence_record'] for line in evidence_path.read_text().splitlines()]
    sft = [json.loads(line) for line in (archive / 'sft.jsonl').read_text().splitlines()]
    tokenizer = tokenizer_at(ROOT / 'models/tokenizers/Qwen3.6-27B-6a9e13bd')
    accepted, rows, differences = [], [], []
    for original, record in zip(audit, evidence, strict=True):
        old = original['semantic_result']
        result = finalize_generation(old['generator_observation'], record, tokenizer)
        if result['generated'] != old['generated'] or result.get('metrics') != old['metrics']:
            differences.append({'candidate_id': record['candidate_id'], 'stage': 'generation'})
            continue
        result['verifier_observation'] = old['verifier_observation']
        result = q.finalize_verifier_observation(result, evidence=record['evidence'],
                question=result['generated']['question'], answer=result['generated']['answer'])
        for key in ('quality_decision', 'processing_status', 'semantic_verifier', 'reason_codes'):
            if result.get(key) != old.get(key):
                differences.append({'candidate_id': record['candidate_id'], 'field': key})
        item = {**original, 'semantic_result': result}
        terminal, stage, reasons, question_hash = derive_production_terminal_fields(item, accepted=accepted)
        if terminal != original['terminal_state'] or question_hash != original['normalized_question_sha256']:
            differences.append({'candidate_id': record['candidate_id'], 'stage': 'production'})
        accepted.append(item)
        rows.append({'evidence_record': record, 'verification_result': result})
    replay_sft, replay_mapping, _ = checkpoint_rows(accepted, audit[0]['run_identity_sha256'])
    assert replay_sft == sft, 'Frozen export content differs'
    old_mapping = [json.loads(line) for line in (archive / 'record_mapping.jsonl').read_text().splitlines()]
    assert replay_mapping == old_mapping, 'Frozen mapping differs'
    storage = MemoryStorage(rows)
    SFT2000Exporter(str(ROOT / 'outputs/sft2000-offline-replay')).run(storage)
    export_dir = Path(storage.frame['export_status'].iloc[0]['export_dir'])
    adapter_sft = [json.loads(line) for line in (export_dir / 'sft.jsonl').read_text().splitlines()]
    assert adapter_sft == sft, 'DataFlow exporter content differs'
    report = {'status': 'PASS' if not differences else 'FAIL', 'record_count': len(audit),
              'generation_metrics_match': not any(d.get('stage') == 'generation' for d in differences),
              'verifier_and_terminal_match': not differences, 'export_content_match': adapter_sft == sft,
              'original_mapping_match': replay_mapping == old_mapping, 'differences': differences,
              'export_dir': str(export_dir), 'network_calls': 0,
              'scope': 'Accepted historical records only; no claim about new data quality or full candidate selection.'}
    (ROOT / 'logs/sft2000-replay.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if differences:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
