"""Offline development preparation: original-paper PDFs -> shared chunks -> A/B requests.

No generation client or credential loading is implemented in this module.
"""
import argparse
import hashlib
import json
import re
import subprocess
import time
import zipfile
from pathlib import Path

import pandas as pd
from dataflow.operators.text_sft import SFTGeneratorSeed
from dataflow.utils.storage import FileStorage
from paper_dataflow.baseline import quality
from paper_dataflow.baseline.mixed_count import word_compatible_mixed_count
from paper_dataflow.operators.paper.generate.preparation import (
    MinerU4PageExtractor, PaperEvidenceChunker, sha256,
)

CUSTOM_PROMPT = '问题和回答使用自然简体中文；只依据给定文档内容，不补充文档之外的事实。'
SEED = 'dataflow-round1-20260922'
COMMON = {
    'model': 'qwen3.7-plus', 'temperature': 0.2, 'enable_thinking': False,
    'max_tokens': 2048, 'response_format': {'type': 'json_object'},
}


def read_jsonl(path):
    # str.splitlines() would also split U+2028 characters inside JSON strings.
    with Path(path).open(encoding='utf-8') as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')


def canonical_paper_id(row, expected):
    # FileStorage/pandas may infer arXiv IDs such as 2603.04254 as floats.
    # Recover only from the preserved source manifest, never from float formatting.
    if row['source']['paper_id'] != expected:
        raise ValueError('Source paper identity mismatch')
    if isinstance(row['paper_id'], str) and row['paper_id'] != expected:
        raise ValueError('Paper identity mismatch')
    row['paper_id'] = expected


def block_windows(row, chunker):
    """Candidate windows at whole-block boundaries; retain exact page substrings."""
    page = row['source_page']
    blocks = page['blocks']
    candidates = []
    allowed = {'text', 'title', 'equation', 'table'}
    for i, first in enumerate(blocks):
        if first['type'] not in {'text', 'title'}:
            continue
        prefix = first['content'].lstrip('*#0123456789. \n')
        if not prefix or not prefix[0].isupper():
            continue  # avoid obvious mid-word or lower-case continuation starts
        for j in range(i, len(blocks)):
            last = blocks[j]
            if last['type'] not in allowed:
                break
            start, end = first['char_start'], last['char_end']
            text = page['text'][start:end]
            count = len(chunker._encode(text)['input_ids'])
            if count > chunker.chunk_size:
                break  # never truncate a table, equation or text block to fit
            closed = last['type'] == 'table' and last['content'].rstrip().endswith('</table>')
            closed = closed or bool(re.search(r'[.!?。！？][*\"\)\]]*$', last['content'].rstrip()))
            if count < 80 or last['type'] == 'equation' or not closed:
                continue
            identity = f"{page['document_id']}:{page['page_number']}:{start}:{end}:{text}"
            meta = {'chunk_id': hashlib.sha256(identity.encode()).hexdigest(),
                    'document_id': page['document_id'], 'page_number': page['page_number'],
                    'char_start': start, 'char_end': end, 'offset_unit': 'unicode_codepoint',
                    'token_count': count, 'chunk_size': chunker.chunk_size,
                    'tokenizer_files_sha256': chunker.tokenizer_files,
                    'eligible_for_qa': True, 'blocks': blocks[i:j + 1],
                    'selection_policy': 'complete_block_window_80_to_512_tokens'}
            candidates.append({**row, 'raw_chunk': text, 'chunk_metadata': meta})
    return candidates


class MemoryStorage:
    def __init__(self, rows):
        self.frame = pd.DataFrame(rows)

    def read(self, kind):
        return self.frame.copy()

    def write(self, frame):
        self.frame = frame.copy()
        return 'memory-only'


class CaptureServing:
    """Exercise the real official operator without network access."""
    def __init__(self):
        self.inputs = []

    def generate_from_input(self, user_inputs, **kwargs):
        self.inputs.extend(user_inputs)
        return ['{"instruction":"离线占位问题","output":"离线占位答案"}'] * len(user_inputs)


def build_requests(record):
    if not isinstance(record['evidence'], str) or not record['evidence'].strip():
        raise ValueError('Empty evidence')
    if quality.sha256_text(record['evidence']) != record['evidence_raw_sha256']:
        raise ValueError('Evidence identity mismatch')
    capture = CaptureServing()
    op = SFTGeneratorSeed(llm_serving=capture, custom_prompt=CUSTOM_PROMPT)
    op.run(MemoryStorage([{'raw_content': record['evidence']}]))
    if len(capture.inputs) != 1:
        raise ValueError('Expected exactly one official generation request')
    messages = {
        'A': [{'role': 'system', 'content': 'You are a helpful assistant'},
              {'role': 'user', 'content': capture.inputs[0]}],
        'B': quality.generator_messages(record),
    }
    requests = []
    # Stable interleaving; half of candidate pairs approximately begin with B.
    arms = ['A', 'B'] if int(record['candidate_id'][-1], 16) % 2 == 0 else ['B', 'A']
    for arm in arms:
        payload = {**COMMON, 'messages': messages[arm]}
        requests.append({
            'request_id': record['candidate_id'] + ':' + arm,
            'candidate_id': record['candidate_id'], 'paper_id': record['paper_id'],
            'arm': arm, 'evidence_raw_sha256': record['evidence_raw_sha256'],
            'payload': payload, 'payload_sha256': quality.sha256_text(quality.canonical_json(payload)),
            'status': 'PREPARED_NOT_SENT',
        })
    return requests


class Round1PreparationPipeline:
    def __init__(self, workspace, output_path):
        self.root = Path(workspace).resolve()
        self.output = Path(output_path).resolve()
        self.op_extract_step2 = MinerU4PageExtractor()
        self.op_chunk_step3 = PaperEvidenceChunker(
            str(self.root / 'models/tokenizers/Qwen2.5-7B-Instruct'), 512, 64,
        )

    def parse_one(self, source):
        paper_id = source['paper_id']
        dest = self.output / paper_id
        dest.mkdir(parents=True, exist_ok=False)
        source_path = Path(source['source_path'])
        if sha256(source_path) != source['sha256']:
            raise ValueError('PDF identity mismatch')
        import pymupdf
        with pymupdf.open(source_path) as pdf:
            if len(pdf) < 3:
                raise ValueError('Development policy requires physical pages 2 and 3')
            page_count = len(pdf)
        archive = dest / 'parsed-pages-2-3.zip'
        command = [str(self.root / 'scripts/mineru.sh'), 'parse', str(source_path),
                   '-o', str(archive), '--format', 'zip', '--tier', 'standard', '--pages', '2-3']
        started = time.monotonic()
        with (dest / 'parse.log').open('w') as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=900, check=True)
        with zipfile.ZipFile(archive) as bundle:
            doc = json.loads(bundle.read('structured_content.json'))
        indices = [p['page_idx'] for p in doc['pages']]
        if indices != [1, 2]:
            raise ValueError(f'Original page indices not preserved: {indices}')
        producer = doc.get('metadata', {}).get('producer', {})
        if not str(producer.get('version', '')).startswith('4.'):
            raise ValueError('Expected MinerU 4 producer identity')
        parsed = {
            'document_id': source['sha256'], 'snapshot_path': str(source_path),
            'source_path': str(source_path), 'archive_path': str(archive),
            'archive_sha256': sha256(archive), 'producer': producer, 'tier': 'standard',
            'selected_physical_pages': [2, 3], 'original_page_count': page_count,
            'scope': 'development_page_subset_not_full_document',
            'reported_is_full_document': doc.get('is_full_document'),
            'wrapper_sha256': sha256(self.root / 'scripts/mineru.sh'),
            'elapsed_seconds': time.monotonic() - started,
        }
        input_path = dest / 'documents.jsonl'
        write_jsonl(input_path, [{'paper_id': paper_id, 'experiment_split': 'development',
                                 'source': source, 'parsed_document': parsed}])
        self.storage = FileStorage(first_entry_file_name=str(input_path),
                                   cache_path=str(dest / 'cache'), cache_type='jsonl')
        self.op_extract_step2.run(self.storage.step(), input_key='parsed_document', output_key='source_page')
        self.op_chunk_step3.run(self.storage.step(), input_key='source_page',
                               output_key='raw_chunk', output_meta_key='chunk_metadata')
        # The next step reads the output produced by the previous operator.
        frame = self.storage.step().read('dataframe')
        write_jsonl(dest / 'chunks.jsonl', frame.to_dict('records'))
        write_new(dest / 'manifest.json', parsed)
        return len(frame)

    def forward(self):
        selection = json.loads((self.root / 'data/round1/paper-selection.json').read_text())
        papers = [p for p in selection['selection'] if p['experiment_split'] == 'development']
        results = []
        for p in papers:
            paper = p['paper_id']
            try:
                source_dir = self.root / f'data/round1/pdfs/{paper}'
                source_file = source_dir / 'source-recovery.json'
                if not source_file.exists():
                    source_file = source_dir / 'source.json'
                source = json.loads(source_file.read_text())
                if source['status'] != 'downloaded':
                    raise ValueError('Source PDF download did not complete')
                count = self.parse_one(source)
                row = {'paper_id': paper, 'status': 'parsed', 'chunks': count}
            except Exception as exc:
                row = {'paper_id': paper, 'status': 'failed', 'error': type(exc).__name__ + ': ' + str(exc)}
            results.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
        write_new(self.output / 'parse-summary.json', results)


def package(workspace, parsed_path, output_path):
    root, parsed_path, output = Path(workspace).resolve(), Path(parsed_path).resolve(), Path(output_path).resolve()
    selection = json.loads((root / 'data/round1/paper-selection.json').read_text())
    papers = [p for p in selection['selection'] if p['experiment_split'] == 'development']
    all_candidates, records, failures = [], [], []
    chunker = PaperEvidenceChunker(str(root / 'models/tokenizers/Qwen2.5-7B-Instruct'), 512, 64)
    for p in papers:
        path = parsed_path / p['paper_id'] / 'chunks.jsonl'
        if not path.exists():
            failures.append({'paper_id': p['paper_id'], 'reason': 'NO_PARSED_CHUNKS'})
            continue
        rows = read_jsonl(path)
        if not rows:
            raise ValueError('Parsed chunk file is empty')
        parsed = rows[0]['parsed_document']
        if sha256(parsed['snapshot_path']) != parsed['document_id']:
            raise ValueError('PDF changed after parsing')
        if sha256(parsed['archive_path']) != parsed['archive_sha256']:
            raise ValueError('Archive changed after parsing')
        for row in rows:
            meta, page = row['chunk_metadata'], row['source_page']
            canonical_paper_id(row, p['paper_id'])
            if row['parsed_document'] != parsed:
                raise ValueError('Mixed document identities')
            if row['raw_chunk'] != page['text'][meta['char_start']:meta['char_end']]:
                raise ValueError('Chunk is not an exact source substring')
        pages = {r['source_page']['page_number']: r for r in rows}
        rows = [candidate for row in pages.values() for candidate in block_windows(row, chunker)]
        all_candidates.extend(rows)
        for page_number in (2, 3):
            candidates = [r for r in rows if r['chunk_metadata']['page_number'] == page_number
                          and r['chunk_metadata']['eligible_for_qa']]
            if not candidates:
                failures.append({'paper_id': p['paper_id'], 'page': page_number, 'reason': 'NO_ELIGIBLE_COMPLETE_BLOCK_WINDOW'})
                continue
            # One chunk per page; select longest by tokenizer count, ID breaks ties.
            # No generation results or old 400-unit rule enter this choice.
            row = sorted(candidates, key=lambda r: (-r['chunk_metadata']['token_count'], r['chunk_metadata']['chunk_id']))[0]
            meta, evidence = row['chunk_metadata'], row['raw_chunk']
            raw_hash = quality.sha256_text(evidence)
            records.append({
                'candidate_id': 'round1-' + meta['chunk_id'], 'paper_id': p['paper_id'],
                'experiment_split': 'development', 'domain': 'original1199_unspecified',
                'chunk_id': meta['chunk_id'], 'evidence': evidence,
                'evidence_raw_sha256': raw_hash, 'evidence_sha256': quality.sha256_text(quality.normalized(evidence)),
                'pdf_sha256': row['parsed_document']['document_id'],
                'pdf_path': row['parsed_document']['snapshot_path'],
                'archive_path': row['parsed_document']['archive_path'],
                'archive_sha256': row['parsed_document']['archive_sha256'],
                'page_number': page_number, 'char_start': meta['char_start'], 'char_end': meta['char_end'],
                'blocks': meta['blocks'], 'token_count': meta['token_count'],
                'evidence_mixed_units': word_compatible_mixed_count(evidence),
                'input_review_status': 'PENDING', 'source_version': row['source']['version'],
            })
    ids = [r['candidate_id'] for r in records]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate candidate IDs')
    requests = [req for r in records for req in build_requests(r)]
    write_jsonl(output / 'all-chunks.jsonl', all_candidates)
    write_jsonl(output / 'shared-evidence.jsonl', records)
    write_jsonl(output / 'requests.jsonl', requests)
    write_jsonl(output / 'input-review.jsonl', [dict(
        candidate_id=r['candidate_id'], paper_id=r['paper_id'], page_number=r['page_number'],
        pdf_path=r['pdf_path'], evidence=r['evidence'],
        parsing_fidelity=None, context_sufficient=None, boundary_complete=None,
        source_type=None, reviewer=None, notes='',
    ) for r in records])
    write_jsonl(output / 'response-template.jsonl', [dict(
        request_id=r['request_id'], raw_response=None, actual_model=None,
        request_started_at=None, elapsed_seconds=None, input_tokens=None, output_tokens=None,
        cost=None, error=None, status='NOT_RUN',
    ) for r in requests])
    manifest = {
        'status': 'PREPARED_PENDING_INPUT_REVIEW' if len(records) == 12 and not failures else 'INCOMPLETE',
        'scope': 'development_only_no_paid_generation', 'failures': failures,
        'papers_expected': 6, 'chunks_selected': len(records), 'requests_prepared': len(requests),
        'common_generation': COMMON, 'endpoint': 'https://maas.qianwenaiapi.com/compatible-mode/v1/chat/completions',
        'serving_reference': 'a9885c5b9907017b',
        'serving_configuration_snapshot': str(root / 'data/round1/generation-serving.snapshot.json'),
        'serving_connectivity_tested': False,
        'concurrency': 1, 'attempts_per_arm_per_chunk': 1, 'timeout_seconds': 60,
        'request_limit': 24, 'prepared_output_token_ceiling': len(requests) * COMMON['max_tokens'],
        'maximum_total_output_tokens': 24 * COMMON['max_tokens'],
        'currency_budget': None, 'paid_calls': 0, 'official_custom_prompt': CUSTOM_PROMPT,
        'B_prompt_version': quality.GENERATOR_PROMPT_VERSION,
        'preparation': {'mineru_tier': 'standard', 'physical_pages': [2, 3],
                        'chunk_size': 512, 'diagnostic_token_window_overlap': 64,
                        'selection': 'one longest complete-block window (80-512 tokens) per page; chunk_id tie break; no atomic block truncation',
                        'overlap': 'candidate windows may overlap; one selected per physical page'},
        'notes': ['PDFs recovered by original arXiv ID; historical byte equality unknown.',
                  'B legacy prompt keeps its 400-unit rule; do not discard raw outputs before common evaluation.',
                  'A retains official prompt ChatML markers as literal user content, matching native API usage.',
                  'No claim of historical holdout: papers only disjoint within current experiment.',
                  'No automatic response generation or source-to-QA admission.'],
        'artifact_sha256': {p.name: sha256(p) for p in sorted(output.glob('*.jsonl'))},
        'source_sha256': {
            'round1_prepare.py': sha256(Path(__file__)),
            'preparation.py': sha256(root / 'extensions/paper-dataflow/paper_dataflow/operators/paper/generate/preparation.py'),
            'quality.py': sha256(root / 'extensions/paper-dataflow/paper_dataflow/baseline/quality.py'),
            'official_generator': sha256(root / 'repos/dataflow/dataflow/operators/text_sft/generate/sft_generator_from_seed.py'),
            'official_prompts': sha256(root / 'repos/dataflow/dataflow/prompts/general_text.py'),
            'model_lock': sha256(root / 'locks/models.json'),
            'selection': sha256(root / 'data/round1/paper-selection.json'),
        },
    }
    write_new(output / 'manifest.json', manifest)
    return manifest


def extract_saved(workspace, parsed_path):
    """Continue from saved MinerU archives; never invoke parsing again."""
    root, output = Path(workspace).resolve(), Path(parsed_path).resolve()
    selection = json.loads((root / 'data/round1/paper-selection.json').read_text())
    chunker = PaperEvidenceChunker(str(root / 'models/tokenizers/Qwen2.5-7B-Instruct'), 512, 64)
    results = []
    for item in selection['selection']:
        if item['experiment_split'] != 'development':
            continue
        dest = output / item['paper_id']
        rows = read_jsonl(dest / 'documents.jsonl')
        if (dest / 'chunks.jsonl').exists():
            results.append({'paper_id': item['paper_id'],
                            'chunks': len(read_jsonl(dest / 'chunks.jsonl')),
                            'status': 'existing_chunks_preserved'})
            continue
        storage = MemoryStorage(rows)
        MinerU4PageExtractor().run(storage)
        chunker.run(storage)
        write_jsonl(dest / 'chunks.jsonl', storage.frame.to_dict('records'))
        if not (dest / 'manifest.json').exists():
            write_new(dest / 'manifest.json', rows[0]['parsed_document'])
        results.append({'paper_id': item['paper_id'], 'chunks': len(storage.frame),
                        'status': 'extracted_from_saved_archive'})
    write_new(output / 'extraction-summary.json', results)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['parse', 'extract-saved', 'package'])
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--parsed')
    args = parser.parse_args()
    if args.mode == 'parse':
        Round1PreparationPipeline(args.workspace, args.output).forward()
    elif args.mode == 'extract-saved':
        print(json.dumps(extract_saved(args.workspace, args.output), ensure_ascii=False, indent=2))
    else:
        if not args.parsed:
            parser.error('--parsed is required for package')
        print(json.dumps(package(args.workspace, args.parsed, args.output), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
