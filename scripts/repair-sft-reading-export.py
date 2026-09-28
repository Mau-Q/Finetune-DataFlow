"""Make the registered SFT export step safe when the score filter keeps no rows."""

import json
import urllib.request
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8000/api/v1"
OLD = (
    "lambda df: df.assign(instruction=lambda d: d['question'], "
    "input=lambda d: d['raw_chunk'], output=lambda d: d['answer'])"
)
NEW = (
    "lambda df: df.assign(instruction=lambda d: d.get('question', ''), "
    "input=lambda d: d.get('raw_chunk', ''), output=lambda d: d.get('answer', ''))"
)
TARGETS = (
    ("6987ae3b-da14-4f24-84a8-ff2573c2a17d", "pipelines/sft-reading-13.webui.json"),
    ("8a1c6d04-5744-443f-9e59-8b8741be0de4", "pipelines/sft-reading-lima-one.webui.json"),
    ("fc2ff76e-d6ee-44c5-93c8-1ae9c2dcc70b", "pipelines/sft-reading-lima-resume-one.webui.json"),
    ("3f377f99-0757-4df8-9294-1813ccf87560", "pipelines/sft-reading-lima-eval.webui.json"),
)


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


def update_export(config):
    config = deepcopy(config)
    matches = []
    for op in config["operators"]:
        if op["name"] != "PandasOperator":
            continue
        for param in op["params"]["init"]:
            if param["name"] == "process_fn" and param["value"] in (OLD, NEW):
                matches.append(param)
    if len(matches) != 1:
        raise ValueError(f"Expected one known export step, found {len(matches)}")
    matches[0]["value"] = NEW
    return config


def main():
    prepared = []
    for pipeline_id, relative_path in TARGETS:
        remote = api(f"/pipelines/{pipeline_id}")
        local_path = ROOT / relative_path
        local = json.loads(local_path.read_text())
        if remote["name"] != local["name"]:
            raise ValueError(f"Pipeline identity changed: {pipeline_id}")
        remote_config = update_export(remote["config"])
        local_config = update_export(local["config"])
        validation = api("/pipelines/validate", remote_config, "POST")
        if not validation.get("valid"):
            raise RuntimeError(f"Updated pipeline failed validation: {pipeline_id}")
        prepared.append((pipeline_id, remote, remote_config, local_path, local, local_config))

    for pipeline_id, remote, remote_config, local_path, local, local_config in prepared:
        api(f"/pipelines/{pipeline_id}", {
            "name": remote["name"], "config": remote_config, "tags": remote.get("tags", []),
        }, "PUT")
        local["config"] = local_config
        local_path.write_text(json.dumps(local, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({"pipeline_id": pipeline_id, "export_handles_empty": True}))


if __name__ == "__main__":
    main()
