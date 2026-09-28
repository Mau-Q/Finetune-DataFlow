"""Recorded provider replay for Round 1 orchestration; no network."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import paper_dataflow.operators.paper.generate.sft2000 as legacy

spec = importlib.util.spec_from_file_location("round1_runner", Path(__file__).with_name("run-round1.py"))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class Round1Tests(unittest.TestCase):
    def replay(self, score):
        root = runner.ROOT
        manifest = json.loads((root / "data/sft2000/manifest.json").read_text())
        with (Path(manifest["checkpoint"]) / "audit.jsonl").open() as f:
            audit = json.loads(next(f))["semantic_result"]
        record = runner.read_jsonl(root / "data/sft2000/evidence-smoke3.jsonl")[0]["evidence_record"]
        generator, verifier = runner.load_servings()
        calls = []
        def transport(request, timeout):
            payload = json.loads(request.data)
            calls.append(payload)
            if payload["model"] == "deepseek-v4-pro":
                raw = audit["verifier_observation"]["raw_response"]
            elif payload["response_format"]["type"] == "text":
                raw = score
            elif payload["messages"] == runner.q.generator_messages(record):
                raw = audit["generator_observation"]["raw_response"]
            else:
                raw = json.dumps({"instruction": "离线问题", "output": "离线回答"})
            return io.BytesIO(json.dumps({"model": payload["model"], "usage": {"prompt_tokens": 8, "completion_tokens": 5, "total_tokens": 13},
                "choices": [{"message": {"content": raw}, "finish_reason": "stop"}]}).encode())
        original = legacy.gateway_for
        gateway_cls = runner.OpenAICompatibleModelGateway
        def factory(*args):
            result = original(*args)
            result.transport = transport
            return result
        def filter_factory(**kwargs):
            return gateway_cls(**kwargs, transport=transport)
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(runner, "gateway_for", side_effect=factory), \
             patch.object(legacy, "gateway_for", side_effect=factory), \
             patch.object(runner, "OpenAICompatibleModelGateway", side_effect=filter_factory):
            output = Path(directory) / "run"
            summary = runner.evaluate_production(output, [record], runner.build_requests(record), generator, verifier)
            exports = runner.read_jsonl(output / "final-exports.jsonl")
            audits = runner.read_jsonl(output / "production-audit.jsonl")
        return summary, exports, audits, calls

    def test_native_operators_export_both_arms_and_account_production_only(self):
        summary, exports, audits, calls = self.replay("4\nGood")
        self.assertEqual(summary["final_counts"], {"A": 1, "B": 1})
        self.assertEqual(len(calls), 4)
        self.assertEqual({e["arm"] for e in exports}, {"A", "B"})
        self.assertEqual(sum(v["http_attempts"] for v in summary["production_resources"].values()), 4)

    def test_bad_filter_response_preserved_not_accepted(self):
        summary, exports, audits, calls = self.replay("not a score")
        self.assertEqual(summary["final_counts"], {"B": 1})
        self.assertEqual([r["decision"] for r in audits if r["arm"] == "A"], ["PROTOCOL_ERROR"])
        self.assertEqual(len(calls), 4)

    def test_prompt_drift_stops_before_model_call(self):
        serving = runner.RecordedServing(None, Path("/unused"))
        serving.expected_messages = []
        with patch.object(runner, "observe", side_effect=AssertionError("No call")):
            with self.assertRaisesRegex(ValueError, "prompt drift"):
                serving.generate_from_input(["changed"])


if __name__ == "__main__":
    unittest.main()
