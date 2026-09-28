"""Blindly assess LIMA QA emitted by the legacy model but rejected by local gates."""
import importlib.util
import json
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import uuid


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "outputs/lima-sft2000-compare-2026-09-28"
OUTPUT = EXPERIMENT / "blind-evaluation-supplemental"
spec = importlib.util.spec_from_file_location("lima_blind_eval", ROOT / "scripts/lima-blind-qa-eval.py")
judge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(judge)


def main():
    source = EXPERIMENT / "legacy-production/generation.jsonl"
    records = {r["candidate_id"]: r for r in judge.read_jsonl(EXPERIMENT / "shared-evidence.jsonl")}
    excluded = []
    for row in judge.read_jsonl(source):
        if row["quality_decision"] not in ("REJECT", None):
            continue
        try:
            value = json.loads(row["generator_observation"]["raw_response"])
        except json.JSONDecodeError:
            continue
        if (value.get("status") == "GENERATED" and
                all(isinstance(value.get(k), str) and value[k].strip() for k in ("question", "answer"))):
            excluded.append((row, value))
    if len(excluded) != 5:
        raise ValueError(f"Expected five locally excluded but parseable QA; found {len(excluded)}")
    OUTPUT.mkdir(exist_ok=False)
    blind, mapping = [], []
    for row, value in excluded:
        candidate_id = row["candidate_id"]
        opaque = uuid.uuid4().hex
        blind.append({"opaque_sample_id": opaque, "question": value["question"],
                      "answer": value["answer"], "source_evidence": records[candidate_id]["evidence"]})
        mapping.append({"opaque_sample_id": opaque, "arm": "legacy_sft2000",
                        "candidate_id": candidate_id, "qa_index": 1,
                        "local_decision": row["quality_decision"], "reason_codes": row["reason_codes"]})
    random.SystemRandom().shuffle(blind)
    judge.write_json(OUTPUT / "blind-input.json", blind)
    judge.write_json(OUTPUT / "private-map.json", mapping)
    judge.write_json(OUTPUT / "schema.json", judge.schema())
    judge.write_json(OUTPUT / "manifest.json", {"status": "PREPARED", "items": 5,
                     "generator_record_sha256": judge.sha(source),
                     "judge_runner_sha256": judge.sha(judge.__file__),
                     "artifact_sha256": {n: judge.sha(OUTPUT / n) for n in
                                         ("blind-input.json", "private-map.json", "schema.json")}})
    cli = shutil.which("codex")
    if not cli:
        raise ValueError("Codex CLI unavailable")
    with tempfile.TemporaryDirectory(prefix="lima-blind-supplemental-") as temp:
        workdir = Path(temp)
        shutil.copyfile(OUTPUT / "schema.json", workdir / "schema.json")
        with (OUTPUT / "events.jsonl").open("x") as events, (OUTPUT / "stderr.log").open("x") as stderr:
            proc = subprocess.run(judge.cli_command(cli, workdir), input=judge.prompt(blind),
                                  text=True, stdout=events, stderr=stderr, cwd=workdir, timeout=600)
        if proc.returncode:
            raise RuntimeError(f"Supplemental judge exited {proc.returncode}")
        value = json.loads((workdir / "answer.json").read_text())
    assessments = judge.validate(value, blind, judge.schema())
    judge.write_json(OUTPUT / "result.json", value)
    mapping = {r["opaque_sample_id"]: r for r in mapping}
    results = []
    for assessment in assessments:
        grades = assessment["dimensions"]
        qualification = ("NOT_QUALIFIED" if "NOT_MET" in grades.values() else
                         "UNSURE" if "UNSURE" in grades.values() else "QUALIFIED")
        results.append({**mapping[assessment["opaque_sample_id"]], "assessment": assessment,
                        "qualification": qualification})
    judge.write_json(OUTPUT / "assessments.json", results)
    print({"items": len(results), "qualification": {k: sum(r["qualification"] == k for r in results)
                                                 for k in ("QUALIFIED", "NOT_QUALIFIED", "UNSURE")}}, flush=True)


if __name__ == "__main__":
    main()
