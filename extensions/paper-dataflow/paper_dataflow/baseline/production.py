"""Vendored exact source segments; see vendor_manifest.json."""
from __future__ import annotations
from collections import Counter
from typing import Any
from . import quality as v3


MAX_ACCEPTED_PER_PAPER = v3.MAX_ACCEPTED_PER_PAPER


def normalized_question_hash(question: str) -> str:
    return v3.sha256_text(v3.normalized(question).casefold())


def derive_production_terminal_fields(
    item: dict[str, Any], *, accepted: list[dict[str, Any]]
) -> tuple[str, str, list[str], str | None]:
    semantic = item.get("semantic_result")
    if not isinstance(semantic, dict):
        raise ValueError("PRODUCTION_SEMANTIC_RESULT_MISSING")
    decision = semantic.get("quality_decision")
    terminal = "PROTOCOL_ERROR"
    stage = str(semantic.get("stage"))
    reasons = list(semantic.get("reason_codes") or [])
    question_hash: str | None = None
    if semantic.get("processing_status") == "COMPLETED" and decision in {
        "PASS",
        "REJECT",
        "REVIEW_REQUIRED",
    }:
        terminal = str(decision)
    if terminal == "PASS":
        paper_counts = Counter(str(row["paper_id"]) for row in accepted)
        if paper_counts[str(item["paper_id"])] >= MAX_ACCEPTED_PER_PAPER:
            terminal = "REJECT"
            stage = "PRODUCTION_PAPER_CAP"
            reasons = ["MAX_ACCEPTED_PER_PAPER_3"]
        else:
            question_hash = normalized_question_hash(str(semantic["generated"]["question"]))
            owners = {
                str(row["normalized_question_sha256"]): str(row["candidate_id"])
                for row in accepted
            }
            if question_hash in owners and owners[question_hash] != item["candidate_id"]:
                terminal = "REJECT"
                stage = "PRODUCTION_DETERMINISTIC_DEDUP"
                reasons = ["DUPLICATE_NORMALIZED_QUESTION"]
    return terminal, stage, reasons, question_hash if terminal == "PASS" else None


def checkpoint_rows(
    accepted: list[dict[str, Any]], identity: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    sft: list[dict[str, Any]] = []
    mapping: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    for index, item in enumerate(accepted, 1):
        semantic = item["semantic_result"]
        generated = semantic["generated"]
        record_id = f"production-sft-{index:04d}-{v3.sha256_text(str(item['candidate_id']))[:12]}"
        sft.append(
            {
                "instruction": generated["question"],
                "input": item["source_evidence"],
                "output": generated["answer"],
            }
        )
        mapping.append(
            {
                "record_id": record_id,
                "record_index": index,
                "candidate_id": item["candidate_id"],
                "paper_id": item["paper_id"],
                "chunk_id": item["chunk_id"],
                "chunk_sha256": item["chunk_sha256"],
                "domain": item["domain"],
                "normalized_question_sha256": item["normalized_question_sha256"],
                "run_identity_sha256": identity,
            }
        )
        audit.append(item)
    return sft, mapping, audit
