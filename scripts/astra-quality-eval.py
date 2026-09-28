"""Freeze blinded final SFT exports, then explicitly run a Codex CLI judge.

prepare and run without --execute never call a model. No implicit retries/resume.
Input export adapter: one JSONL row per FINAL export with arm, candidate_id,
question, answer, source_evidence. Production admission is upstream's responsibility.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import signal
import subprocess
import tempfile
import time
import uuid

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
MODEL = "gpt-6-astra"
EFFORT = "high"
DIMENSIONS = (
    "source_supported_facts", "answerability", "answer_completeness",
    "numbers_entities_conditions", "instruction_self_containment",
    "learning_value", "expression_clarity",
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def rows(path):
    return [json.loads(line) for line in Path(path).read_text().split("\n") if line.strip()]


def object_schema(properties):
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


def schema():
    grade = object_schema({"verdict": {"type": "string", "enum": ["MET", "NOT_MET", "UNSURE"]},
                           "reason": {"type": "string", "minLength": 1}})
    issue = object_schema({"dimension": {"type": "string", "enum": list(DIMENSIONS)},
                           "description": {"type": "string", "minLength": 1},
                           "source_quote": {"type": "string"}})
    return object_schema({
        "opaque_sample_id": {"type": "string"},
        "dimensions": object_schema({key: grade for key in DIMENSIONS}),
        "issue_evidence": {"type": "array", "items": issue},
        "question_type": {"type": "string", "enum": ["definition", "mechanism", "comparison", "quantitative", "procedure", "other"]},
        "difficulty": {"type": "string", "enum": ["basic", "intermediate", "advanced", "uncertain"]},
    })


def prepare(input_path, output, evidence_path=None):
    evidence_path = evidence_path or ROOT / "data/round1/development-structured-reviewed/shared-evidence.jsonl"
    evidence = {r["candidate_id"]: r["evidence"] for r in rows(evidence_path)}
    exported = rows(input_path)
    if len(exported) > 22:
        raise ValueError("Round 1 permits at most 22 final exports")
    seen = set()
    blind, mapping = [], []
    for row in exported:
        if set(row) != {"arm", "candidate_id", "question", "answer", "source_evidence"}:
            raise ValueError("Expected normalized final-export fields only")
        if row["arm"] not in {"A", "B"} or row["candidate_id"] not in evidence:
            raise ValueError("Unknown arm or candidate")
        identity = (row["arm"], row["candidate_id"])
        if identity in seen:
            raise ValueError("Duplicate arm/candidate export")
        seen.add(identity)
        if row["source_evidence"] != evidence[row["candidate_id"]]:
            raise ValueError("Evidence differs from frozen shared input")
        if any(not isinstance(row[k], str) or not row[k].strip() for k in ("question", "answer")):
            raise ValueError("Empty or invalid QA")
        opaque = uuid.uuid4().hex
        blind.append({"opaque_sample_id": opaque, **{k: row[k] for k in ("question", "answer", "source_evidence")}})
        mapping.append({"opaque_sample_id": opaque, "arm": row["arm"], "candidate_id": row["candidate_id"]})
    random.SystemRandom().shuffle(blind)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "blind-input.json", blind)
    write_json(output / "private-map.json", mapping)
    write_json(output / "schema.json", schema())
    shutil.copyfile(ROOT / "pipelines/astra-quality-rubric.md", output / "rubric.md")
    write_json(output / "manifest.json", {
        "status": "PREPARED_NOT_SENT", "model": MODEL, "reasoning_effort": EFFORT,
        "source_export_sha256": sha(input_path), "shared_evidence_sha256": sha(evidence_path),
        "runner_sha256": sha(__file__), "items": len(blind), "max_cli_invocations": len(blind),
        "timeout_seconds_per_item": 600, "wrapper_retries": 0,
        "usage_accounting": "Excluded by user: assess SFT quality only, not evaluator consumption or cost",
        "artifact_sha256": {n: sha(output / n) for n in ("blind-input.json", "private-map.json", "schema.json", "rubric.md")},
    })


def command(cli, workdir):
    args = [str(cli), "exec", "--ignore-user-config", "--ephemeral", "--skip-git-repo-check",
            "--sandbox", "read-only", "--cd", str(workdir), "--model", MODEL,
            "--json", "--color", "never", "--output-schema", str(workdir / "schema.json"),
            "--output-last-message", str(workdir / "answer.json")]
    settings = ['model_reasoning_effort="high"', 'model_provider="openai"',
                'web_search="disabled"', 'project_doc_max_bytes=0']
    disabled = ("shell_tool", "unified_exec", "apps", "plugins", "remote_plugin", "hooks",
                "multi_agent", "multi_agent_v2", "browser_use", "browser_use_external",
                "computer_use", "in_app_browser", "image_generation", "view_image",
                "code_mode_host", "skill_search", "unbounded_connection_retries")
    settings += [f"features.{key}=false" for key in disabled]
    settings += ["features.skip_host_skill_discovery=true"]
    for setting in settings:
        args.extend(["--config", setting])
    return args + ["-"]


def validate_response(value, sample, events, expected_schema):
    jsonschema.validate(value, expected_schema)
    if value["opaque_sample_id"] != sample["opaque_sample_id"]:
        raise ValueError("Response sample ID mismatch")
    for issue in value["issue_evidence"]:
        if issue["source_quote"] not in sample["source_evidence"]:
            raise ValueError("Source quote not present in evidence")
    completed = [e for e in events if e.get("type") == "turn.completed"]
    if len(completed) != 1 or any(e.get("type") in {"error", "turn.failed"} for e in events):
        raise ValueError("CLI did not complete exactly one successful turn")
    turn_started = False
    for event in events:
        if event.get("type") == "turn.started":
            turn_started = True
        item = event.get("item", {})
        # exec 0.155.1 emits known local startup warnings as error *items*.
        # They precede the model turn, are not tool activity, and do not invalidate
        # a schema-valid answer with a successful turn.completed event.
        startup_warning = (not turn_started and item.get("type") == "error" and
            str(item.get("message", "")).startswith((
                "Under-development features enabled: skip_host_skill_discovery.",
                "Code Mode is unavailable because code-mode host is disabled.")))
        if startup_warning:
            continue
        if item and item.get("type") not in {"reasoning", "agent_message"}:
            raise ValueError("Unexpected tool/activity in blind judge session")
    verdicts = [value["dimensions"][key]["verdict"] for key in DIMENSIONS]
    qualified = "NOT_QUALIFIED" if "NOT_MET" in verdicts else "UNSURE" if "UNSURE" in verdicts else "QUALIFIED"
    return {"assessment": value, "qualification": qualified,
            "requested_model": MODEL,
            "requested_reasoning_effort": EFFORT,
            "served_model_identity": "Not independently exposed by standard exec JSON events"}


def run(bundle, execute=False, resume=False):
    bundle = Path(bundle).resolve()
    manifest = json.loads((bundle / "manifest.json").read_text())
    runner_matches = manifest["runner_sha256"] == sha(__file__)
    repair_path = bundle / "execution-repair.json"
    if resume and not runner_matches and repair_path.exists():
        repair = json.loads(repair_path.read_text())
        runner_matches = (repair.get("from_runner_sha256") == manifest["runner_sha256"] and
                          repair.get("to_runner_sha256") == sha(__file__) and
                          repair.get("manifest_sha256") == sha(bundle / "manifest.json"))
    if manifest["model"] != MODEL or manifest["reasoning_effort"] != EFFORT or not runner_matches:
        raise ValueError("Runner/model drift; prepare a new frozen bundle")
    for name, digest in manifest["artifact_sha256"].items():
        if sha(bundle / name) != digest:
            raise ValueError(f"Frozen artifact changed: {name}")
    samples = json.loads((bundle / "blind-input.json").read_text())
    if len(samples) != manifest["items"] or len(samples) > 22:
        raise ValueError("Manifest item count mismatch")
    if not execute:
        return {"status": "DRY_RUN_NO_MODEL_CALL", "items": len(samples), "model": MODEL,
                "reasoning_effort": EFFORT, "command_template": command("codex", Path("/isolated-judge-workdir"))}
    cli = shutil.which("codex")
    if not cli:
        raise ValueError("Codex CLI missing")
    # Exclusive directory creation prevents accidental replays of a started/failed run.
    results = bundle / "execution"
    if resume:
        started_record = json.loads((results / "started.json").read_text())
        if started_record["manifest_sha256"] != sha(bundle / "manifest.json") or (results / "completed.json").exists():
            raise ValueError("Cannot resume changed or completed execution")
        write_json(results / "resume-started.json", {"runner_sha256": sha(__file__), "reason": "Validate saved completed response, then execute only unstarted items"})
    else:
        results.mkdir(exist_ok=False)
        write_json(results / "started.json", {"status": "STARTED", "manifest_sha256": sha(bundle / "manifest.json"),
                   "cli_version": subprocess.check_output([cli, "--version"], text=True).strip()})
    rubric = (bundle / "rubric.md").read_text()
    expected_schema = json.loads((bundle / "schema.json").read_text())
    for sample in samples:
        dest = results / sample["opaque_sample_id"]
        if resume and dest.exists():
            # No replay of ambiguous transport failures or interrupted model calls.
            # Recovery requires a completed, valid response already on disk.
            value = json.loads((dest / "answer.json").read_text())
            result = validate_response(value, sample, rows(dest / "events.jsonl"), expected_schema)
            if not (dest / "result.json").exists():
                result["recovered_from_saved_response"] = True
                write_json(dest / "result.json", result)
            continue
        dest.mkdir()
        prompt = rubric + "\n\nSAMPLE_JSON\n" + json.dumps(sample, ensure_ascii=False)
        (dest / "prompt.txt").write_text(prompt)
        started = time.monotonic()
        try:
            # Only schema and this anonymous sample are placed in a fresh working directory.
            with tempfile.TemporaryDirectory(prefix="sft-judge-") as temp:
                workdir = Path(temp)
                shutil.copyfile(bundle / "schema.json", workdir / "schema.json")
                args = command(cli, workdir)
                write_json(dest / "command.json", args)
                with (dest / "events.jsonl").open("w") as out, (dest / "stderr.log").open("w") as err:
                    proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=out, stderr=err,
                                            text=True, cwd=workdir, start_new_session=True)
                    try:
                        proc.communicate(prompt, timeout=600)
                    except (subprocess.TimeoutExpired, KeyboardInterrupt):
                        os.killpg(proc.pid, signal.SIGTERM)
                        try:
                            proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            os.killpg(proc.pid, signal.SIGKILL)
                            proc.wait()
                        raise
                response = workdir / "answer.json"
                if response.exists():
                    shutil.copyfile(response, dest / "answer.json")
                if proc.returncode != 0:
                    raise ValueError(f"Codex exited {proc.returncode}")
                value = json.loads(response.read_text())
                result = validate_response(value, sample, rows(dest / "events.jsonl"), expected_schema)
                result["elapsed_seconds"] = time.monotonic() - started
                write_json(dest / "result.json", result)
        except (Exception, KeyboardInterrupt) as error:
            write_json(dest / "failure.json", {"status": "ERROR_STOPPED_NO_RETRY", "error_type": type(error).__name__,
                       "message": str(error), "elapsed_seconds": time.monotonic() - started})
            raise
    status = {"status": "COMPLETE" if samples else "EMPTY_EXPORT_NO_QUALITY_ESTIMATE", "items": len(samples)}
    write_json(results / "completed.json", status)
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="action", required=True)
    prepare_parser = subs.add_parser("prepare", help="Freeze final exports; no model calls")
    prepare_parser.add_argument("--input", required=True, type=Path)
    prepare_parser.add_argument("--output", required=True, type=Path)
    run_parser = subs.add_parser("run", help="Dry-run unless --execute is explicitly supplied")
    run_parser.add_argument("--bundle", required=True, type=Path)
    run_parser.add_argument("--execute", action="store_true")
    run_parser.add_argument("--resume", action="store_true", help="Recover valid saved responses and run only unstarted items; never retry a failed model call")
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.input, args.output)
        print("PREPARED_NOT_SENT")
    else:
        print(json.dumps(run(args.bundle, args.execute, args.resume), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
