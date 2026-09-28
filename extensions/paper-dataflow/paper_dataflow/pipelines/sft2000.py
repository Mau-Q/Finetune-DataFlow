"""Frozen SFT-2000 baseline, with registered generator/verifier serving objects."""
from pathlib import Path
from dataflow.utils.storage import FileStorage
from paper_dataflow.operators.paper.generate.sft2000 import SFT2000Generator, SFT2000Verifier, SFT2000Exporter


class SFT2000Pipeline:
    def __init__(self, workspace, input_path, output_path, generator_serving, verifier_serving, max_records=3):
        root = Path(workspace).resolve()
        self.storage = FileStorage(first_entry_file_name=input_path, cache_path=output_path, cache_type='jsonl')
        self.generator = SFT2000Generator(generator_serving, str(root / 'models/tokenizers/Qwen3.6-27B-6a9e13bd'),
                                          str(root / 'outputs/sft2000-runs'), max_records)
        self.verifier = SFT2000Verifier(verifier_serving)
        self.exporter = SFT2000Exporter(str(root / 'outputs/sft2000-exports'))

    def forward(self):
        self.generator.run(self.storage.step(), input_key='evidence_record', output_key='generation_result')
        self.verifier.run(self.storage.step(), input_key='generation_result', input_evidence_key='evidence_record', output_key='verification_result')
        self.exporter.run(self.storage.step(), input_key='verification_result', input_evidence_key='evidence_record', output_key='export_status')
