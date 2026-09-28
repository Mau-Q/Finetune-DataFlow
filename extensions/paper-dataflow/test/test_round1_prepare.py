"""Checks that preparation preserves the comparison's input and output identities."""
import json
import tempfile
import unittest
from pathlib import Path

from dataflow.operators.text_sft import SFTGeneratorSeed
from paper_dataflow.baseline import quality
from paper_dataflow.pipelines.round1_prepare import (
    CaptureServing, MemoryStorage, block_windows, build_requests, canonical_paper_id, read_jsonl, write_new,
)


def record(evidence='Evidence: method A achieves 85% accuracy.'):
    return {'candidate_id': 'round1-0123a', 'paper_id': 'fixture', 'domain': 'test',
            'evidence': evidence, 'evidence_raw_sha256': quality.sha256_text(evidence)}


class Round1Tests(unittest.TestCase):
    def test_atomic_block_windows_do_not_truncate_large_table(self):
        class Chunker:
            chunk_size = 512
            tokenizer_files = {}
            def _encode(self, text):
                return {'input_ids': list(text)}
        text = 'An intact statement. ' * 5
        table = '<table>' + 'x' * 600 + '</table>'
        page = {'document_id': 'fixture', 'page_number': 2, 'text': text + '\n' + table,
                'blocks': [{'type': 'text', 'content': text.strip(), 'char_start': 0, 'char_end': len(text)},
                           {'type': 'table', 'content': table, 'char_start': len(text) + 1,
                            'char_end': len(text) + 1 + len(table)}]}
        rows = block_windows({'source_page': page}, Chunker())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['raw_chunk'], text)
        self.assertNotIn('<table>', rows[0]['raw_chunk'])

    def test_float_inferred_paper_id_uses_verified_nested_manifest(self):
        row = {'paper_id': 2603.0425, 'source': {'paper_id': '2603.04250'}}
        canonical_paper_id(row, '2603.04250')
        self.assertEqual(row['paper_id'], '2603.04250')
        with self.assertRaisesRegex(ValueError, 'identity'):
            canonical_paper_id(row, '2603.04251')

    def test_same_evidence_and_model_both_arms(self):
        row = record('Evidence with Unicode separator\u2028and a number 85%.')
        req = {r['arm']: r for r in build_requests(row)}
        self.assertEqual(set(req), {'A', 'B'})
        self.assertEqual(req['A']['evidence_raw_sha256'], req['B']['evidence_raw_sha256'])
        self.assertIn(row['evidence'], req['A']['payload']['messages'][1]['content'])
        b_user = json.loads(req['B']['payload']['messages'][1]['content'])
        self.assertEqual(b_user['paper_evidence'], row['evidence'])
        for key in ('model', 'temperature', 'max_tokens', 'response_format', 'enable_thinking'):
            self.assertEqual(req['A']['payload'][key], req['B']['payload'][key])
        self.assertEqual(req['B']['payload']['messages'], quality.generator_messages(row))

    def test_modified_or_empty_evidence_rejected_before_capture(self):
        bad = record()
        bad['evidence'] += 'changed'
        with self.assertRaisesRegex(ValueError, 'identity'):
            build_requests(bad)
        with self.assertRaisesRegex(ValueError, 'Empty'):
            build_requests(record(' '))

    def test_long_evidence_is_not_removed_by_legacy_gate(self):
        self.assertEqual(len(build_requests(record('word ' * 600))), 2)

    def test_jsonl_unicode_separator_keeps_row_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'rows.jsonl'
            p.write_text(json.dumps({'text': 'a\u2028b'}, ensure_ascii=False) + '\n')
            self.assertEqual(read_jsonl(p), [{'text': 'a\u2028b'}])

    def test_artifact_overwrite_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'artifact.json'
            write_new(p, {'first': True})
            with self.assertRaises(FileExistsError):
                write_new(p, {'first': False})
            self.assertEqual(json.loads(p.read_text()), {'first': True})

    def test_native_official_operator_failure_can_drop_row(self):
        class Responses(CaptureServing):
            def generate_from_input(self, inputs, **kwargs):
                return ['invalid', '{"instruction":"问题","output":"回答"}']
        storage = MemoryStorage([{'raw_content': 'first', 'id': 1}, {'raw_content': 'second', 'id': 2}])
        SFTGeneratorSeed(Responses(), custom_prompt='中文').run(storage)
        self.assertEqual(storage.frame['raw_content'].tolist(), ['second'])
        self.assertNotIn('id', storage.frame.columns)
        # The external prepared request ledger must retain the first input as well.
        self.assertEqual(len(build_requests(record('first'))), 2)


if __name__ == '__main__':
    unittest.main()
