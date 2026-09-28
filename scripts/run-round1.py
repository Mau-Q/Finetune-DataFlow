"""Bounded Round 1 orchestration of existing DataFlow operators; opt-in live run."""
import argparse
from collections import Counter
import importlib.util
import json
import math
from pathlib import Path
from types import SimpleNamespace

import yaml
from dataflow.operators.text_sft import SFTGeneratorSeed, AlpagasusFilter
from paper_dataflow.baseline import quality as q
from paper_dataflow.baseline.gateway import OpenAICompatibleModelGateway
from paper_dataflow.operators.paper.generate.sft2000 import (
    gateway_for, observe, finalize_generation, tokenizer_at, check_evidence,
    SFT2000Verifier, SFT2000Exporter, persist,
)
from paper_dataflow.pipelines.round1_prepare import (
    CUSTOM_PROMPT, MemoryStorage, build_requests, read_jsonl, write_jsonl, write_new,
)

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data/round1/development-structured-reviewed"


def load_servings():
    # Read existing local credentials in memory only; never log the registry or keys.
    registry = yaml.safe_load((ROOT / "repos/dataflow-webui/backend/data/serving_registry.yaml").read_text())
    output = []
    for identity in ("a9885c5b9907017b", "99e05909b12873c2"):
        values = {p["name"]: p.get("value", p.get("default_value")) for p in registry[identity]["params"]}
        configs = dict(values["configs"])
        configs["temperature"] = values["temperature"]
        output.append(SimpleNamespace(api_url=values["api_url"], api_key=values["api_key"],
            model_name=values["model_name"], configs=configs,
            timeout=(values["connect_timeout"], values["read_timeout"]), max_retries=values["max_retries"]))
    if output[0].api_url != "https://maas.qianwenaiapi.com/compatible-mode/v1/chat/completions" or output[1].api_url != "https://api.deepseek.com/chat/completions":
        raise ValueError("Serving endpoint changed")
    for serving in output:
        if not serving.api_key:
            raise ValueError("Missing saved credentials")
    return output


def sha(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def preflight():
    records = read_jsonl(INPUT / "shared-evidence.jsonl")
    requests = read_jsonl(INPUT / "requests.jsonl")
    manifest = json.loads((INPUT / "manifest.json").read_text())
    for name, digest in manifest["artifact_sha256"].items():
        if sha(INPUT / name) != digest:
            raise ValueError("Prepared artifact changed: " + name)
    for name, digest in manifest["source_sha256"].items():
        if sha(ROOT / name) != digest:
            raise ValueError("Preparation source changed: " + name)
    if len(records) != 11 or len(requests) != 22:
        raise ValueError("Expected frozen 11 paired inputs")
    rebuilt = [request for row in records for request in build_requests(row)]
    if rebuilt != requests:
        raise ValueError("Official/original prompts differ from frozen requests")
    # train is the legacy adapter's protocol field, not permission for training.
    records = [{**r, "split": "train"} for r in records]
    check_evidence(records, 11)
    generator, verifier = load_servings()
    gateway_for(generator, "generator")
    gateway_for(verifier, "verifier")
    tokenizer_at(ROOT / "models/tokenizers/Qwen3.6-27B-6a9e13bd")
    return records, requests, generator, verifier


class RecordedServing:
    """Adapt the official operator to the existing audited, bounded gateway."""
    def __init__(self, gateway, output):
        self.gateway, self.output = gateway, output
        self.record = self.expected_messages = self.role = self.observation = None

    def generate_from_input(self, user_inputs, **kwargs):
        if len(user_inputs) != 1:
            raise ValueError("One sample per operator invocation")
        messages = [{"role": "system", "content": "You are a helpful assistant"},
                    {"role": "user", "content": user_inputs[0]}]
        if self.expected_messages is not None and messages != self.expected_messages:
            raise ValueError("Official prompt drift before paid call")
        persist(self.output / "production-requests.jsonl", {
            "arm": "A", "stage": self.role, "candidate_id": self.record["candidate_id"], "messages": messages})
        self.observation = observe(self.gateway, messages, self.record, self.role)
        persist(self.output / "observations.jsonl", {"arm": "A", "stage": self.role,
            "candidate_id": self.record["candidate_id"], **self.observation})
        require_transport(self.observation, "qwen3.7-plus")
        return [self.observation["raw_response"]]


def require_transport(observation, model):
    if observation.get("error_payload") or observation.get("actual_model") != model:
        raise RuntimeError("Transport/model identity failure; preserved observation; no further calls")


def evaluate_production(output, records, requests, generator, verifier):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    paths = [Path(__file__), ROOT / "scripts/astra-quality-eval.py", ROOT / "pipelines/astra-quality-rubric.md",
             ROOT / "data/round1/evaluation-contract.json"]
    paths += list((ROOT / "extensions/paper-dataflow/paper_dataflow/baseline").glob("*.py"))
    paths += [ROOT / "extensions/paper-dataflow/paper_dataflow/operators/paper/generate/sft2000.py",
              ROOT / "extensions/paper-dataflow/paper_dataflow/pipelines/round1_prepare.py",
              ROOT / "repos/dataflow/dataflow/prompts/general_text.py"]
    paths += [ROOT / "repos/dataflow/dataflow/operators/text_sft" / p for p in (
        "generate/sft_generator_from_seed.py", "filter/alpagasus_filter.py", "eval/alpagasus_sample_evaluator.py")]
    write_new(output / "manifest.json", {"status": "STARTED", "inputs": 11, "generation_requests": 22,
        "A": "SFTGeneratorSeed + AlpagasusFilter(quality, inclusive 3..5), Qwen scoring",
        "B": "Original generation, original DeepSeek production verification and exporter",
        "production_max_http_attempts": 55, "production_max_output_tokens_across_attempts": 126720,
        "A_filter_profile": {"model": "qwen3.7-plus", "temperature": 0, "max_tokens": 1024,
                             "enable_thinking": False, "response_format": "text", "attempts": 1},
        "generation_payloads_sha256": sha(INPUT / "requests.jsonl"),
        "shared_evidence_sha256": sha(INPUT / "shared-evidence.jsonl"),
        "code_and_contract_sha256": {str(p.relative_to(ROOT)): sha(p) for p in paths},
        "user_authorization": "进行并启动实验", "Astra_usage_accounting": "excluded_by_user",
        "split_note": "Legacy train adapter field only; all records remain development; no training authorized"})
    gen_gateway = gateway_for(generator, "generator")
    filter_gateway = OpenAICompatibleModelGateway(base_url=gen_gateway.base_url, api_key=generator.api_key,
        model_name="qwen3.7-plus", temperature=0, timeout=60, response_format="text",
        enable_thinking=False, max_output_tokens=1024, transport_retries=0)
    a_serving, filter_serving = RecordedServing(gen_gateway, output), RecordedServing(filter_gateway, output)
    op_generate_step1 = SFTGeneratorSeed(a_serving, CUSTOM_PROMPT)
    op_filter_step2 = AlpagasusFilter(min_score=3, max_score=5, llm_serving=filter_serving, dimension="quality")
    op_verify_step2 = SFT2000Verifier(verifier)
    op_export_step3 = SFT2000Exporter(str(output / "B-export"))
    tokenizer = tokenizer_at(ROOT / "models/tokenizers/Qwen3.6-27B-6a9e13bd")
    by_id = {r["candidate_id"]: r for r in records}
    a_candidates, b_rows, audits, exports = [], [], [], []
    for index, request in enumerate(requests, 1):
        record = by_id[request["candidate_id"]]
        arm = request["arm"]
        if arm == "A":
            a_serving.record, a_serving.role = record, "A_generator"
            a_serving.expected_messages = request["payload"]["messages"]
            a_serving.observation = None
            storage = MemoryStorage([{"raw_content": record["evidence"]}])
            result = op_generate_step1.run(storage, input_key="raw_content")
            if a_serving.observation:
                require_transport(a_serving.observation, "qwen3.7-plus")
                if a_serving.observation["request_sha256"] != request["payload_sha256"]:
                    raise ValueError("Actual generation payload differs from frozen request")
            if result is None:
                raise RuntimeError("Official generator failed; stopping")
            generated = storage.frame.to_dict("records")
            if len(generated) == 1 and all(isinstance(generated[0].get(k), str) and generated[0][k].strip() for k in ("instruction", "output")):
                a_candidates.append((record, generated[0]))
            else:
                audits.append({"arm": "A", "candidate_id": record["candidate_id"], "decision": "PROTOCOL_ERROR", "stage": "GENERATION"})
        else:
            messages = request["payload"]["messages"]
            persist(output / "production-requests.jsonl", {"arm": "B", "stage": "B_generator",
                "candidate_id": record["candidate_id"], "messages": messages})
            observation = observe(gen_gateway, messages, record, "B_generator")
            persist(output / "observations.jsonl", {"arm": "B", "stage": "B_generator",
                "candidate_id": record["candidate_id"], **observation})
            require_transport(observation, "qwen3.7-plus")
            if observation["request_sha256"] != request["payload_sha256"]:
                raise ValueError("Actual generation payload differs from frozen request")
            result = finalize_generation(observation, record, tokenizer)
            result["run_dir"] = str(output / "B-production")
            b_rows.append({"evidence_record": record, "generation_result": result})
        persist(output / "generation-progress.jsonl", {"request_id": request["request_id"], "arm": arm, "index": index})
        print(f"Generation {index}/22: {arm}", flush=True)
    for record, generated in a_candidates:
        filter_serving.record, filter_serving.role = record, "A_filter"
        storage = MemoryStorage([{**generated, "evidence_input": record["evidence"]}])
        decision, reason = "REJECT", "ALPAGASUS_BELOW_THRESHOLD"
        try:
            op_filter_step2.run(storage, input_instruction_key="instruction", input_input_key="evidence_input", input_output_key="output")
            score = float(filter_serving.observation["raw_response"].strip().split("\n")[0].split()[0])
            if not math.isfinite(score) or not 0 <= score <= 5:
                raise ValueError("Invalid score")
            if len(storage.frame):
                decision, reason = "PASS", "ALPAGASUS_3_TO_5"
                exports.append({"arm": "A", "candidate_id": record["candidate_id"], "question": generated["instruction"],
                                "answer": generated["output"], "source_evidence": record["evidence"]})
        except (ValueError, IndexError):
            score, decision, reason = None, "PROTOCOL_ERROR", "ALPAGASUS_SCORE_PARSE_ERROR"
        audits.append({"arm": "A", "candidate_id": record["candidate_id"], "decision": decision,
                       "stage": "PRODUCTION_FILTER", "score": score, "reason": reason})
        persist(output / "A-production.jsonl", audits[-1])
        print(f"A filter: {decision}", flush=True)
    # Original B operator preserves rejection/review semantics and does not regenerate.
    verified = []
    for row in b_rows:
        storage = MemoryStorage([row])
        op_verify_step2.run(storage)
        verified_row = storage.frame.to_dict("records")[0]
        result = verified_row["verification_result"]
        observation = result.get("verifier_observation")
        if observation:
            require_transport(observation, "deepseek-v4-pro")
        verified.append(verified_row)
        print(f"B production: {result['quality_decision']}", flush=True)
    storage = MemoryStorage(verified)
    op_export_step3.run(storage)
    for row in storage.frame.to_dict("records"):
        record, status = row["evidence_record"], row["export_status"]
        audits.append({"arm": "B", **status})
        if status["decision"] == "PASS":
            qa = row["verification_result"]["generated"]
            exports.append({"arm": "B", "candidate_id": record["candidate_id"], "question": qa["question"],
                            "answer": qa["answer"], "source_evidence": record["evidence"]})
    write_jsonl(output / "final-exports.jsonl", exports)
    write_jsonl(output / "production-audit.jsonl", audits)
    for arm in ("A", "B"):
        write_jsonl(output / f"SFT-{arm}.jsonl", [{"instruction": e["question"], "input": e["source_evidence"], "output": e["answer"]} for e in exports if e["arm"] == arm])
    calls = gen_gateway.call_records + filter_gateway.call_records + op_verify_step2.gateway.call_records
    write_jsonl(output / "production-call-records.jsonl", calls)
    if len(calls) > 55:
        raise ValueError("Production request ceiling exceeded")
    usage = {}
    for arm in ("A", "B"):
        selected = [c for c in calls if (c.get("stage") or "").startswith(arm + "_") or (arm == "B" and c.get("stage") == "verifier")]
        counts = Counter()
        for call in selected:
            counts.update({k: v for k, v in call.get("usage", {}).items() if isinstance(v, (int, float))})
        usage[arm] = {"http_attempts": len(selected), "reported_usage": dict(counts), "currency_cost": None,
                      "cost_note": "No verified provider/account tariff; report measured production usage, do not invent currency cost"}
    summary = {"status": "PRODUCTION_COMPLETE", "input_per_arm": 11,
        "final_counts": dict(Counter(e["arm"] for e in exports)),
        "decisions": {arm: dict(Counter(a["decision"] for a in audits if a["arm"] == arm)) for arm in ("A", "B")},
        "production_resources": usage, "final_exports_sha256": sha(output / "final-exports.jsonl")}
    write_new(output / "production-summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    inputs = preflight()
    if not args.execute:
        print("PREFLIGHT_PASS; no model call; 11 paired inputs; at most 55 production HTTP attempts")
        return
    try:
        summary = evaluate_production(args.output.resolve(), *inputs)
        print(json.dumps(summary, ensure_ascii=False), flush=True)
        spec = importlib.util.spec_from_file_location("astra_judge", ROOT / "scripts/astra-quality-eval.py")
        judge = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(judge)
        judge.prepare(args.output / "final-exports.jsonl", args.output / "astra-evaluation")
        print("Starting Astra high independent evaluation", flush=True)
        print(json.dumps(judge.run(args.output / "astra-evaluation", execute=True), ensure_ascii=False), flush=True)
    except Exception as error:
        if args.output.exists():
            persist(args.output / "failures.jsonl", {"type": type(error).__name__, "message": str(error)})
        raise


if __name__ == "__main__":
    main()
