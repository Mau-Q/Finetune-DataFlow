"""Separately blind-evaluate B's nine rejected candidates; user-authorized diagnostic."""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path

from paper_dataflow.baseline import quality as q

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("astra_judge", ROOT / "scripts/astra-quality-eval.py")
judge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(judge)


def prepare(run):
    production = json.loads((run / "production-summary.json").read_text())
    if judge.sha(run / "final-exports.jsonl") != production["final_exports_sha256"]:
        raise ValueError("Production outputs changed")
    rejected = {r["candidate_id"]: r for r in judge.rows(run / "production-audit.jsonl")
                if r["arm"] == "B" and r["decision"] == "REJECT"}
    evidence = {r["candidate_id"]: r for r in judge.rows(ROOT / "data/round1/development-structured-reviewed/shared-evidence.jsonl")}
    observed = {r["candidate_id"]: r for r in judge.rows(run / "B-production/verification.jsonl")}
    if len(rejected) != 9:
        raise ValueError("Expected exactly the nine rejected B candidates")
    accepted = {r["candidate_id"] for r in judge.rows(run / "final-exports.jsonl") if r["arm"] == "B"}
    if accepted & rejected.keys() or accepted | rejected.keys() != evidence.keys():
        raise ValueError("Accepted/rejected partition mismatch")
    samples, lineage = [], []
    for identity, decision in rejected.items():
        raw = observed[identity]["generator_observation"]["raw_response"]
        value = json.loads(q.strip_json_fence(raw))
        if value.get("status") != "GENERATED" or any(not isinstance(value.get(k), str) or not value[k].strip() for k in ("question", "answer")):
            raise ValueError("Rejected candidate has no evaluable QA; do not fabricate one")
        samples.append({"arm": "B", "candidate_id": identity, "question": value["question"].strip(),
                        "answer": value["answer"].strip(), "source_evidence": evidence[identity]["evidence"]})
        lineage.append({"candidate_id": identity, "production_decision": decision,
                        "raw_generation_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                        "evidence_raw_sha256": evidence[identity]["evidence_raw_sha256"]})
    output = run / "B-rejection-diagnostic"
    output.mkdir(exist_ok=False)
    with (output / "rejected-candidates.jsonl").open("x") as stream:
        stream.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in samples))
    judge.write_json(output / "private-lineage.json", lineage)
    judge.write_json(output / "scope.json", {
        "scope": "B_REJECTION_DIAGNOSTIC_SEPARATE_FROM_FINAL_OUTPUT_EVALUATION",
        "authority": "User: 同时也让 Astra 也评测一下拒绝的 9 条",
        "records": 9, "model": "gpt-6-astra", "reasoning_effort": "high",
        "same_rubric_as_main_evaluation": True,
        "hidden": ["arm", "production_rejection", "rejection_reason", "support_quotes", "internal_scores"],
        "interpretation": "A quality-qualified rejected QA is a potential rejection-loss signal, not proof that every production constraint should be removed. Keep original decisions and final exports unchanged.",
        "production_audit_sha256": judge.sha(run / "production-audit.jsonl"),
        "verifications_sha256": judge.sha(run / "B-production/verification.jsonl"),
        "runner_sha256": judge.sha(__file__), "Astra_usage_accounting": "excluded_by_user"})
    judge.prepare(output / "rejected-candidates.jsonl", output / "astra-evaluation")
    return output


def summarize(output):
    bundle = output / "astra-evaluation"
    completion = json.loads((bundle / "execution/completed.json").read_text())
    if completion["items"] != 9:
        raise ValueError("Incomplete diagnostic")
    mapping = json.loads((bundle / "private-map.json").read_text())
    lineage = {r["candidate_id"]: r for r in json.loads((output / "private-lineage.json").read_text())}
    judgments = []
    for row in mapping:
        result = json.loads((bundle / "execution" / row["opaque_sample_id"] / "result.json").read_text())
        judgments.append({**row, **result, "original_production_decision": lineage[row["candidate_id"]]["production_decision"]})
    summary = {"scope": "B_REJECTION_DIAGNOSTIC_ONLY", "assessed": 9,
               "quality_counts": dict(Counter(r["qualification"] for r in judgments)), "judgments": judgments,
               "note": "Do not include these candidates in original final-output quality, production yield or SFT export. No candidates reinstated."}
    judge.write_json(output / "diagnostic-summary.json", summary)
    print(json.dumps({k: v for k, v in summary.items() if k != "judgments"}, ensure_ascii=False, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    output = prepare(args.run.resolve())
    print("Prepared 9 rejected candidates; original final outputs unchanged", flush=True)
    if args.execute:
        judge.run(output / "astra-evaluation", execute=True)
        summarize(output)


if __name__ == "__main__":
    main()
