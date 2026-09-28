"""Register the two-QA evaluation continuation from a verified checkpoint."""

import hashlib
import json
import sys
import urllib.request
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8000/api/v1"
if sys.argv[1:] not in ([], ["--finalize"]):
    raise SystemExit("Usage: register-sft-reading-eval.py [--finalize]")
FINALIZE = sys.argv[1:] == ["--finalize"]
SOURCE = ROOT / (
    "repos/dataflow-webui/backend/cache_local/5879b99d0e3c_output/"
    "dataflow_cache_step_step2.jsonl" if FINALIZE else
    "repos/dataflow-webui/backend/cache_local/b5f5508a6c18_output/"
    "dataflow_cache_step_step3.jsonl"
)
SOURCE_SHA256 = (
    "e9ff86524b84251aed9c341e625f3d8a6db9fdde4e34bbcf6d7a4ce4c4ced0e5"
    if FINALIZE else "a18133e1b830e7e74cbb81fcab32cb0cbd4d80487f518a1e00323d3c78dc922a"
)
PARENT = ROOT / "pipelines/sft-reading-lima-resume-one.webui.json"
CONFIG_FILE = ROOT / ("pipelines/sft-reading-lima-finalize.webui.json" if FINALIZE
                      else "pipelines/sft-reading-lima-eval.webui.json")
STATE_FILE = ROOT / ("pipelines/sft-reading-lima-finalize.registration.json" if FINALIZE
                     else "pipelines/sft-reading-lima-eval.registration.json")
PIPELINE_NAME = ("SFT 阅读论文评分后整理 · LIMA #22" if FINALIZE
                 else "SFT 阅读论文双 QA 评价接续 · LIMA #22")


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
        raise ValueError("QA transformation checkpoint changed")
    rows = [json.loads(line) for line in SOURCE.read_text().splitlines() if line.strip()]
    if len(rows) != 2 or not all({"question", "answer", "raw_chunk"}.issubset(r) for r in rows):
        raise ValueError("Expected two independent QA rows")

    datasets = [d for d in api("/datasets/") if d.get("root") == str(SOURCE)]
    if len(datasets) > 1:
        raise ValueError("Several datasets point to this QA checkpoint")
    dataset = datasets[0] if datasets else api("/datasets/", {
        "name": ("SFT 阅读论文 · LIMA #22 评分缓存" if FINALIZE
                 else "SFT 阅读论文 · LIMA #22 双 QA 缓存"),
        "root": str(SOURCE), "pipeline": "SFTReadingFinalize" if FINALIZE else "SFTReadingEval",
        "meta": {"source_task_id": "5879b99d0e3c" if FINALIZE else "b5f5508a6c18",
                 "sha256": SOURCE_SHA256},
    })
    columns = set(api(f"/datasets/columns/{dataset['id']}"))
    if not {"question", "answer", "raw_chunk"}.issubset(columns):
        raise ValueError(f"Unexpected dataset columns: {columns}")

    config = deepcopy(json.loads(PARENT.read_text())["config"])
    config["file_path"] = str(CONFIG_FILE)
    config["input_dataset"]["id"] = dataset["id"]
    config["operators"] = config["operators"][6:] if FINALIZE else config["operators"][4:]
    expected = (["GeneralFilter", "HashDeduplicateFilter", "PandasOperator"] if FINALIZE
                else ["Text2QASampleEvaluator", "AlpagasusSampleEvaluator",
                      "GeneralFilter", "HashDeduplicateFilter", "PandasOperator"])
    if [op["name"] for op in config["operators"]] != expected:
        raise ValueError("Unexpected evaluation operator chain")
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
               "tags": ["paper", "sft", "checkpoint", "two-qa", "not-executed"]}
    existing = [p for p in api("/pipelines/") if p.get("name") == PIPELINE_NAME]
    if len(existing) > 1:
        raise ValueError("Several pipelines have the evaluation name")
    pipeline = existing[0] if existing else api("/pipelines/", payload)
    if pipeline["config"]["input_dataset"]["id"] != dataset["id"]:
        raise ValueError("Existing pipeline points to a different QA checkpoint")

    CONFIG_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    state = {"pipeline_id": pipeline["id"], "dataset_id": dataset["id"],
             "source_task_id": "5879b99d0e3c" if FINALIZE else "b5f5508a6c18",
             "source_sha256": SOURCE_SHA256,
             "validation": validation, "status": "registered_not_executed"}
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"pipeline_id": pipeline["id"], "dataset_id": dataset["id"],
                      "valid": validation["valid"], "status": state["status"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
