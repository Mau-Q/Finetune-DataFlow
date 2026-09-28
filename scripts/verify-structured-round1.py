"""Validate source coverage and paired requests for the active preparation."""
import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from transformers import AutoTokenizer
from paper_dataflow.operators.paper.generate.preparation import MinerU4PageExtractor
from paper_dataflow.pipelines.round1_prepare import MemoryStorage, read_jsonl

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(output_path=None):
    active = json.loads((ROOT / 'data/round1/active-preparation.json').read_text())
    data = ROOT / active['directory']
    manifest = json.loads((data / 'manifest.json').read_text())
    for name, digest in manifest['artifact_sha256'].items():
        assert sha(data / name) == digest, name
    for name, digest in manifest['source_sha256'].items():
        assert sha(ROOT / name) == digest, name
    assert sha(Path(manifest['selection_file'])) == manifest['selection_sha256']
    docs = read_jsonl(data / 'documents.jsonl')
    for r in docs:
        assert sha(Path(r['parsed_document']['snapshot_path'])) == r['parsed_document']['document_id']
    storage = MemoryStorage(docs)
    MinerU4PageExtractor().run(storage)
    pages = {(r['source_page']['document_id'], r['source_page']['page_number']): r['source_page']
             for r in storage.frame.to_dict('records')}
    tokenizer = AutoTokenizer.from_pretrained(ROOT / 'models/tokenizers/Qwen2.5-7B-Instruct', local_files_only=True)
    chunks = read_jsonl(data / 'all-chunks.jsonl')
    coverage = defaultdict(list)
    for r in chunks:
        meta, text = r['chunk_metadata'], r['raw_chunk']
        count = len(tokenizer.encode(text, add_special_tokens=False))
        assert count == meta['token_count']
        assert count <= 1024 or 'oversize_preserved' in meta['flags']
        parts = []
        for s in meta['source_segments']:
            page = pages[meta['document_id'], s['page_number']]
            source = page['text'][s['char_start']:s['char_end']]
            assert source == text[s['chunk_char_start']:s['chunk_char_end']]
            parts.append(source)
            coverage[meta['document_id'], s['page_number'], s['block_id']].append((s['char_start'], s['char_end']))
        assert '\n'.join(parts) == text
    excluded = {(r['document_id'], r['page_number'], r['block_id'])
                for r in read_jsonl(data / 'excluded-blocks.jsonl')}
    included_blocks = 0
    for (doc_id, number), page in pages.items():
        for block in page['blocks']:
            if not block['content'].strip():
                continue
            key = (doc_id, number, block['block_id'])
            if key in excluded:
                assert key not in coverage
                continue
            intervals = sorted(coverage[key])
            assert intervals and intervals[0][0] == block['char_start']
            assert intervals[-1][1] == block['char_end']
            assert all(a[1] == b[0] for a, b in zip(intervals, intervals[1:]))
            included_blocks += 1
    selected = {r['candidate_id']: r for r in read_jsonl(data / 'shared-evidence.jsonl')}
    requests = read_jsonl(data / 'requests.jsonl')
    assert len(selected) == 11 and len(requests) == 22
    assert len({r['request_id'] for r in requests}) == 22
    grouped, tokens = defaultdict(dict), defaultdict(int)
    chunks_by_id = {r['chunk_metadata']['chunk_id']: r for r in chunks}
    for req in requests:
        row = selected[req['candidate_id']]
        assert chunks_by_id[row['chunk_id']]['chunk_metadata']['eligible_for_qa']
        assert chunks_by_id[row['chunk_id']]['raw_chunk'] == row['evidence']
        assert req['status'] == 'PREPARED_NOT_SENT'
        assert req['evidence_raw_sha256'] == hashlib.sha256(row['evidence'].encode()).hexdigest()
        serialized = json.dumps(req['payload'], ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        assert req['payload_sha256'] == hashlib.sha256(serialized.encode()).hexdigest()
        grouped[req['candidate_id']][req['arm']] = req['payload']
        tokens[req['arm']] += sum(len(tokenizer.encode(m['content'], add_special_tokens=False)) for m in req['payload']['messages'])
    for identity, pair in grouped.items():
        assert set(pair) == {'A', 'B'}
        assert {k: v for k, v in pair['A'].items() if k != 'messages'} == {k: v for k, v in pair['B'].items() if k != 'messages'}
        evidence = selected[identity]['evidence']
        assert evidence in pair['A']['messages'][1]['content']
        assert evidence == json.loads(pair['B']['messages'][1]['content'])['paper_evidence']
    log = (ROOT / 'logs/round1-structured-regression-final.log').read_text()
    assert 'Ran 29 tests' in log and log.rstrip().endswith('OK')
    result = {'integrity': 'PASS', 'source_pages': len(pages), 'all_chunks': len(chunks),
              'included_blocks_fully_preserved': included_blocks, 'excluded_blocks_accounted_for': len(excluded),
              'selected_chunks': len(selected), 'prepared_requests': len(requests),
              'cross_page_chunks': manifest['cross_page_chunks'], 'tests_passed': 29,
              'input_content_token_proxy_by_arm': dict(tokens),
              'proxy_warning': 'Local Qwen2.5 message-content tokens; excludes chat framing; not supplier billing',
              'evidence_over_400_mixed_units': sum(r['evidence_mixed_units'] > 400 for r in selected.values()),
              'paid_calls': 0, 'quality_claim': 'Source-reviewed development inputs, not SFT or model quality results',
              'manifest_sha256': sha(data / 'manifest.json')}
    serialized = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if output_path:
        with Path(output_path).open('x', encoding='utf-8') as stream:
            stream.write(serialized)
    else:
        print(serialized)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', help='Write clean JSON independently of imported library logs')
    main(parser.parse_args().output)
