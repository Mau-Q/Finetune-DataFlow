"""Register a bounded LIMA raw-chunk run through cleaning, QA, and export."""

import hashlib
import json
import urllib.request
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8000/api/v1"
CACHE = ROOT / (
    "repos/dataflow-webui/backend/cache_local/9fc165914038_output/"
    "dataflow_cache_step_step3.jsonl"
)
CACHE_SHA256 = "1e3244fce54c3e4e7ffd5dda93daffd476ef58b25dec5d2d5c5b266d946c156d"
ROW_INDEX = 14
SOURCE = ROOT / "data/sft-reading-13/lima-block14-raw.jsonl"
PARENT = ROOT / "pipelines/sft-reading-lima-one.webui.json"
CONFIG_FILE = ROOT / "pipelines/sft-reading-lima-block14.webui.json"
STATE_FILE = ROOT / "pipelines/sft-reading-lima-block14.registration.json"
PIPELINE_NAME = "SFT 阅读论文单块全程 · LIMA #14"


def api(path, body=None, method=None):
    payload = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    request = urllib.request.Request(
        BASE + path, data=payload, method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.load(response)
    if result.get("success") is False:
        raise RuntimeError(result.get("message", "WebUI API failed"))
    return result.get("data", result)


def main():
    if hashlib.sha256(CACHE.read_bytes()).hexdigest() != CACHE_SHA256:
        raise ValueError("Raw chunk cache changed")
    rows = [json.loads(line) for line in CACHE.read_text().splitlines() if line.strip()]
    if len(rows) != 33:
        raise ValueError("Unexpected chunk count")
    row = rows[ROW_INDEX]
    if (row.get("source_page", {}).get("page_number") != 6
            or row.get("chunk_metadata", {}).get("chunk_index") != 1
            or not row.get("raw_chunk") or "cleaned_chunk" in row):
        raise ValueError("Unexpected raw chunk identity or schema")
    source_content = json.dumps(row, ensure_ascii=False) + "\n"
    if SOURCE.exists() and SOURCE.read_text() != source_content:
        raise ValueError("Existing single-chunk input differs")
    SOURCE.write_text(source_content)

    datasets = [d for d in api("/datasets/") if d.get("root") == str(SOURCE)]
    if len(datasets) > 1:
        raise ValueError("Duplicate datasets for the input")
    dataset = datasets[0] if datasets else api("/datasets/", {
        "name": "SFT 阅读论文 · LIMA 第 6 页原始块 #14",
        "root": str(SOURCE), "pipeline": "SFTReadingBlock14",
        "meta": {"source_task_id": "9fc165914038", "row_index": str(ROW_INDEX),
                 "cache_sha256": CACHE_SHA256},
    })
    columns = set(api(f"/datasets/columns/{dataset['id']}"))
    if not {"source", "source_page", "raw_chunk", "chunk_metadata"}.issubset(columns):
        raise ValueError("Single-chunk dataset has missing columns")

    config = deepcopy(json.loads(PARENT.read_text())["config"])
    config["file_path"] = str(CONFIG_FILE)
    config["input_dataset"]["id"] = dataset["id"]
    config["operators"] = config["operators"][3:]
    if [op["name"] for op in config["operators"][:2]] != [
        "KBCTextCleaner", "Text2MultiHopQAGenerator"
    ] or config["operators"][-1]["name"] != "PandasOperator":
        raise ValueError("Unexpected pipeline operator chain")
    for index, op in enumerate(config["operators"]):
        op["location"] = [340 + index * 310, 160]
    serving_ids = {item["id"] for item in api("/serving/")}
    for op in config["operators"]:
        for param in op["params"]["init"]:
            if param["name"] == "llm_serving" and param["value"] not in serving_ids:
                raise ValueError(f"Missing serving for {op['name']}")

    validation = api("/pipelines/validate", config)
    if not validation.get("valid"):
        raise RuntimeError("Pipeline validation failed")
    payload = {"name": PIPELINE_NAME, "config": config,
               "tags": ["paper", "sft", "one-chunk", "bounded-validation"]}
    existing = [p for p in api("/pipelines/") if p.get("name") == PIPELINE_NAME]
    if len(existing) > 1:
        raise ValueError("Duplicate named pipelines")
    if existing:
        pipeline = existing[0]
        if pipeline["config"]["input_dataset"]["id"] != dataset["id"]:
            raise ValueError("Existing pipeline points to a different dataset")
        pipeline = api(f"/pipelines/{pipeline['id']}", payload, "PUT")
    else:
        pipeline = api("/pipelines/", payload)

    CONFIG_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    STATE_FILE.write_text(json.dumps({
        "pipeline_id": pipeline["id"], "dataset_id": dataset["id"],
        "source_task_id": "9fc165914038", "source_cache_sha256": CACHE_SHA256,
        "input_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "row_index": ROW_INDEX, "source_page": 6,
        "operator_count": len(config["operators"]), "validation": validation,
        "status": "registered_not_executed",
    }, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"pipeline_id": pipeline["id"], "dataset_id": dataset["id"],
                      "operators": len(config["operators"]),
                      "valid": validation["valid"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
