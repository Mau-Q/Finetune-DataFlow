"""Freeze LIMA shared evidence and run the unchanged SFT-2000 production logic.

Preparation has no model calls. Execution writes each observation before moving
to the next request; a failed or interrupted run is never silently resumed.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace

import yaml

from paper_dataflow.baseline import quality as q
from paper_dataflow.operators.paper.generate.sft2000 import (
    SFT2000Exporter, SFT2000Verifier, check_evidence, finalize_generation,
    gateway_for, observe, persist, tokenizer_at,
)
from paper_dataflow.pipelines.round1_prepare import MemoryStorage


ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "repos/dataflow-webui/backend/cache_local/653343528759_output"
PAPER_SHA256 = "759ddebaa24a03ee772a70d3a0ecc546f53310f209de0f8f6052a3dddb289144"
PAPER_ID = "2305.11206"
LEGACY_LENGTH_SENTENCE = "8. 完整 instruction + input + answer 不超过 400 个中英文混合计数单位和 4096 个 Qwen token。"
VARIANT_LENGTH_SENTENCE = "8. 完整 instruction + input + answer 不设中英文混合计数单位上限；仍须不超过 4096 个 Qwen token。"


def load_servings():
    """Read the existing saved credentials in memory without logging them."""
    registry = yaml.safe_load((ROOT / "repos/dataflow-webui/backend/data/serving_registry.yaml").read_text())
    output = []
    for identity in ("a9885c5b9907017b", "99e05909b12873c2"):
        values = {p["name"]: p.get("value", p.get("default_value")) for p in registry[identity]["params"]}
        configs = dict(values["configs"])
        configs["temperature"] = values["temperature"]
        if not values["api_key"]:
            raise ValueError("Missing saved serving credential")
        output.append(SimpleNamespace(api_url=values["api_url"], api_key=values["api_key"],
                         model_name=values["model_name"], configs=configs,
                         timeout=(values["connect_timeout"], values["read_timeout"]),
                         max_retries=values["max_retries"]))
    return output


def variant_messages(record):
    messages = q.generator_messages(record)
    if q.GENERATOR_SYSTEM_PROMPT.count(LEGACY_LENGTH_SENTENCE) != 1:
        raise ValueError("Frozen legacy prompt changed; cannot make bounded variant")
    messages[0]["content"] = messages[0]["content"].replace(LEGACY_LENGTH_SENTENCE, VARIANT_LENGTH_SENTENCE)
    payload = json.loads(messages[1]["content"])
    if payload.pop("full_record_mixed_count_max") != 400:
        raise ValueError("Legacy mixed-count payload changed")
    payload["experiment_variant"] = "no_mixed_count_limit"
    messages[1]["content"] = q.canonical_json(payload)
    return messages


def finalize_unbounded(observation, record, tokenizer):
    """Reuse the frozen validator with only its mixed-unit threshold disabled."""
    original = q.MAX_MIXED_COUNT
    try:
        q.MAX_MIXED_COUNT = math.inf
        return finalize_generation(observation, record, tokenizer)
    finally:
        q.MAX_MIXED_COUNT = original


def sha_bytes(value):
    return hashlib.sha256(value).hexdigest()


def sha_file(path):
    return sha_bytes(Path(path).read_bytes())


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def write_new(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def write_jsonl(path, rows):
    with Path(path).open("x", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def identity(row):
    meta = row["chunk_metadata"]
    return (row["source_page"]["page_number"], meta["chunk_index"],
            meta["char_start"], meta["char_end"])


def prepare(output):
    output.mkdir(parents=True, exist_ok=False)
    clean = read_jsonl(CACHE / "dataflow_cache_step_step4.jsonl")
    generated = read_jsonl(CACHE / "dataflow_cache_step_step7.jsonl")
    if len(clean) != 33 or len(generated) != 66:
        raise ValueError("LIMA cached row counts differ from frozen full-paper run")
    records = []
    evidence_index = {}
    for index, row in enumerate(clean, 1):
        key = identity(row)
        page = row["source_page"]
        meta = row["chunk_metadata"]
        if row["original_sha256"] != PAPER_SHA256 or page["document_id"] != PAPER_SHA256:
            raise ValueError(f"Source identity mismatch: {index}")
        if page["text"][meta["char_start"]:meta["char_end"]] != row["raw_chunk"]:
            raise ValueError(f"Source offset mismatch: {index}")
        evidence = row["cleaned_chunk"]
        if not isinstance(evidence, str) or not evidence.strip() or key in evidence_index:
            raise ValueError(f"Empty or duplicate evidence: {index}")
        candidate_id = f"lima-20260928-{index:02d}"
        record = {
            "candidate_id": candidate_id, "paper_id": PAPER_ID,
            "chunk_id": f"p{key[0]}-c{key[1]}", "chunk_sha256": sha_bytes(evidence.encode()),
            "domain": "AI_LLM", "split": "train", "evidence": evidence,
            "evidence_raw_sha256": sha_bytes(evidence.encode()),
            "evidence_sha256": sha_bytes(q.normalized(evidence).encode()),
            "source_pdf_sha256": PAPER_SHA256, "source_page": key[0],
            "source_char_start": key[2], "source_char_end": key[3],
            "source_raw_chunk_sha256": sha_bytes(row["raw_chunk"].encode()),
            "scope": "LIMA comparison only; train is legacy adapter protocol, not training admission",
        }
        records.append(record)
        evidence_index[key] = record
    check_evidence(records, 33)
    candidates = []
    per_evidence = Counter()
    for row in generated:
        key = identity(row)
        record = evidence_index.get(key)
        if record is None or row["cleaned_chunk"] != record["evidence"]:
            raise ValueError("Current pipeline candidate differs from frozen evidence")
        question, answer = row["question"], row["answer"]
        if not isinstance(question, str) or not question.strip() or not isinstance(answer, str) or not answer.strip():
            raise ValueError("Current pipeline candidate has empty QA")
        per_evidence[record["candidate_id"]] += 1
        candidates.append({"arm": "current_13", "candidate_id": record["candidate_id"],
                           "qa_index": per_evidence[record["candidate_id"]],
                           "question": question, "answer": answer,
                           "source_evidence": record["evidence"]})
    if sorted(per_evidence.values()) != [2] * 33:
        raise ValueError("Expected two current QA per evidence")
    write_jsonl(output / "shared-evidence.jsonl", records)
    write_jsonl(output / "current-candidates.jsonl", candidates)
    write_new(output / "manifest.json", {
        "status": "PREPARED_NO_MODEL_CALL", "source_pdf_sha256": PAPER_SHA256,
        "current_task_id": "653343528759", "current_qa_count": 66,
        "shared_evidence_count": 33,
        "source_cache_sha256": {f"step{n}": sha_file(CACHE / f"dataflow_cache_step_step{n}.jsonl") for n in (4, 7)},
        "artifacts_sha256": {name: sha_file(output / name) for name in ("shared-evidence.jsonl", "current-candidates.jsonl")},
        "runner_sha256": sha_file(__file__),
        "legacy_max_generator_calls": 33, "legacy_max_verifier_http_attempts": 66,
        "legacy_paper_export_cap": 3,
        "legacy_variant": "Original SFT-2000 prompt and validator except removed 400 mixed-unit ceiling; 4096 token gate remains",
        "split_note": "train is required by the frozen SFT-2000 adapter; LIMA comparison data is not admitted for training",
    })


def preflight(output):
    manifest = json.loads((output / "manifest.json").read_text())
    if manifest["runner_sha256"] != sha_file(__file__):
        raise ValueError("Runner changed after evidence freeze")
    for name, expected in manifest["artifacts_sha256"].items():
        if sha_file(output / name) != expected:
            raise ValueError(f"Frozen artifact changed: {name}")
    for step, expected in manifest["source_cache_sha256"].items():
        if sha_file(CACHE / f"dataflow_cache_step_{step}.jsonl") != expected:
            raise ValueError(f"Source cache changed: {step}")
    records = read_jsonl(output / "shared-evidence.jsonl")
    if len(records) != 33:
        raise ValueError("Expected 33 frozen evidence records")
    check_evidence(records, 33)
    generator, verifier = load_servings()
    gateway_for(generator, "generator")
    gateway_for(verifier, "verifier")
    tokenizer_at(ROOT / "models/tokenizers/Qwen3.6-27B-6a9e13bd")
    variant_messages(records[0])
    return records, generator, verifier


def execute(output):
    records, generator, verifier = preflight(output)
    run = output / "legacy-production"
    run.mkdir(exist_ok=False)
    write_new(run / "started.json", {"status": "STARTED", "manifest_sha256": sha_file(output / "manifest.json"),
                                     "input_count": len(records)})
    gen_gateway = gateway_for(generator, "generator")
    tokenizer = tokenizer_at(ROOT / "models/tokenizers/Qwen3.6-27B-6a9e13bd")
    rows = []
    for i, record in enumerate(records, 1):
        observation = observe(gen_gateway, variant_messages(record), record, "generator")
        persist(run / "generator-observations.jsonl", {"candidate_id": record["candidate_id"], **observation})
        if observation.get("error_payload") or observation.get("actual_model") != "qwen3.7-plus":
            raise RuntimeError(f"Generator transport/model failure at {record['candidate_id']}; no further calls")
        result = finalize_unbounded(observation, record, tokenizer)
        result["run_dir"] = str(run)
        persist(run / "generation.jsonl", {"candidate_id": record["candidate_id"], **result})
        rows.append({"evidence_record": record, "generation_result": result})
        print(f"Generation {i}/33: {result['quality_decision']}", flush=True)
    op_verifier = SFT2000Verifier(verifier)
    verified = []
    for i, row in enumerate(rows, 1):
        storage = MemoryStorage([row])
        op_verifier.run(storage)
        result = storage.frame.to_dict("records")[0]
        obs = result["verification_result"].get("verifier_observation")
        if obs and (obs.get("error_payload") or obs.get("actual_model") != "deepseek-v4-pro"):
            raise RuntimeError(f"Verifier transport/model failure at {row['evidence_record']['candidate_id']}; no further calls")
        verified.append(result)
        print(f"Verification {i}/33: {result['verification_result']['quality_decision']}", flush=True)
    storage = MemoryStorage(verified)
    SFT2000Exporter(str(run / "export")).run(storage)
    final = storage.frame.to_dict("records")
    write_jsonl(run / "final-rows.jsonl", final)
    candidates = []
    for row in rows:
        generated = row["generation_result"].get("generated")
        if generated:
            record = row["evidence_record"]
            candidates.append({"arm": "legacy_sft2000", "candidate_id": record["candidate_id"],
                               "qa_index": 1, "question": generated["question"],
                               "answer": generated["answer"], "source_evidence": record["evidence"]})
    write_jsonl(run / "legacy-candidates.jsonl", candidates)
    summary = saved_summary(output)
    write_new(run / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


def decision_counts(rows, field):
    return dict(Counter(str(row[field]) if row[field] is not None else "NONE" for row in rows))


def saved_summary(output):
    run = output / "legacy-production"
    generation = read_jsonl(run / "generation.jsonl")
    verification = read_jsonl(run / "verification.jsonl")
    final = read_jsonl(run / "final-rows.jsonl")
    candidates = read_jsonl(run / "legacy-candidates.jsonl")
    if not (len(generation) == len(verification) == len(final) == 33):
        raise ValueError("Saved production row count incomplete")
    return {"status": "PRODUCTION_COMPLETE", "inputs": 33,
            "generator_decisions": decision_counts(generation, "quality_decision"),
            "verification_decisions": decision_counts(verification, "quality_decision"),
            "export_decisions": decision_counts([r["export_status"] for r in final], "decision"),
            "legacy_candidate_count": len(candidates),
            "source_manifest_sha256": sha_file(output / "manifest.json"),
            "artifact_sha256": {name: sha_file(run / name) for name in
                                ("generation.jsonl", "verification.jsonl", "final-rows.jsonl", "legacy-candidates.jsonl")}}


def recover_summary(output):
    """Repair only the failed local summary write; never make model calls."""
    run = output / "legacy-production"
    old = json.loads((output / "manifest.json").read_text())["runner_sha256"]
    summary = saved_summary(output)
    path = run / "summary.json"
    try:
        json.loads(path.read_text())
    except (json.JSONDecodeError, FileNotFoundError):
        path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    else:
        raise ValueError("Existing summary is valid; no repair needed")
    write_new(run / "summary-repair.json", {"reason": "None decision key caused JSON key-sort error after export",
                                           "old_runner_sha256": old, "repair_runner_sha256": sha_file(__file__),
                                           "model_calls": 0, "summary_sha256": sha_file(path)})
    print("SUMMARY_REPAIRED_NO_MODEL_CALL", json.dumps(summary, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--recover-summary", action="store_true")
    args = parser.parse_args()
    if sum((args.prepare, args.execute, args.recover_summary)) != 1:
        parser.error("Choose exactly one of --prepare, --execute, or --recover-summary")
    output = args.output.resolve()
    if args.prepare:
        prepare(output)
        print("PREPARED_NO_MODEL_CALL: 33 paired evidence records, 66 current QA")
    elif args.execute:
        execute(output)
    else:
        recover_summary(output)


if __name__ == "__main__":
    main()
