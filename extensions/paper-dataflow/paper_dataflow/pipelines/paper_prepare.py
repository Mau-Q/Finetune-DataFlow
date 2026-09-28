"""Runnable local preparation pipeline; no generation API calls."""

import argparse
from pathlib import Path

from dataflow.utils.storage import FileStorage
from paper_dataflow.operators.paper.generate.preparation import (
    MinerU4PDFParser,
    MinerU4PageExtractor,
    PaperEvidenceChunker,
)


class PaperPreparePipeline:
    def __init__(self, workspace: str, input_path: str, output_path: str):
        root = Path(workspace).resolve()
        self.storage = FileStorage(first_entry_file_name=input_path, cache_path=output_path, cache_type="jsonl")
        self.op1 = MinerU4PDFParser(str(root / "scripts/mineru.sh"), str(root / "outputs/paper-parsing"))
        self.op2 = MinerU4PageExtractor()
        self.op3 = PaperEvidenceChunker(str(root / "models/tokenizers/Qwen2.5-7B-Instruct"))

    def forward(self):
        self.op1.run(self.storage.step(), input_key="source_path", output_key="parsed_document")
        self.op2.run(self.storage.step(), input_key="parsed_document", output_key="source_page")
        self.op3.run(self.storage.step(), input_key="source_page", output_key="raw_chunk", output_meta_key="chunk_metadata")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    PaperPreparePipeline(args.workspace, args.input, args.output).forward()
