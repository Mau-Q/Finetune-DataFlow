"""Read-only validation of the prepared experiment; no generation or credentials."""
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from transformers import AutoTokenizer

ROOT = Path(__file__).resolve().parents[1]


def rows(path):
    with path.open(encoding='utf-8') as stream:
        return [json.loads(line) for line in stream if line.strip()]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    data = ROOT / 'data/round1/development'
    manifest = json.loads((data / 'manifest.json').read_text())
    reproduced = json.loads((ROOT / 'outputs/round1-package-reproduction/manifest.json').read_text())
    assert manifest == reproduced, 'Final manifest differs from independent offline reproduction'
    for filename, expected in manifest['artifact_sha256'].items():
        assert sha(data / filename) == expected
        assert sha(ROOT / 'outputs/round1-package-reproduction' / filename) == expected
    assert sha(ROOT / 'extensions/paper-dataflow/paper_dataflow/pipelines/round1_prepare.py') == manifest['source_sha256']['round1_prepare.py']
    evidence = rows(data / 'shared-evidence.jsonl')
    requests = rows(data / 'requests.jsonl')
    selected = {r['candidate_id']: r for r in evidence}
    assert len(selected) == len(evidence) == 11
    assert len({r['paper_id'] for r in evidence}) == 6
    assert len(requests) == len({r['request_id'] for r in requests}) == 22
    by_candidate = defaultdict(dict)
    for req in requests:
        r = selected[req['candidate_id']]
        assert req['status'] == 'PREPARED_NOT_SENT'
        assert req['evidence_raw_sha256'] == r['evidence_raw_sha256']
        assert hashlib.sha256(r['evidence'].encode()).hexdigest() == r['evidence_raw_sha256']
        canonical = json.dumps(req['payload'], ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        assert hashlib.sha256(canonical.encode()).hexdigest() == req['payload_sha256']
        by_candidate[req['candidate_id']][req['arm']] = req
    for identity, pair in by_candidate.items():
        assert set(pair) == {'A', 'B'}
        a, b = pair['A']['payload'], pair['B']['payload']
        assert {k: v for k, v in a.items() if k != 'messages'} == {k: v for k, v in b.items() if k != 'messages'}
        text = selected[identity]['evidence']
        assert text in a['messages'][1]['content']
        assert json.loads(b['messages'][1]['content'])['paper_evidence'] == text
    for r in evidence:
        assert sha(Path(r['pdf_path'])) == r['pdf_sha256']
        assert sha(Path(r['archive_path'])) == r['archive_sha256']
        source_rows = rows(ROOT / 'outputs/round1-development-parse' / r['paper_id'] / 'chunks.jsonl')
        page = next(x['source_page'] for x in source_rows if x['source_page']['page_number'] == r['page_number'])
        assert page['text'][r['char_start']:r['char_end']] == r['evidence']
    selection = json.loads((ROOT / 'data/round1/paper-selection.json').read_text())['selection']
    dev = {r['paper_id'] for r in selection if r['experiment_split'] == 'development'}
    confirm = {r['paper_id'] for r in selection if r['experiment_split'] == 'confirmation'}
    assert len(dev) == 6 and len(confirm) == 20 and not dev & confirm
    assert all(not (ROOT / 'data/round1/pdfs' / p).exists() for p in confirm)
    tokenizer = AutoTokenizer.from_pretrained(ROOT / 'models/tokenizers/Qwen2.5-7B-Instruct', local_files_only=True)
    estimates = defaultdict(int)
    for req in requests:
        estimates[req['arm']] += sum(len(tokenizer.encode(m['content'], add_special_tokens=False)) for m in req['payload']['messages'])
    reviews = rows(ROOT / 'outputs/round1-source-review/agent-input-review.jsonl')
    test_log = ROOT / 'logs/round1-preparation-tests-final.log'
    assert 'Ran 22 tests' in test_log.read_text() and test_log.read_text().rstrip().endswith('OK')
    print(json.dumps({
        'integrity_checks': 'PASS', 'generation_ready': False, 'paid_calls': 0,
        'development_papers': len(dev), 'target_pages': 12, 'selected_chunks': len(evidence),
        'prepared_requests': len(requests), 'confirmation_papers_reserved': len(confirm),
        'jsonl_artifacts_reproduced_byte_identically': len(manifest['artifact_sha256']),
        'source_pages_rendered_and_agent_reviewed': len(reviews),
        'unit_tests_passed': 22, 'test_log_sha256': sha(test_log),
        'input_content_token_proxy_by_arm': dict(estimates),
        'token_proxy_warning': 'Qwen2.5 local tokenizer, message content only; excludes chat framing and is not provider billing usage.',
        'prepared_output_token_ceiling': len(requests) * 2048,
        'remaining_items': ['1 selected chunk requires source-backed formula correction',
                            '1 target page excluded by current chunk policy; coverage shortfall remains explicit',
                            'Currency budget and live API behavior have not been established'],
        'evidence_manifest_sha256': sha(data / 'manifest.json'),
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
