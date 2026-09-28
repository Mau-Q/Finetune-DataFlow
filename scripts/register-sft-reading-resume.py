"""Register a one-chunk continuation from the verified LIMA cleaning cache.

Registration performs no PDF parsing and makes no model calls.
"""

import hashlib
import json
import urllib.request
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8000/api/v1"
CACHE = ROOT / (
    "repos/dataflow-webui/backend/cache_local/9fc165914038_output/"
    "dataflow_cache_step_step4.jsonl"
)
CACHE_SHA256 = "d64f4135103c11050be26cc57e8b0464c86d24152e7bd3a7cf5d6b6b28c08be8"
CHUNK_INDEX = 22
SOURCE = ROOT / "data/sft-reading-13/lima-checkpoint-one.jsonl"
PARENT_CONFIG = ROOT / "pipelines/sft-reading-lima-one.webui.json"
CONFIG_FILE = ROOT / "pipelines/sft-reading-lima-resume-one.webui.json"
STATE_FILE = ROOT / "pipelines/sft-reading-lima-resume-one.registration.json"
PIPELINE_NAME = "SFT 阅读论文单块接续 · LIMA #22"
DATASET_NAME = "SFT 阅读论文单块接续 · LIMA 清洗缓存 #22"


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
        raise ValueError("Cleaning cache changed; refusing to resume from an unknown snapshot")
    rows = [json.loads(line) for line in CACHE.read_text().splitlines() if line.strip()]
    if len(rows) != 33 or not {"raw_chunk", "cleaned_chunk"}.issubset(rows[CHUNK_INDEX]):
        raise ValueError("Unexpected cleaning-cache schema or row count")
    SOURCE.write_text(json.dumps(rows[CHUNK_INDEX], ensure_ascii=False) + "\n")

    datasets = [item for item in api("/datasets/") if item.get("root") == str(SOURCE)]
    if len(datasets) > 1:
        raise ValueError("Several datasets point to the checkpoint input")
    dataset = datasets[0] if datasets else api("/datasets/", {
        "name": DATASET_NAME, "root": str(SOURCE), "pipeline": "SFTReadingResumeOne",
        "meta": {"source_task_id": "9fc165914038", "cache_sha256": CACHE_SHA256,
                 "chunk_index": str(CHUNK_INDEX)},
    })
    columns = api(f"/datasets/columns/{dataset['id']}")
    if not {"raw_chunk", "cleaned_chunk"}.issubset(set(columns)):
        raise ValueError(f"Unexpected dataset columns: {columns}")

    parent = json.loads(PARENT_CONFIG.read_text())
    config = deepcopy(parent["config"])
    config["input_dataset"]["id"] = dataset["id"]
    config["file_path"] = str(CONFIG_FILE)
    config["operators"] = config["operators"][4:]
    if config["operators"][0]["name"] != "Text2MultiHopQAGenerator":
        raise ValueError("Continuation must begin at the QA generator")
    for index, op in enumerate(config["operators"]):
        op["location"] = [340 + index * 310, 160]

    serving_ids = {item["id"] for item in api("/serving/")}
    for op in config["operators"]:
        for param in op["params"]["init"]:
            if param["name"] == "llm_serving" and param["value"] not in serving_ids:
                raise ValueError(f"Missing serving for {op['name']}")

    validation = api("/pipelines/validate", config)
    if not validation.get("valid"):
        raise RuntimeError(json.dumps(validation.get("errors"), ensure_ascii=False))
    payload = {"name": PIPELINE_NAME, "config": config,
               "tags": ["paper", "sft", "checkpoint", "one-chunk", "not-executed"]}
    existing = [item for item in api("/pipelines/") if item.get("name") == PIPELINE_NAME]
    if len(existing) > 1:
        raise ValueError("Several pipelines have the checkpoint name")
    if existing:
        pipeline = existing[0]
        if pipeline["config"]["input_dataset"]["id"] != dataset["id"]:
            raise ValueError("An existing checkpoint pipeline points to another dataset")
    else:
        pipeline = api("/pipelines/", payload)

    CONFIG_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    state = {"pipeline_id": pipeline["id"], "dataset_id": dataset["id"],
             "source_task_id": "9fc165914038", "cache_sha256": CACHE_SHA256,
             "chunk_index": CHUNK_INDEX, "operator_count": len(config["operators"]),
             "validation": validation, "status": "registered_not_executed"}
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"pipeline_id": pipeline["id"], "dataset_id": dataset["id"],
                      "operators": len(config["operators"]),
                      "valid": validation["valid"], "status": state["status"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
