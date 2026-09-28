"""Local, API-free check of editable DataFlow and the downloaded tokenizer."""
from pathlib import Path
import json

from dataflow.operators.general_text import HashDeduplicateFilter
from dataflow.utils.storage import FileStorage
from transformers import AutoTokenizer

root = Path(__file__).resolve().parents[1]
out = root / "outputs" / "smoke-dataflow"
out.mkdir(parents=True, exist_ok=True)
source = out / "input.jsonl"
rows = [{"text": "DataFlow local installation check."},
        {"text": "DataFlow local installation check."},
        {"text": "本地解析与数据清洗。"}]
source.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
storage = FileStorage(first_entry_file_name=str(source), cache_path=str(out), cache_type="jsonl")
HashDeduplicateFilter(hash_func="sha256").run(storage.step(), input_key="text")
result = storage.step().read("dataframe")
assert result["text"].tolist() == [rows[0]["text"], rows[2]["text"]]
tokenizer = AutoTokenizer.from_pretrained(root / "models/tokenizers/Qwen2.5-7B-Instruct", local_files_only=True)
tokens = tokenizer.encode(rows[2]["text"])
assert tokens and tokenizer.decode(tokens) == rows[2]["text"]
print(json.dumps({"dedup_input": 3, "dedup_output": len(result), "tokenizer_tokens": len(tokens), "status": "PASS"}))
