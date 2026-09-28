"""Blind, batchwise independent QA assessment for the LIMA paired experiment."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import uuid

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
DIMENSIONS = ("source_supported_facts", "answerability", "answer_completeness",
              "numbers_entities_conditions", "instruction_self_containment",
              "learning_value", "expression_clarity")
BATCH_SIZE = 8


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_jsonl(path):
    return [json.loads(s) for s in Path(path).read_text().splitlines() if s.strip()]


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def schema():
    grade = {"type": "string", "enum": ["MET", "NOT_MET", "UNSURE"]}
    assessment = {"type": "object", "additionalProperties": False,
                  "required": ["opaque_sample_id", "dimensions", "multihop_required", "reason", "source_quote"],
                  "properties": {
                      "opaque_sample_id": {"type": "string"},
                      "dimensions": {"type": "object", "additionalProperties": False,
                                     "required": list(DIMENSIONS), "properties": {key: grade for key in DIMENSIONS}},
                      "multihop_required": {"type": "string", "enum": ["YES", "NO", "UNSURE"]},
                      "reason": {"type": "string", "minLength": 1},
                      "source_quote": {"type": "string"},
                  }}
    return {"type": "object", "additionalProperties": False, "required": ["assessments"],
            "properties": {"assessments": {"type": "array", "items": assessment}}}


def prepare(experiment, output):
    legacy = experiment / "legacy-production"
    sources = [experiment / "current-candidates.jsonl", legacy / "legacy-candidates.jsonl"]
    summary = json.loads((legacy / "summary.json").read_text())
    if summary["status"] != "PRODUCTION_COMPLETE":
        raise ValueError("Legacy production incomplete")
    candidates = read_jsonl(sources[0]) + read_jsonl(sources[1])
    evidence = {r["candidate_id"]: r["evidence"] for r in read_jsonl(experiment / "shared-evidence.jsonl")}
    if len(candidates) != 66 + summary["legacy_candidate_count"]:
        raise ValueError("Candidate count changed")
    output.mkdir(parents=True, exist_ok=False)
    blind, mapping = [], []
    for row in candidates:
        if row["candidate_id"] not in evidence or row["source_evidence"] != evidence[row["candidate_id"]]:
            raise ValueError("Candidate evidence mismatch")
        opaque = uuid.uuid4().hex
        blind.append({"opaque_sample_id": opaque, "question": row["question"],
                      "answer": row["answer"], "source_evidence": row["source_evidence"]})
        mapping.append({"opaque_sample_id": opaque, "arm": row["arm"],
                        "candidate_id": row["candidate_id"], "qa_index": row["qa_index"]})
    random.SystemRandom().shuffle(blind)
    batches = [blind[i:i+BATCH_SIZE] for i in range(0, len(blind), BATCH_SIZE)]
    write_json(output / "blind-batches.json", batches)
    write_json(output / "private-map.json", mapping)
    write_json(output / "schema.json", schema())
    write_json(output / "manifest.json", {"status": "PREPARED_NO_JUDGE_CALL", "model": "gpt-6-astra",
               "reasoning_effort": "high", "items": len(blind), "batches": len(batches),
               "source_sha256": {str(p.relative_to(experiment)): sha(p) for p in sources},
               "artifact_sha256": {name: sha(output / name) for name in ("blind-batches.json", "private-map.json", "schema.json")},
               "runner_sha256": sha(__file__)})


def cli_command(cli, workdir):
    cmd = [str(cli), "exec", "--ignore-user-config", "--ephemeral", "--skip-git-repo-check",
           "--sandbox", "read-only", "--cd", str(workdir), "--model", "gpt-6-astra",
           "--json", "--color", "never", "--output-schema", str(workdir / "schema.json"),
           "--output-last-message", str(workdir / "answer.json")]
    settings = ['model_reasoning_effort="high"', 'model_provider="openai"',
                'web_search="disabled"', 'project_doc_max_bytes=0']
    disabled = ("shell_tool", "unified_exec", "apps", "plugins", "remote_plugin", "hooks",
                "multi_agent", "multi_agent_v2", "browser_use", "browser_use_external",
                "computer_use", "in_app_browser", "image_generation", "view_image")
    settings += [f"features.{key}=false" for key in disabled]
    for setting in settings:
        cmd.extend(["--config", setting])
    return cmd + ["-"]


def prompt(batch):
    rubric = (ROOT / "pipelines/astra-quality-rubric.md").read_text()
    return (rubric + "\n\n本次一次评价多个匿名 SAMPLE_JSON。对每条分别判断七个维度；"
            "另判断问题是否必须连接至少两个可定位的事实才能回答（multihop_required）。"
            "只有在不能从单句或相邻直接陈述得到答案时才标 YES。"
            "每条给一句具体理由和一段逐字原文短引文；无法引用时填空字符串。"
            "返回 assessments 数组，条数和 opaque_sample_id 与输入完全一致。\n\nSAMPLE_JSON\n"
            + json.dumps(batch, ensure_ascii=False))


def validate(value, batch, expected_schema):
    jsonschema.validate(value, expected_schema)
    assessments = value["assessments"]
    samples = {s["opaque_sample_id"]: s for s in batch}
    if len(assessments) != len(batch) or {a["opaque_sample_id"] for a in assessments} != set(samples):
        raise ValueError("Judge response does not cover exactly the batch")
    for assessment in assessments:
        quote = assessment["source_quote"]
        if quote and quote not in samples[assessment["opaque_sample_id"]]["source_evidence"]:
            raise ValueError("Judge quote not found in evidence")
    return assessments


def execute(output):
    manifest = json.loads((output / "manifest.json").read_text())
    if manifest["runner_sha256"] != sha(__file__):
        raise ValueError("Judge runner changed after freeze")
    for name, expected in manifest["artifact_sha256"].items():
        if sha(output / name) != expected:
            raise ValueError(f"Frozen judge artifact changed: {name}")
    batches = json.loads((output / "blind-batches.json").read_text())
    expected_schema = json.loads((output / "schema.json").read_text())
    cli = shutil.which("codex")
    if not cli:
        raise ValueError("Codex CLI unavailable")
    runs = output / "execution"
    runs.mkdir(exist_ok=True)
    all_assessments = []
    for number, batch in enumerate(batches, 1):
        dest = runs / f"batch-{number:02d}"
        if (dest / "result.json").exists():
            value = json.loads((dest / "result.json").read_text())
            all_assessments.extend(validate(value, batch, expected_schema))
            continue
        if dest.exists():
            raise ValueError(f"Batch {number} started but lacks verified result; inspect before retry")
        dest.mkdir()
        write_json(dest / "batch.json", batch)
        with tempfile.TemporaryDirectory(prefix="lima-blind-judge-") as temp:
            workdir = Path(temp)
            shutil.copyfile(output / "schema.json", workdir / "schema.json")
            with (dest / "events.jsonl").open("x") as events, (dest / "stderr.log").open("x") as stderr:
                proc = subprocess.run(cli_command(cli, workdir), input=prompt(batch), text=True,
                                      stdout=events, stderr=stderr, cwd=workdir, timeout=600)
            if proc.returncode:
                raise RuntimeError(f"Judge batch {number} exited {proc.returncode}; preserve logs")
            value = json.loads((workdir / "answer.json").read_text())
            assessments = validate(value, batch, expected_schema)
            write_json(dest / "result.json", value)
            all_assessments.extend(assessments)
        print(f"Judged {len(all_assessments)}/{manifest['items']}", flush=True)
    mapping = {r["opaque_sample_id"]: r for r in json.loads((output / "private-map.json").read_text())}
    results = []
    for assessment in all_assessments:
        grades = assessment["dimensions"]
        verdict = ("NOT_QUALIFIED" if "NOT_MET" in grades.values() else
                   "UNSURE" if "UNSURE" in grades.values() else "QUALIFIED")
        results.append({**mapping[assessment["opaque_sample_id"]], "assessment": assessment,
                        "qualification": verdict})
    write_json(output / "assessments.json", results)
    summary = {}
    for arm in ("current_13", "legacy_sft2000"):
        selected = [r for r in results if r["arm"] == arm]
        summary[arm] = {"total": len(selected),
                        "qualification": dict(Counter(r["qualification"] for r in selected)),
                        "multihop_required": dict(Counter(r["assessment"]["multihop_required"] for r in selected))}
    write_json(output / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.prepare == args.execute:
        parser.error("Choose exactly one of --prepare or --execute")
    experiment, output = args.experiment.resolve(), args.output.resolve()
    if args.prepare:
        prepare(experiment, output)
        print("PREPARED_NO_JUDGE_CALL")
    else:
        execute(output)


if __name__ == "__main__":
    main()
