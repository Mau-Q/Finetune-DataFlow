"""Summarize completed production and independent judgments without new calls."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().split("\n") if line.strip()]


def summarize(root):
    production = json.loads((root / "production-summary.json").read_text())
    export_path = root / "final-exports.jsonl"
    if hashlib.sha256(export_path.read_bytes()).hexdigest() != production["final_exports_sha256"]:
        raise ValueError("Final exports changed")
    exported = read_jsonl(export_path)
    bundle = root / "astra-evaluation"
    manifest = json.loads((bundle / "manifest.json").read_text())
    if manifest["source_export_sha256"] != production["final_exports_sha256"]:
        raise ValueError("Judge evaluated a different export")
    for name, expected in manifest["artifact_sha256"].items():
        if hashlib.sha256((bundle / name).read_bytes()).hexdigest() != expected:
            raise ValueError("Judge input changed: " + name)
    mapping = json.loads((bundle / "private-map.json").read_text())
    complete = json.loads((bundle / "execution/completed.json").read_text())
    if complete["items"] != len(exported) or len(mapping) != len(exported):
        raise ValueError("Incomplete evaluation")
    if {(r["arm"], r["candidate_id"]) for r in mapping} != {(r["arm"], r["candidate_id"]) for r in exported}:
        raise ValueError("Mapping mismatch")
    judgments = []
    for row in mapping:
        result = json.loads((bundle / "execution" / row["opaque_sample_id"] / "result.json").read_text())
        if result["assessment"]["opaque_sample_id"] != row["opaque_sample_id"]:
            raise ValueError("Judgment ID mismatch")
        judgments.append({**row, **result})
    arms = {}
    for arm in ("A", "B"):
        selected = [r for r in judgments if r["arm"] == arm]
        counts = Counter(r["qualification"] for r in selected)
        dimension_counts = {}
        for row in selected:
            for name, assessment in row["assessment"]["dimensions"].items():
                dimension_counts.setdefault(name, Counter())[assessment["verdict"]] += 1
        qualified = counts["QUALIFIED"]
        arms[arm] = {"attempted_inputs": 11, "final_outputs": len(selected),
            "quality_counts": dict(counts), "qualified_final_output_rate": qualified / len(selected) if selected else None,
            "qualified_yield_per_input": qualified / 11,
            "dimension_counts": {k: dict(v) for k, v in dimension_counts.items()},
            "question_types": dict(Counter(r["assessment"]["question_type"] for r in selected)),
            "production": production["production_resources"][arm],
            "production_decisions": production["decisions"][arm]}
    return {"status": "COMPLETE", "scope": "11 shared development chunks from 6 papers; not a generalization or training-effect result",
            "judge": "Codex CLI requested gpt-6-astra high; no independent backend version verification",
            "arms": arms, "judgments": judgments,
            "Astra_usage_and_cost": "excluded_by_user"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    args = parser.parse_args()
    report = summarize(args.run)
    with (args.run / "comparison.json").open("x") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    lines = ["# 第一轮 SFT 对照结果", "", "A：官方 Seed + Alpagasus 3–5；B：原生成、生产验证和过滤。",
             "最终质量：Codex CLI 请求 GPT Astra high，七维度均 MET 才合格。", "",
             "| 指标 | A | B |", "|---|---:|---:|"]
    a, b = report["arms"]["A"], report["arms"]["B"]
    for label, va, vb in [("共同输入",11,11), ("最终导出",a["final_outputs"],b["final_outputs"]),
        ("独立评估合格",a["quality_counts"].get("QUALIFIED",0),b["quality_counts"].get("QUALIFIED",0)),
        ("独立评估不合格",a["quality_counts"].get("NOT_QUALIFIED",0),b["quality_counts"].get("NOT_QUALIFIED",0)),
        ("独立评估不确定",a["quality_counts"].get("UNSURE",0),b["quality_counts"].get("UNSURE",0)),
        ("每条输入的合格产出率",f'{a["qualified_yield_per_input"]:.1%}',f'{b["qualified_yield_per_input"]:.1%}'),
        ("生产 HTTP 尝试",a["production"]["http_attempts"],b["production"]["http_attempts"])]:
        lines.append(f"| {label} | {va} | {vb} |")
    lines += ["", "生产货币成本未计算：尚无核实的账户费率；实际生产用量见 comparison.json。按用户要求排除 Astra 用量和费用。",
              "", "## 独立评估发现", ""]
    for row in report["judgments"]:
        failures = [(k, v) for k, v in row["assessment"]["dimensions"].items() if v["verdict"] != "MET"]
        if failures:
            lines.append(f'- {row["arm"]} / {row["candidate_id"]}: {row["qualification"]}')
            lines.extend(f'  - {k} ({v["verdict"]}): {v["reason"]}' for k, v in failures)
    lines += ["", "## 范围", "", "仅覆盖 6 篇论文的 11 条开发证据。两组最终数量受各自生产规则影响；此结果不能证明全库优势或微调后的能力提升。被生产拒绝的样本未混入最终质量评估，因此无法从本轮判断过滤误杀率。", ""]
    with (args.run / "REPORT.md").open("x") as stream:
        stream.write("\n".join(lines))
    print(json.dumps({"status": report["status"], "arms": report["arms"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
