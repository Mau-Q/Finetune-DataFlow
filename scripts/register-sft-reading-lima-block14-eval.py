"""Register a fresh-runtime scoring continuation for LIMA block 14."""

import hashlib
import json
import urllib.request
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8000/api/v1"
SOURCE = ROOT / (
    "repos/dataflow-webui/backend/cache_local/02ffb4e53346_output/"
    "dataflow_cache_step_step5.jsonl"
)
SOURCE_SHA256 = "10bb623609e8cd066c25d70dae2e38f91859ef89ea04f6afb420747635914eab"
PARENT = ROOT / "pipelines/sft-reading-lima-block14.webui.json"
CONFIG_FILE = ROOT / "pipelines/sft-reading-lima-block14-eval.webui.json"
STATE_FILE = ROOT / "pipelines/sft-reading-lima-block14-eval.registration.json"
NAME = "SFT 阅读论文评分接续 · LIMA #14"


def api(path, body=None, method=None):
    payload = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    req = urllib.request.Request(
        BASE + path, data=payload, method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        result = json.load(response)
    if result.get("success") is False:
        raise RuntimeError(result.get("message", "WebUI API failed"))
    return result.get("data", result)


def main():
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("QA checkpoint identity changed")
    rows = [json.loads(line) for line in SOURCE.read_text().splitlines() if line.strip()]
    if len(rows) != 2 or not all(
        {"question", "answer", "raw_chunk"}.issubset(row) for row in rows
    ):
        raise ValueError("Unexpected QA checkpoint")

    datasets = [d for d in api("/datasets/") if d.get("root") == str(SOURCE)]
    if len(datasets) > 1:
        raise ValueError("Duplicate checkpoint datasets")
    dataset = datasets[0] if datasets else api("/datasets/", {
        "name": "SFT 阅读论文 · LIMA #14 双 QA 运行缓存",
        "root": str(SOURCE), "pipeline": "SFTReadingBlock14Eval",
        "meta": {"source_task_id": "02ffb4e53346", "sha256": SOURCE_SHA256},
    })
    config = deepcopy(json.loads(PARENT.read_text())["config"])
    config["file_path"] = str(CONFIG_FILE)
    config["input_dataset"]["id"] = dataset["id"]
    config["operators"] = config["operators"][5:]
    expected = ["Text2QASampleEvaluator", "AlpagasusSampleEvaluator",
                "GeneralFilter", "HashDeduplicateFilter", "PandasOperator"]
    if [op["name"] for op in config["operators"]] != expected:
        raise ValueError("Unexpected evaluation chain")
    for index, op in enumerate(config["operators"]):
        op["location"] = [340 + index * 310, 160]
    serving_ids = {item["id"] for item in api("/serving/")}
    for op in config["operators"]:
        for param in op["params"]["init"]:
            if param["name"] == "llm_serving" and param["value"] not in serving_ids:
                raise ValueError(f"Missing serving for {op['name']}")
    validation = api("/pipelines/validate", config)
    if not validation.get("valid"):
        raise RuntimeError("Evaluation pipeline validation failed")

    payload = {"name": NAME, "config": config,
               "tags": ["paper", "sft", "checkpoint", "parser-activation-check"]}
    existing = [p for p in api("/pipelines/") if p.get("name") == NAME]
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
        "source_task_id": "02ffb4e53346", "source_sha256": SOURCE_SHA256,
        "operator_count": len(config["operators"]), "validation": validation,
        "status": "registered_not_executed",
    }, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"pipeline_id": pipeline["id"], "dataset_id": dataset["id"],
                      "operators": len(config["operators"]),
                      "valid": validation["valid"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
