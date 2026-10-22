"""Evidence contracts, using synthetic text and the installed local tokenizer."""

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from paper_dataflow.operators.paper.generate.preparation import MinerU4PDFParser, MinerU4PageExtractor, PaperEvidenceChunker, sha256

ROOT = Path(__file__).resolve().parents[3]


class MemoryStorage:
    def __init__(self, rows):
        self.frame = pd.DataFrame(rows)

    def read(self, output_type):
        return self.frame.copy()

    def write(self, frame):
        self.frame = frame


class AdvancedParserTests(unittest.TestCase):
    def test_advanced_command_and_archive_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / 'mineru.sh'
            script.write_text('#!/bin/sh\n')
            source = root / 'source.pdf'
            source.write_bytes(b'%PDF-1.4 synthetic parser transport fixture')
            storage = MemoryStorage([{'source_path': str(source)}])
            def parse(command, **kwargs):
                self.assertEqual(command[command.index('--tier') + 1], 'advanced')
                archive = Path(command[command.index('-o') + 1])
                with zipfile.ZipFile(archive, 'w') as bundle:
                    bundle.writestr('structured_content.json', json.dumps({
                        'metadata': {'producer': {'version': '4.0.12'}},
                        'is_full_document': True,
                        'pages': [{'page_idx': 0, 'blocks': []}],
                    }))
            parser = MinerU4PDFParser(str(script), str(root / 'parsed'), tier='advanced')
            with patch('paper_dataflow.operators.paper.generate.preparation.subprocess.run', side_effect=parse):
                parser.run(storage)
            record = storage.frame.iloc[0]['parsed_document']
            self.assertEqual(record['tier'], 'advanced')
            self.assertEqual(record['document_id'], sha256(source))
            self.assertEqual(record['archive_sha256'], sha256(record['archive_path']))
            self.assertEqual(json.loads((Path(record['archive_path']).parent / 'manifest.json').read_text()), record)


@unittest.skipUnless((ROOT / 'models/tokenizers/Qwen2.5-7B-Instruct/tokenizer.json').is_file(),
                     'Optional historical Qwen tokenizer is not installed; no automatic download')
class EvidenceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chunker = PaperEvidenceChunker(str(ROOT / "models/tokenizers/Qwen2.5-7B-Instruct"), 32, 8)

    def test_unicode_coverage_and_token_budget(self):
        text = "  论文原文😀 café e\u0301\n| 数据 | 数值 |\n|---|---|\n|样本|123|\n" * 40 + "  "
        chunks = list(self.chunker.chunks(text))
        coverage = set()
        previous_start = -1
        for start, end, count in chunks:
            self.assertGreater(start, previous_start)
            self.assertLessEqual(count, 32)
            self.assertEqual(count, len(self.chunker._encode(text[start:end])["input_ids"]))
            coverage.update(range(start, end))
            previous_start = start
        self.assertEqual(coverage, set(range(len(text))))
        self.assertGreater(len(chunks), 1)

    def test_page_and_table_provenance_with_empty_page(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "source.zip"
            document = {"pages": [
                {"page_idx": 0, "blocks": [{"type": "table", "content": "| A | B |\n|---|---|\n|1|2|", "bbox": [0.1, 0.2, 0.8, 0.9], "captions": ["表 1"], "footnotes": ["注：示例"]}]},
                {"page_idx": 1, "blocks": []},
            ]}
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("structured_content.json", json.dumps(document))
            storage = MemoryStorage([{"parsed_document": {"archive_path": str(archive), "archive_sha256": sha256(archive), "document_id": "fixture"}}])
            MinerU4PageExtractor().run(storage)
            self.assertEqual(storage.frame["source_page"].iloc[1]["status"], "empty_page")
            self.chunker.run(storage)
            for row in storage.frame.to_dict("records"):
                meta, page = row["chunk_metadata"], row["source_page"]
                self.assertEqual(row["raw_chunk"], page["text"][meta["char_start"]:meta["char_end"]])
                self.assertEqual(meta["page_number"], page["page_number"])
            blank = storage.frame.iloc[-1]["chunk_metadata"]
            self.assertFalse(blank["eligible_for_qa"])
            self.assertIn("注：示例", storage.frame.iloc[0]["source_page"]["text"])

    def test_modified_archive_rejected(self):
        with tempfile.NamedTemporaryFile() as temporary:
            storage = MemoryStorage([{"parsed_document": {"archive_path": temporary.name, "archive_sha256": "wrong"}}])
            with self.assertRaisesRegex(ValueError, "archive changed"):
                MinerU4PageExtractor().run(storage)

    def test_structured_caption_preserves_text_and_coordinates(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "source.zip"
            caption = {"content": "Table 1: accuracy under condition A", "bbox": [0.1, 0.2, 0.8, 0.3]}
            document = {"pages": [{"page_idx": 1, "blocks": [
                {"type": "table", "content": "| accuracy | 85% |", "captions": [caption],
                 "footnotes": [{"content": "Only on dataset A", "bbox": [0.1, 0.8, 0.8, 0.9]}]}
            ]}]}
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("structured_content.json", json.dumps(document))
            storage = MemoryStorage([{"parsed_document": {"archive_path": str(archive),
                "archive_sha256": sha256(archive), "document_id": "fixture"}}])
            MinerU4PageExtractor().run(storage)
            page = storage.frame.iloc[0]["source_page"]
            self.assertEqual(page["page_number"], 2)
            self.assertIn(caption["content"], page["text"])
            self.assertIn("Only on dataset A", page["text"])
            self.assertEqual(page["blocks"][0]["captions"][0], caption)

    def test_missing_field_and_overwrite_rejected(self):
        with self.assertRaisesRegex(ValueError, "available columns"):
            self.chunker.run(MemoryStorage([{"unexpected": "x"}]))
        with self.assertRaisesRegex(ValueError, "new and distinct"):
            self.chunker.run(MemoryStorage([{"source_page": {}, "raw_chunk": "original"}]))

    def test_invalid_overlap_rejected(self):
        with self.assertRaisesRegex(ValueError, "chunk_overlap"):
            PaperEvidenceChunker(str(ROOT / "models/tokenizers/Qwen2.5-7B-Instruct"), 32, 32)


if __name__ == "__main__":
    unittest.main()
