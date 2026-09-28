"""Register/update the local demo pipeline via WebUI API, after validation.

Does not execute it or replace an unsaved canvas. Pass --render explicitly to
push the saved pipeline to connected WebUI clients. No model/API key is needed.
"""

import argparse
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "pipelines/paper-prepare.registration.json"
BASE = "http://127.0.0.1:8000/api/v1"


def api(path, body=None, method=None):
    payload = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    request = urllib.request.Request(BASE + path, data=payload, method=method,
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        result = json.load(response)
    if result.get("success") is False:
        raise RuntimeError(result)
    return result.get("data", result)


def operator(name, init, run, x):
    return {"name": name, "location": [x, 160], "params": {
        "init": [{"name": key, "value": value} for key, value in init.items()],
        "run": [{"name": key, "value": value} for key, value in run.items()],
    }}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--render", action="store_true")
    args = parser.parse_args()
    source = ROOT / "data/paper-demo/documents.jsonl"
    source.parent.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        source.write_text(json.dumps({"source_path": str(ROOT / "data/smoke/installation-check.pdf"),
                                      "is_demo": True, "dataset_note": "Synthetic installation fixture; not a real paper."}) + "\n")
    dataset = api("/datasets/", {"name": "论文准备 · 演示 PDF 清单", "root": str(source), "pipeline": "PaperPrepare",
                                "meta": {"scope": "synthetic demonstration"}})
    columns = api(f"/datasets/columns/{dataset['id']}")
    print("Dataset columns:", columns)
    config = {
        "file_path": str(ROOT / "extensions/paper-dataflow/paper_dataflow/pipelines/paper_prepare.py"),
        "input_dataset": {"id": dataset["id"], "location": [30, 160]},
        "operators": [
            operator("MinerU4PDFParser", {"mineru_script": str(ROOT / "scripts/mineru.sh"), "output_dir": str(ROOT / "outputs/paper-parsing"), "tier": "standard", "timeout_seconds": 900},
                     {"input_key": "source_path", "output_key": "parsed_document"}, 350),
            operator("MinerU4PageExtractor", {}, {"input_key": "parsed_document", "output_key": "source_page"}, 670),
            operator("PaperEvidenceChunker", {"tokenizer_path": str(ROOT / "models/tokenizers/Qwen2.5-7B-Instruct"), "chunk_size": 512, "chunk_overlap": 64},
                     {"input_key": "source_page", "output_key": "raw_chunk", "output_meta_key": "chunk_metadata"}, 990),
        ],
    }
    validation = api("/pipelines/validate", config)
    if not validation["valid"]:
        raise RuntimeError(validation)
    payload = {"name": "论文 PDF → 证据分块（演示，无 LLM）", "config": config, "tags": ["paper", "local", "demo", "preparation"]}
    STATE.parent.mkdir(parents=True, exist_ok=True)
    if STATE.exists():
        existing = json.loads(STATE.read_text())
        pipeline = api(f"/pipelines/{existing['pipeline_id']}", payload, "PUT")
    else:
        pipeline = api("/pipelines/", payload)
    registration = {"pipeline_id": pipeline["id"], "dataset_id": dataset["id"], "validation": validation}
    STATE.write_text(json.dumps(registration, ensure_ascii=False, indent=2) + "\n")
    (STATE.parent / "paper-prepare.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(registration, ensure_ascii=False, indent=2))
    if args.render:
        print("Render:", api("/agent/render", {"pipeline_id": pipeline["id"]}))


if __name__ == "__main__":
    main()
