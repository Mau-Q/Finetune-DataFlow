"""Offline gate ablations on frozen Round 1 responses; never call a model."""
import argparse
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import re
from unittest.mock import patch

from paper_dataflow.baseline import quality as q
from paper_dataflow.baseline.production import derive_production_terminal_fields
from paper_dataflow.operators.paper.generate.sft2000 import tokenizer_at
from paper_dataflow.pipelines.round1_prepare import read_jsonl, write_jsonl, write_new

ROOT = Path(__file__).resolve().parents[1]


def parse_seed_json(raw):
    """Whole JSON only; braces inside string values are not object delimiters."""
    text = raw.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*\n(.*?)\n```", text, re.S)
    if fenced:
        text = fenced.group(1)
    value = json.loads(text)
    if not isinstance(value, dict) or any(not isinstance(value.get(k), str) or not value[k].strip() for k in ("instruction", "output")):
        raise ValueError("Expected nonempty instruction/output strings")
    return value


def math_spans(text):
    return list(re.finditer(r"(?<!\\)\$(?!\$)(.*?)(?<!\\)\$", text, re.S))


def bold_view(text):
    """Whitespace-folded view and exact source offsets; only paired ** removed."""
    math_ranges = [(m.start(), m.end()) for m in math_spans(text)]
    removed = set()
    for match in re.finditer(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", text, re.S):
        if any(match.start() < end and match.end() > start for start, end in math_ranges):
            continue
        removed.update((match.start(), match.start() + 1, match.end() - 2, match.end() - 1))
    chars, spans = [], []
    for index, char in enumerate(text):
        if index in removed:
            continue
        if char.isspace():
            if chars and chars[-1] == " ":
                spans[-1] = (spans[-1][0], index + 1)
                continue
            char = " "
        chars.append(char)
        spans.append((index, index + 1))
    return "".join(chars), spans


def align_quote(quote, evidence):
    if q.exact_quote_in_evidence(quote, evidence):
        return {"mode": "ORIGINAL_MATCH", "source_quote": quote}
    target, _ = bold_view(quote.strip())
    source, spans = bold_view(evidence)
    if not target or source.count(target) != 1:
        return {"mode": "UNRESOLVED", "source_quote": None}
    start = source.index(target)
    a, b = spans[start][0], spans[start + len(target) - 1][1]
    return {"mode": "MARKDOWN_BOLD_ONLY", "source_quote": evidence[a:b], "source_start": a, "source_end": b}


def math_aliases(evidence):
    """Only literal Latin-base subscripts inside $...$, with source spans.

    No fuzzy matches, invented definitions, prose concatenation or semantic edits.
    Recognizes W_{ASR_{in}}, bold S_{i}, and spaced equivalents.
    """
    aliases = {}
    base = re.compile(r"(?:\\(?:mathbf|mathrm|mathit|text)\s*\{\s*([A-Za-z])\s*\}|(?<![A-Za-z\\])([A-Za-z]))\s*_\s*")
    for math in math_spans(evidence):
        body = math.group(1)
        consumed_until = 0
        for match in base.finditer(body):
            if match.start() < consumed_until:
                continue  # nested ASR_{in} belongs to W_{ASR_{in}}, not a new R_in
            pos = match.end()
            if pos >= len(body):
                continue
            end = pos
            if body[pos] == "{":
                depth = 0
                for end in range(pos, len(body)):
                    depth += (body[end] == "{") - (body[end] == "}")
                    if depth == 0:
                        break
                if depth:
                    continue
                sub = body[pos + 1:end]
                end += 1
            else:
                submatch = re.match(r"[A-Za-z0-9]+", body[pos:])
                if not submatch:
                    continue
                sub = submatch.group()
                end = pos + len(sub)
            sub = re.sub(r"[\s{}]", "", sub)
            if not re.fullmatch(r"[A-Za-z0-9]+(?:_[A-Za-z0-9]+)*", sub):
                continue
            alias = (match.group(1) or match.group(2)) + "_" + sub
            consumed_until = end
            a, b = math.start(1) + match.start(), math.start(1) + end
            aliases.setdefault(alias.casefold(), []).append({"alias": alias, "source_start": a, "source_end": b, "source_text": evidence[a:b]})
    return aliases


def audit(run, output):
    records = read_jsonl(ROOT / "data/round1/development-structured-reviewed/shared-evidence.jsonl")
    by_id = {r["candidate_id"]: r for r in records}
    b_rows = {r["candidate_id"]: r for r in read_jsonl(run / "B-production/verification.jsonl")}
    main = json.loads((run / "comparison.json").read_text())
    rejected = json.loads((run / "B-rejection-diagnostic/diagnostic-summary.json").read_text())
    judgments = {r["candidate_id"]: r["qualification"] for r in main["judgments"] + rejected["judgments"] if r["arm"] == "B"}
    tokenizer = tokenizer_at(ROOT / "models/tokenizers/Qwen3.6-27B-6a9e13bd")
    details = []
    for record in records:
        identity = record["candidate_id"]
        observed = b_rows[identity]
        value = json.loads(q.strip_json_fence(observed["generator_observation"]["raw_response"]))
        matches = [align_quote(quote, record["evidence"]) for quote in value["support_quotes"]]
        aliases = math_aliases(record["evidence"])
        checks = q.deterministic_semantic_checks(record["evidence"], value["answer"], value["question"])
        resolved = {reason: aliases[reason.split(":", 1)[1].casefold()] for reason in checks
                    if reason.startswith("UNBOUND_ASCII_TERM:") and reason.split(":", 1)[1].casefold() in aliases}
        prompt, answer = q.render_qwen36_parts(value["question"], record["evidence"], value["answer"])
        details.append({"candidate_id": identity, "original_decision": observed["quality_decision"],
            "original_stage": observed["stage"], "original_reasons": observed["reason_codes"],
            "astra_quality": judgments[identity], "quote_alignment": matches,
            "all_quotes_align_after_bold_removal": all(m["source_quote"] is not None for m in matches),
            "mixed_count": q.word_compatible_mixed_count(value["question"], record["evidence"], value["answer"]),
            "evidence_mixed_count": q.word_compatible_mixed_count(record["evidence"]),
            "qa_mixed_count": q.word_compatible_mixed_count(value["question"], value["answer"]),
            "qwen_tokens": tokenizer.count(prompt) + tokenizer.count(answer),
            "symbol_alias_resolutions": resolved,
            "remaining_deterministic_reasons": [r for r in checks if r not in resolved],
            "production_verifier_response_available": "verifier_observation" in observed})
    variants = []
    for name, markdown, remove_length, symbols in [
        ("baseline", False, False, False),
        ("markdown_only", True, False, False),
        ("symbol_aliases_only", False, False, True),
        ("remove_400_only_keep_4096", False, True, False),
        ("markdown_and_symbols", True, False, True),
        ("markdown_symbols_remove_400_keep_4096", True, True, True),
    ]:
        outcomes, accepted = [], []
        for detail in details:
            identity = detail["candidate_id"]
            record, observed = by_id[identity], b_rows[identity]
            value = json.loads(q.strip_json_fence(observed["generator_observation"]["raw_response"]))
            if markdown:
                value["support_quotes"] = [m["source_quote"] or old for m, old in zip(detail["quote_alignment"], value["support_quotes"])]
            try:
                with patch.object(q, "MAX_MIXED_COUNT", 10**12 if remove_length else 400):
                    generated, _ = q.validate_generated(json.dumps(value, ensure_ascii=False), record, tokenizer)
                if "semantic_verifier" not in observed:
                    decision, reasons = "NEEDS_PRODUCTION_VERIFICATION", ["NO_SAVED_VALIDATED_VERIFIER_RESPONSE"]
                else:
                    semantic = copy.deepcopy(observed["semantic_verifier"])
                    if symbols:
                        semantic["deterministic_semantic_checks"] = detail["remaining_deterministic_reasons"]
                    decision, reasons = q.aggregate_verifier(semantic)
                    updated = {**observed, "generated": generated, "quality_decision": decision, "reason_codes": reasons}
                    item = {**record, "semantic_result": updated}
                    decision, _, reasons, question_hash = derive_production_terminal_fields(item, accepted=accepted)
                    if decision == "PASS":
                        accepted.append({**item, "normalized_question_sha256": question_hash})
            except (q.GeneratorQualityReject, q.GeneratorProtocolError) as error:
                decision, reasons = "REJECT", [str(error)]
            outcomes.append({"candidate_id": identity, "decision": decision, "reasons": reasons,
                             "existing_astra_quality": judgments[identity]})
        variants.append({"variant": name, "counts": dict(Counter(r["decision"] for r in outcomes)),
                         "outcomes": outcomes, "interpretation": "Offline development replay, not a new production result or independent confirmation"})
    a_recovery = []
    for observation in read_jsonl(run / "observations.jsonl"):
        if observation["stage"] != "A_generator":
            continue
        try:
            parsed = parse_seed_json(observation["raw_response"])
            a_recovery.append({"candidate_id": observation["candidate_id"], "parse": "VALID_WHOLE_JSON",
                               "instruction": parsed["instruction"], "output": parsed["output"]})
        except (ValueError, TypeError):
            a_recovery.append({"candidate_id": observation["candidate_id"], "parse": "INVALID"})
    output.mkdir(parents=True, exist_ok=False)
    paths = [Path(__file__), run / "production-audit.jsonl", run / "B-production/verification.jsonl",
             run / "comparison.json", run / "B-rejection-diagnostic/diagnostic-summary.json",
             run / "observations.jsonl", ROOT / "data/round1/development-structured-reviewed/shared-evidence.jsonl"]
    write_new(output / "manifest.json", {"scope": "OFFLINE_DEVELOPMENT_ABLATION", "new_model_calls": 0,
        "original_outputs_modified": False, "source_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        "label_boundary": "Previously seen Astra labels used for development diagnosis only; they cannot provide independent validation of rules designed after seeing them."})
    write_jsonl(output / "gate-details.jsonl", details)
    write_new(output / "ablations.json", variants)
    write_jsonl(output / "A-parser-replay.jsonl", a_recovery)
    print(json.dumps({"A_valid_json": sum(r["parse"] == "VALID_WHOLE_JSON" for r in a_recovery),
                      "variants": [{k: v for k, v in r.items() if k != "outcomes"} for r in variants]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    audit(args.run.resolve(), args.output.resolve())
