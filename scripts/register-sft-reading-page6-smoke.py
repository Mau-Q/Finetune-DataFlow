"""Prepare and register a bounded one-page PDF run through all 13 operators."""

import hashlib
import json
import urllib.request
from copy import deepcopy
from pathlib import Path

import pymupdf


ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8000/api/v1"
ORIGINAL = Path(
    "/Users/rui/Downloads/SFT-data-composition-reading/"
    "02_Zhou_2023_LIMA_Less_Is_More_for_Alignment.pdf"
)
ORIGINAL_PAGE_INDEX = 5
SOURCE = ROOT / "data/sft-reading-13/lima-page6-smoke.pdf"
MANIFEST = ROOT / "data/sft-reading-13/lima-page6-smoke.jsonl"
PARENT = ROOT / "pipelines/sft-reading-lima-one.webui.json"
CONFIG_FILE = ROOT / "pipelines/sft-reading-lima-page6-smoke.webui.json"
STATE_FILE = ROOT / "pipelines/sft-reading-lima-page6-smoke.registration.json"
NAME = "SFT 阅读论文单页 PDF 全链路 · LIMA p6"


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


def prepare_input():
    with pymupdf.open(ORIGINAL) as original:
        if len(original) != 15:
            raise ValueError("Original LIMA PDF page count changed")
        source_text = original[ORIGINAL_PAGE_INDEX].get_text()
        if "Why is Less More?" not in source_text:
            raise ValueError("Original page 6 content changed")
        if not SOURCE.exists():
            with pymupdf.open() as clipped:
                clipped.insert_pdf(original, from_page=ORIGINAL_PAGE_INDEX,
                                   to_page=ORIGINAL_PAGE_INDEX)
                clipped.save(SOURCE)
    with pymupdf.open(SOURCE) as clipped:
        if len(clipped) != 1 or clipped[0].get_text() != source_text:
            raise ValueError("Derived PDF is not an exact page-text extraction")
    manifest_row = {
        "source": str(SOURCE), "source_name": SOURCE.name,
        "original_source": str(ORIGINAL), "original_page_number": 6,
        "original_sha256": hashlib.sha256(ORIGINAL.read_bytes()).hexdigest(),
        "derived_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
    }
    manifest_text = json.dumps(manifest_row, ensure_ascii=False) + "\n"
    if MANIFEST.exists() and MANIFEST.read_text() != manifest_text:
        raise ValueError("Existing input manifest differs")
    MANIFEST.write_text(manifest_text)
    return manifest_row


def main():
    source = prepare_input()
    datasets = [d for d in api("/datasets/") if d.get("root") == str(MANIFEST)]
    if len(datasets) > 1:
        raise ValueError("Duplicate one-page datasets")
    dataset = datasets[0] if datasets else api("/datasets/", {
        "name": "LIMA 原论文第 6 页 · PDF 单页试跑",
        "root": str(MANIFEST), "pipeline": "SFTReadingPage6Smoke",
        "meta": {"original_source": str(ORIGINAL),
                 "original_page_number": "6",
                 "derived_sha256": source["derived_sha256"]},
    })
    if not {"source", "source_name"}.issubset(
        set(api(f"/datasets/columns/{dataset['id']}"))
    ):
        raise ValueError("Missing PDF input columns")

    config = deepcopy(json.loads(PARENT.read_text())["config"])
    config["file_path"] = str(CONFIG_FILE)
    config["input_dataset"]["id"] = dataset["id"]
    if len(config["operators"]) != 13 or config["operators"][0]["name"] != "MinerU4PDFParser":
        raise ValueError("Unexpected parent pipeline")
    for param in config["operators"][0]["params"]["init"]:
        if param["name"] == "output_dir":
            param["value"] = str(ROOT / "outputs/sft-reading-13/page6-smoke-parsing")
    serving_ids = {item["id"] for item in api("/serving/")}
    for op in config["operators"]:
        for param in op["params"]["init"]:
            if param["name"] == "llm_serving" and param["value"] not in serving_ids:
                raise ValueError(f"Missing serving for {op['name']}")
    validation = api("/pipelines/validate", config)
    if not validation.get("valid"):
        raise RuntimeError("Full pipeline validation failed")
    payload = {"name": NAME, "config": config,
               "tags": ["paper", "sft", "single-page-pdf", "bounded-smoke"]}
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
        "source": source, "operator_count": len(config["operators"]),
        "validation": validation, "status": "registered_not_executed",
    }, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"pipeline_id": pipeline["id"], "dataset_id": dataset["id"],
                      "operators": len(config["operators"]),
                      "valid": validation["valid"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
