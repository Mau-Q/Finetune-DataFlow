"""Offline boundary tests for candidate parsing/alignment and recorded ablation."""
import importlib.util
import json
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("gate_audit", Path(__file__).with_name("audit-round1-gates.py"))
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class GateAuditTests(unittest.TestCase):
    def test_json_preserves_latex_braces_and_escaped_quotes(self):
        value = {"instruction": '解释 "任务向量"', "output": r"$\Delta W_{ASR}=W_{ASR}-W_{base}$"}
        raw = json.dumps(value, ensure_ascii=False)
        self.assertEqual(audit.parse_seed_json(raw), value)
        self.assertEqual(audit.parse_seed_json("```json\n" + raw + "\n```"), value)

    def test_json_does_not_accept_multiple_objects_or_invalid_fields(self):
        for raw in ['{"instruction":"q","output":"a"} {"output":"b"}',
                    '{"instruction":"q","output":null}', 'prefix {"instruction":"q","output":"a"}']:
            with self.assertRaises(ValueError):
                audit.parse_seed_json(raw)

    def test_bold_quote_alignment_returns_exact_original_span(self):
        source = "Before: a **trained hierarchy** over chunks. After."
        result = audit.align_quote("a trained hierarchy over chunks", source)
        self.assertEqual(result["mode"], "MARKDOWN_BOLD_ONLY")
        self.assertEqual(source[result["source_start"]:result["source_end"]], result["source_quote"])
        self.assertIn("**", result["source_quote"])
        self.assertTrue(audit.q.exact_quote_in_evidence(result["source_quote"], source))

    def test_quote_alignment_rejects_ellipsis_changed_words_and_ambiguity(self):
        source = "a **trained hierarchy** over chunks"
        for quote in ["a trained ... over chunks", "a learned hierarchy over chunks"]:
            self.assertEqual(audit.align_quote(quote, source)["mode"], "UNRESOLVED")
        self.assertEqual(audit.align_quote("a trained hierarchy over chunks", source + ". " + source)["mode"], "UNRESOLVED")
        self.assertEqual(audit.align_quote("$x2y$", "$x**2**y$")["mode"], "UNRESOLVED")

    def test_math_aliases_are_source_bound_and_do_not_join_prose(self):
        source = r"$W _ { A S R _ { i n } }$, $\mathbf { S } _ { i }$; prose W _ {fake}."
        aliases = audit.math_aliases(source)
        self.assertEqual(set(aliases), {"w_asr_in", "s_i"})
        self.assertNotIn("w_asr_out", aliases)
        for items in aliases.values():
            for item in items:
                self.assertEqual(source[item["source_start"]:item["source_end"]], item["source_text"])
        self.assertEqual(audit.math_aliases(r"$W_{i+1}$ $\alpha_i$"), {})

    def test_baseline_replay_matches_all_original_decisions(self):
        root = audit.ROOT
        results = json.loads((root / "outputs/round1-gate-ablation-20260922-checked/ablations.json").read_text())
        baseline = next(r for r in results if r["variant"] == "baseline")
        original = {r["candidate_id"]: r["decision"] for r in audit.read_jsonl(root / "outputs/round1-live-20260922/production-audit.jsonl") if r["arm"] == "B"}
        self.assertEqual({r["candidate_id"]: r["decision"] for r in baseline["outcomes"]}, original)
        symbolic = next(r for r in results if r["variant"] == "symbol_aliases_only")
        self.assertEqual(symbolic["counts"], {"REJECT": 7, "PASS": 4})
        self.assertEqual(sum(r["decision"] == "NEEDS_PRODUCTION_VERIFICATION" for r in next(r for r in results if r["variant"] == "markdown_only")["outcomes"]), 1)


if __name__ == "__main__":
    unittest.main()
