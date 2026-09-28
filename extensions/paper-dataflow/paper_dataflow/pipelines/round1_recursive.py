"""Prepare the selected structural chunking policy from saved MinerU archives."""
import argparse
import importlib.metadata
import json
from collections import Counter
from pathlib import Path

from dataflow.utils.storage import FileStorage
from paper_dataflow.baseline import quality
from paper_dataflow.baseline.mixed_count import word_compatible_mixed_count
from paper_dataflow.operators.paper.generate.preparation import MinerU4PageExtractor, sha256
from paper_dataflow.operators.paper.generate.structured_chunking import PaperStructuredChunker
from paper_dataflow.pipelines.round1_prepare import COMMON, build_requests, read_jsonl, write_jsonl, write_new


class Round1RecursivePreparation:
    def __init__(self, workspace, output, selection_file=None):
        self.root, self.output = Path(workspace).resolve(), Path(output).resolve()
        self.selection_file = Path(selection_file).resolve() if selection_file else None
        self.reviewed_selection = json.loads(self.selection_file.read_text()) if self.selection_file else None
        self.output.mkdir(parents=True, exist_ok=False)
        selection = json.loads((self.root / 'data/round1/paper-selection.json').read_text())
        docs = []
        self.paper_ids = []
        for item in selection['selection']:
            if item['experiment_split'] != 'development':
                continue
            paper = item['paper_id']
            self.paper_ids.append(paper)
            doc, = read_jsonl(self.root / 'outputs/round1-development-parse' / paper / 'documents.jsonl')
            if sha256(doc['parsed_document']['snapshot_path']) != doc['parsed_document']['document_id']:
                raise ValueError('PDF changed')
            if doc['source']['paper_id'] != paper:
                raise ValueError('Source identity changed')
            docs.append(doc)
        write_jsonl(self.output / 'documents.jsonl', docs)
        self.storage = FileStorage(first_entry_file_name=str(self.output / 'documents.jsonl'),
                                   cache_path=str(self.output / 'cache'), cache_type='jsonl')
        self.op_extract_step1 = MinerU4PageExtractor()
        self.op_chunk_step2 = PaperStructuredChunker(str(self.root / 'models/tokenizers/Qwen2.5-7B-Instruct'), 1024)

    def forward(self):
        self.op_extract_step1.run(storage=self.storage.step())
        self.op_chunk_step2.run(storage=self.storage.step())
        chunks = self.storage.step().read('dataframe').to_dict('records')
        records, failures = [], []
        for row in chunks:
            row['paper_id'] = row['source']['paper_id']
        for paper in self.paper_ids:
            eligible = [r for r in chunks if r['paper_id'] == paper and r['chunk_metadata']['eligible_for_qa']]
            # Sampling is separate from chunking; all chunks remain in all-chunks.
            eligible.sort(key=lambda r: quality.sha256_text('round1-structural-sample:' + r['chunk_metadata']['chunk_id']))
            if self.reviewed_selection:
                ids = self.reviewed_selection['selected_chunk_ids'][paper]
                by_id = {r['chunk_metadata']['chunk_id']: r for r in eligible}
                if len(ids) != len(set(ids)) or not 0 < len(ids) <= 2:
                    raise ValueError('Reviewed selection must contain one or two distinct chunks per paper')
                eligible = [by_id[identity] for identity in ids]
            if len(eligible) < 2:
                failures.append({'paper_id': paper, 'reason': ('reviewed_selection_has_one_chunk' if self.reviewed_selection else 'fewer_than_two_eligible_chunks')})
            for row in eligible[:2]:
                meta, text = row['chunk_metadata'], row['raw_chunk']
                parsed = row['parsed_document']
                records.append({
                    'candidate_id': 'round1-' + meta['chunk_id'], 'paper_id': paper,
                    'domain': 'original1199_unspecified', 'experiment_split': 'development',
                    'chunk_id': meta['chunk_id'], 'evidence': text,
                    'evidence_raw_sha256': quality.sha256_text(text),
                    'evidence_sha256': quality.sha256_text(quality.normalized(text)),
                    'source_segments': meta['source_segments'], 'page_numbers': meta['page_numbers'],
                    'section_title': meta['section_title'], 'token_count': meta['token_count'],
                    'evidence_mixed_units': word_compatible_mixed_count(text),
                    'pdf_path': parsed['snapshot_path'], 'pdf_sha256': parsed['document_id'],
                    'archive_path': parsed['archive_path'], 'archive_sha256': parsed['archive_sha256'],
                    'source_version': row['source']['version'], 'input_review_status': 'PENDING',
                })
        requests = [req for row in records for req in build_requests(row)]
        write_jsonl(self.output / 'all-chunks.jsonl', chunks)
        write_jsonl(self.output / 'excluded-blocks.jsonl', self.op_chunk_step2.exclusions)
        write_jsonl(self.output / 'shared-evidence.jsonl', records)
        write_jsonl(self.output / 'requests.jsonl', requests)
        write_jsonl(self.output / 'input-review.jsonl', [dict(
            candidate_id=r['candidate_id'], paper_id=r['paper_id'], page_numbers=r['page_numbers'],
            evidence=r['evidence'], parsing_fidelity=None, context_sufficient=None,
            reviewer=None, notes='',
        ) for r in records])
        write_jsonl(self.output / 'response-template.jsonl', [dict(
            request_id=r['request_id'], raw_response=None, status='NOT_RUN', error=None,
            actual_model=None, request_started_at=None, elapsed_seconds=None,
            input_tokens=None, output_tokens=None, cost=None,
        ) for r in requests])
        flag_counts = Counter(f for r in chunks for f in r['chunk_metadata']['flags'])
        manifest = {
            'status': ('PREPARED_WITH_DOCUMENTED_SHORTFALL' if self.reviewed_selection and failures else
                       'PREPARED_PENDING_INPUT_REVIEW' if not failures else 'INCOMPLETE'),
            'scope': 'development_page_subset_no_paid_calls', 'paid_calls': 0, 'failures': failures,
            'chunking_policy': 'structure_first_recursive', 'chunker_comparison': 'cancelled_by_user',
            'chunk_size_tokens': 1024, 'overlap_tokens': 0, 'min_tokens': None,
            'chunker': 'PaperStructuredChunker wrapping Chonkie recursion for long prose',
            'chonkie_version': importlib.metadata.version('chonkie'),
            'chunk_count': len(chunks), 'flag_counts': dict(flag_counts),
            'chunks_per_paper': dict(Counter(r['paper_id'] for r in chunks)),
            'cross_page_chunks': sum(len(r['chunk_metadata']['page_numbers']) > 1 for r in chunks),
            'sampling': ('Source-reviewed development selection, at most two per paper; all chunks retained'
                         if self.reviewed_selection else
                         '2 eligible chunks per paper sorted by seeded chunk hash; all candidates retained'),
            'selection_file': str(self.selection_file) if self.selection_file else None,
            'selection_sha256': sha256(self.selection_file) if self.selection_file else None,
            'selected_chunks': len(records), 'requests_prepared': len(requests),
            'common_generation': COMMON, 'concurrency': 1, 'attempts_per_chunk_per_arm': 1,
            'request_limit': 24, 'maximum_total_output_tokens': len(requests) * COMMON['max_tokens'],
            'currency_budget': None, 'serving_reference': 'a9885c5b9907017b',
            'B_prompt_version': quality.GENERATOR_PROMPT_VERSION,
            'source_scope': 'same six recovered PDFs, physical pages 2 and 3; not whole-paper coverage',
            'notes': ['Raw parsing artifacts unchanged; tables and display equations are never truncated.',
                      'Oversized and known formula-rendering issues are retained and flagged, excluded from sampling.',
                      'Heading metadata does not recover missing earlier sections or pages.',
                      'B legacy 400-unit limit remains; larger evidence can affect SKIP rate and must be reported.',
                      'No PDF parsing, embedding or generation model calls were made by this preparation run.'],
            'artifact_sha256': {p.name: sha256(p) for p in sorted(self.output.glob('*.jsonl'))},
            'source_sha256': {str(p.relative_to(self.root)): sha256(p) for p in [
                Path(__file__),
                self.root / 'extensions/paper-dataflow/paper_dataflow/operators/paper/generate/structured_chunking.py',
                self.root / 'extensions/paper-dataflow/paper_dataflow/operators/paper/generate/preparation.py',
                self.root / 'extensions/paper-dataflow/paper_dataflow/pipelines/round1_prepare.py',
                self.root / 'data/round1/chunking-decision.json',
                self.root / 'data/round1/paper-selection.json',
            ]},
        }
        write_new(self.output / 'manifest.json', manifest)
        return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--selection-file')
    args = parser.parse_args()
    print(json.dumps(Round1RecursivePreparation(args.workspace, args.output, args.selection_file).forward(), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
