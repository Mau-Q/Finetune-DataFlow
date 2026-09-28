"""Register a one-paper copy of the SFT reading pipeline without running it."""

import json
import urllib.request
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8000/api/v1"
SOURCE = ROOT / "data/sft-reading-13/lima-one.jsonl"
PARENT_CONFIG = ROOT / "pipelines/sft-reading-13.webui.json"
CONFIG_FILE = ROOT / "pipelines/sft-reading-lima-one.webui.json"
STATE_FILE = ROOT / "pipelines/sft-reading-lima-one.registration.json"
PIPELINE_NAME = "SFT 阅读论文单篇试跑 · LIMA"
DATASET_NAME = "SFT 阅读论文单篇试跑 · LIMA PDF"


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
    rows = [json.loads(line) for line in SOURCE.read_text().splitlines() if line.strip()]
    if len(rows) != 1:
        raise ValueError("The smoke-test manifest must contain exactly one PDF")
    row = rows[0]
    pdf = Path(row["source"])
    if not pdf.is_file() or pdf.suffix.lower() != ".pdf" or pdf.name != row["source_name"]:
        raise ValueError(f"Invalid PDF source: {pdf}")

    datasets = [item for item in api("/datasets/") if item.get("root") == str(SOURCE)]
    if len(datasets) > 1:
        raise ValueError("Several datasets point to the single-paper manifest")
    dataset = datasets[0] if datasets else api("/datasets/", {
        "name": DATASET_NAME, "root": str(SOURCE), "pipeline": "SFTReadingOne",
        "meta": {"scope": "one-paper smoke test; no execution yet"},
    })
    columns = api(f"/datasets/columns/{dataset['id']}")
    if not {"source", "source_name"}.issubset(set(columns)):
        raise ValueError(f"Unexpected dataset columns: {columns}")

    parent = json.loads(PARENT_CONFIG.read_text())
    config = deepcopy(parent["config"])
    config["input_dataset"]["id"] = dataset["id"]
    config["file_path"] = str(CONFIG_FILE)
    parser = next(op for op in config["operators"] if op["name"] == "MinerU4PDFParser")
    for param in parser["params"]["init"]:
        if param["name"] == "output_dir":
            param["value"] = str(ROOT / "outputs/sft-reading-lima-one/parsing")

    serving_ids = {item["id"] for item in api("/serving/")}
    for op in config["operators"]:
        for param in op["params"]["init"]:
            if param["name"] == "llm_serving" and param["value"] not in serving_ids:
                raise ValueError(f"Missing serving for {op['name']}")

    validation = api("/pipelines/validate", config)
    if not validation.get("valid"):
        raise RuntimeError(json.dumps(validation.get("errors"), ensure_ascii=False))
    payload = {"name": PIPELINE_NAME, "config": config,
               "tags": ["paper", "sft", "one-pdf", "smoke-test", "not-executed"]}
    existing = [item for item in api("/pipelines/") if item.get("name") == PIPELINE_NAME]
    if len(existing) > 1:
        raise ValueError("Several pipelines have the smoke-test name")
    if existing:
        pipeline = existing[0]
        if pipeline["config"]["input_dataset"]["id"] != dataset["id"]:
            raise ValueError("An existing smoke-test pipeline points to another dataset")
    else:
        pipeline = api("/pipelines/", payload)

    CONFIG_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    state = {"pipeline_id": pipeline["id"], "dataset_id": dataset["id"],
             "operator_count": len(config["operators"]), "validation": validation,
             "status": "registered_not_executed"}
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"pipeline_id": pipeline["id"], "dataset_id": dataset["id"],
                      "operators": len(config["operators"]),
                      "valid": validation["valid"], "status": state["status"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
