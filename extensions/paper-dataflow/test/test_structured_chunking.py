import unittest
from pathlib import Path

from paper_dataflow.operators.paper.generate.structured_chunking import PaperStructuredChunker
from paper_dataflow.pipelines.round1_prepare import MemoryStorage


ROOT = Path(__file__).resolve().parents[3]


def page(number, blocks, document='fixture'):
    text, result = '', []
    for i, (kind, content) in enumerate(blocks):
        if text:
            text += '\n'
        start = len(text)
        text += content
        result.append(dict(type=kind, content=content, block_id=f'p{number}-b{i}', bbox=[],
                           char_start=start, char_end=len(text)))
    return {'source_page': dict(document_id=document, page_number=number, text=text, blocks=result)}


class StructuredChunkingTests(unittest.TestCase):
    def run_chunker(self, source, size=128):
        op = PaperStructuredChunker(str(ROOT / 'models/tokenizers/Qwen2.5-7B-Instruct'), size)
        storage = MemoryStorage(source)
        op.run(storage)
        rows = storage.frame.to_dict('records')
        for row in rows:
            meta, text = row['chunk_metadata'], row['raw_chunk']
            self.assertEqual(meta['token_count'], op.count(text))
            for span in meta['source_segments']:
                original = next(r['source_page'] for r in source if r['source_page']['page_number'] == span['page_number'])
                self.assertEqual(text[span['chunk_char_start']:span['chunk_char_end']],
                                 original['text'][span['char_start']:span['char_end']])
        return rows, op

    def test_cross_page_chinese_lowercase_and_no_minimum_filter(self):
        rows, op = self.run_chunker([page(2, [('text', '中文句子，跨页继续')]),
                                     page(3, [('header', 'ignore'), ('text', 'lowercase continuation。')])])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['chunk_metadata']['page_numbers'], [2, 3])
        self.assertTrue(rows[0]['chunk_metadata']['eligible_for_qa'])
        self.assertNotIn('ignore', rows[0]['raw_chunk'])
        self.assertEqual(len(op.exclusions), 1)

    def test_real_mineru_heading_and_missing_page_are_boundaries(self):
        rows, _ = self.run_chunker([page(2, [('text', 'One.'), ('paragraph_title', 'Method'), ('text', 'Two.')]),
                                    page(4, [('text', 'Three.')])])
        self.assertEqual([r['raw_chunk'] for r in rows], ['One.', 'Method\nTwo.', 'Three.'])

    def test_figure_does_not_break_cross_page_prose_continuation(self):
        rows, op = self.run_chunker([page(2, [('text', 'An unfinished')]),
                                     page(3, [('image', 'Figure caption.'), ('text', 'sentence ends here.')])])
        self.assertEqual(rows[0]['raw_chunk'], 'An unfinished\nsentence ends here.')
        self.assertEqual(len(rows), 1)
        self.assertEqual(op.exclusions[0]['reason'], 'not_text_only_evidence')

    def test_oversized_table_and_equation_are_not_cut(self):
        table, equation = '<table>' + 'cell ' * 160 + '</table>', '$$' + 'x + ' * 160 + '$$'
        rows, _ = self.run_chunker([page(2, [('table', table), ('equation', equation)])], 64)
        self.assertEqual([r['raw_chunk'] for r in rows], [table, equation])
        self.assertTrue(all('oversize_preserved' in r['chunk_metadata']['flags'] for r in rows))

    def test_recursive_prose_preserves_repeated_sentences_and_offsets(self):
        text = 'A repeated sentence has several important words. ' * 80
        rows, _ = self.run_chunker([page(2, [('text', text)])], 64)
        self.assertGreater(len(rows), 1)
        self.assertEqual(''.join(r['raw_chunk'] for r in rows), text)
        self.assertTrue(all(r['chunk_metadata']['token_count'] <= 64 for r in rows))

    def test_indivisible_long_sentence_and_known_formula_are_flagged(self):
        text = 'long ' * 100
        rows, _ = self.run_chunker([page(2, [('text', text), ('paragraph_title', 'Settings'),
                                               ('text', r'Rate $10^{\tilde { - }4}$ is reported.')])], 64)
        self.assertEqual(rows[0]['raw_chunk'], text)
        self.assertIn('oversize_preserved', rows[0]['chunk_metadata']['flags'])
        self.assertIn('formula_rendering_review', rows[-1]['chunk_metadata']['flags'])

    def test_invalid_source_offsets_fail_closed(self):
        row = page(2, [('text', 'original')])
        row['source_page']['blocks'][0]['content'] = 'changed'
        with self.assertRaisesRegex(ValueError, 'source'):
            self.run_chunker([row])


if __name__ == '__main__':
    unittest.main()
