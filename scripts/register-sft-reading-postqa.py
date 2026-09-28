"""Register the no-model QA transformation check from the saved QA cache."""

import hashlib
import json
import urllib.request
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8000/api/v1"
SOURCE = ROOT / (
    "repos/dataflow-webui/backend/cache_local/382eb1ca7fad_output/"
    "dataflow_cache_step_step1.jsonl"
)
SOURCE_SHA256 = "a7fcc784d4cfec1a87481fa2ee840884ba488a6852e377754da3c29114444763"
PARENT = ROOT / "pipelines/sft-reading-lima-resume-one.webui.json"
CONFIG_FILE = ROOT / "pipelines/sft-reading-lima-postqa.webui.json"
STATE_FILE = ROOT / "pipelines/sft-reading-lima-postqa.registration.json"
PIPELINE_NAME = "SFT 阅读论文 QA 转换验证 · LIMA #22"


def api(path, body=None):
    payload = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    req = urllib.request.Request(
        BASE + path, data=payload, method="POST" if body is not None else "GET",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        result = json.load(response)
    if result.get("success") is False:
        raise RuntimeError(result.get("message", "WebUI API failed"))
    return result.get("data", result)


def main():
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("QA checkpoint changed; refusing an unknown input")
    rows = [json.loads(line) for line in SOURCE.read_text().splitlines() if line.strip()]
    if len(rows) != 1 or len(rows[0].get("QA_pairs", [])) != 2:
        raise ValueError("Expected one chunk with two QA pairs")

    datasets = [d for d in api("/datasets/") if d.get("root") == str(SOURCE)]
    if len(datasets) > 1:
        raise ValueError("Several datasets point to this QA checkpoint")
    dataset = datasets[0] if datasets else api("/datasets/", {
        "name": "SFT 阅读论文 · LIMA #22 QA 缓存",
        "root": str(SOURCE), "pipeline": "SFTReadingPostQA",
        "meta": {"source_task_id": "382eb1ca7fad", "sha256": SOURCE_SHA256},
    })
    if "QA_pairs" not in api(f"/datasets/columns/{dataset['id']}"):
        raise ValueError("QA_pairs column is missing")

    config = deepcopy(json.loads(PARENT.read_text())["config"])
    config["file_path"] = str(CONFIG_FILE)
    config["input_dataset"]["id"] = dataset["id"]
    config["operators"] = config["operators"][1:4]
    if [op["name"] for op in config["operators"]] != [
        "PandasOperator", "PandasOperator", "GeneralFilter"
    ]:
        raise ValueError("Unexpected deterministic operator chain")
    for index, op in enumerate(config["operators"]):
        op["location"] = [340 + index * 310, 160]
    validation = api("/pipelines/validate", config)
    if not validation.get("valid"):
        raise RuntimeError(json.dumps(validation.get("errors"), ensure_ascii=False))

    payload = {"name": PIPELINE_NAME, "config": config,
               "tags": ["paper", "sft", "checkpoint", "no-model"]}
    existing = [p for p in api("/pipelines/") if p.get("name") == PIPELINE_NAME]
    if len(existing) > 1:
        raise ValueError("Several pipelines have the checkpoint name")
    pipeline = existing[0] if existing else api("/pipelines/", payload)
    if pipeline["config"]["input_dataset"]["id"] != dataset["id"]:
        raise ValueError("Existing pipeline points to a different QA checkpoint")

    CONFIG_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    state = {"pipeline_id": pipeline["id"], "dataset_id": dataset["id"],
             "source_task_id": "382eb1ca7fad", "source_sha256": SOURCE_SHA256,
             "validation": validation, "status": "registered_not_executed"}
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"pipeline_id": pipeline["id"], "dataset_id": dataset["id"],
                      "valid": validation["valid"], "status": state["status"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
