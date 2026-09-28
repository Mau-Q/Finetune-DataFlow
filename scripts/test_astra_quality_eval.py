"""Offline tests: no real Codex model invocation."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("astra_eval", Path(__file__).with_name("astra-quality-eval.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class JudgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.evidence = self.root / "evidence.jsonl"
        self.evidence.write_text(json.dumps({"candidate_id": "c1", "evidence": "Evidence 123."}) + "\n")
        self.source = self.root / "export.jsonl"
        self.source.write_text("\n".join(json.dumps({"arm": a, "candidate_id": "c1", "question": "What?",
            "answer": "123.", "source_evidence": "Evidence 123."}) for a in ("A", "B")) + "\n")
        self.bundle = self.root / "bundle"

    def prepare(self):
        module.prepare(self.source, self.bundle, self.evidence)
        return json.loads((self.bundle / "blind-input.json").read_text())

    def response(self, sample):
        return {"opaque_sample_id": sample["opaque_sample_id"],
                "dimensions": {k: {"verdict": "MET", "reason": "Supported."} for k in module.DIMENSIONS},
                "issue_evidence": [], "question_type": "quantitative", "difficulty": "basic"}

    def events(self):
        return [{"type": "turn.completed", "usage": {"input_tokens": 40, "output_tokens": 20}}]

    def test_blinding_and_default_no_execution(self):
        samples = self.prepare()
        self.assertEqual(len(samples), 2)
        for sample in samples:
            self.assertEqual(set(sample), {"opaque_sample_id", "question", "answer", "source_evidence"})
        self.assertNotIn("usage", module.validate_response(self.response(samples[0]), samples[0], self.events(), module.schema()))
        with patch.object(module.subprocess, "Popen", side_effect=AssertionError("No model calls")):
            self.assertEqual(module.run(self.bundle)["status"], "DRY_RUN_NO_MODEL_CALL")
        self.assertFalse((self.bundle / "execution").exists())

    def test_rejects_wrong_evidence_and_duplicate_exports(self):
        original = self.source.read_text()
        self.source.write_text(original.replace("Evidence 123.", "Other evidence."))
        with self.assertRaisesRegex(ValueError, "Evidence differs"):
            self.prepare()
        self.source.write_text(original + original)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.prepare()

    def test_rejects_artifact_and_runner_drift(self):
        self.prepare()
        rubric = self.bundle / "rubric.md"
        rubric.write_text(rubric.read_text() + "modified")
        with self.assertRaisesRegex(ValueError, "Frozen artifact changed"):
            module.run(self.bundle)
        manifest_path = self.bundle / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["runner_sha256"] = "tampered"
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "Runner/model drift"):
            module.run(self.bundle)

    def test_response_id_quote_schema_and_completion_checks(self):
        sample = self.prepare()[0]
        good = self.response(sample)
        self.assertEqual(module.validate_response(good, sample, self.events(), module.schema())["qualification"], "QUALIFIED")
        bad = self.response(sample)
        bad["opaque_sample_id"] = "wrong"
        with self.assertRaisesRegex(ValueError, "ID mismatch"):
            module.validate_response(bad, sample, self.events(), module.schema())
        bad = self.response(sample)
        bad["issue_evidence"] = [{"dimension": "answerability", "description": "x", "source_quote": "invented"}]
        with self.assertRaisesRegex(ValueError, "quote"):
            module.validate_response(bad, sample, self.events(), module.schema())
        bad = self.response(sample)
        bad["dimensions"].pop("answerability")
        with self.assertRaises(module.jsonschema.ValidationError):
            module.validate_response(bad, sample, self.events(), module.schema())
        for events in ([], self.events() * 2, self.events() + [{"type": "turn.failed"}],
                       self.events() + [{"type": "item.completed", "item": {"type": "command_execution"}}]):
            with self.assertRaises(ValueError):
                module.validate_response(good, sample, events, module.schema())

    def test_uncertainty_and_failure_not_counted_as_qualified(self):
        sample = self.prepare()[0]
        value = self.response(sample)
        value["dimensions"]["source_supported_facts"]["verdict"] = "UNSURE"
        self.assertEqual(module.validate_response(value, sample, self.events(), module.schema())["qualification"], "UNSURE")
        value["dimensions"]["answerability"]["verdict"] = "NOT_MET"
        self.assertEqual(module.validate_response(value, sample, self.events(), module.schema())["qualification"], "NOT_QUALIFIED")

    def test_startup_warning_is_not_model_tool_activity(self):
        sample = self.prepare()[0]
        warning = {"type": "item.completed", "item": {"type": "error", "message": "Code Mode is unavailable because code-mode host is disabled. Details"}}
        events = [warning, {"type": "turn.started"}, *self.events()]
        self.assertEqual(module.validate_response(self.response(sample), sample, events, module.schema())["qualification"], "QUALIFIED")
        with self.assertRaises(ValueError):
            module.validate_response(self.response(sample), sample, [{"type": "turn.started"}, warning, *self.events()], module.schema())

    def test_resume_saved_response_without_repeating_model_call(self):
        samples = self.prepare()
        execution = self.bundle / "execution"
        execution.mkdir()
        module.write_json(execution / "started.json", {"manifest_sha256": module.sha(self.bundle / "manifest.json")})
        first = execution / samples[0]["opaque_sample_id"]
        first.mkdir()
        module.write_json(first / "answer.json", self.response(samples[0]))
        (first / "events.jsonl").write_text("\n".join(json.dumps(e) for e in self.events()))
        module.write_json(first / "failure.json", {"type": "old_parser_rejection"})
        with patch.object(module.shutil, "which", return_value="/fake/codex"), \
             patch.object(module.subprocess, "Popen", side_effect=self.fake_cli) as calls:
            self.assertEqual(module.run(self.bundle, execute=True, resume=True)["status"], "COMPLETE")
            self.assertEqual(calls.call_count, 1)
        self.assertTrue((first / "failure.json").exists())
        self.assertTrue(json.loads((first / "result.json").read_text())["recovered_from_saved_response"])

    def fake_cli(self, args, **kwargs):
        test = self
        class Process:
            returncode = 0
            def communicate(self, prompt, timeout):
                sample = json.loads(prompt.split("\nSAMPLE_JSON\n", 1)[1])
                self_sample = test.response(sample)
                Path(args[args.index("--output-last-message") + 1]).write_text(json.dumps(self_sample))
                for event in test.events():
                    kwargs["stdout"].write(json.dumps(event) + "\n")
        return Process()

    def test_full_mock_execution_and_no_accidental_replay(self):
        self.prepare()
        with patch.object(module.shutil, "which", return_value="/fake/codex"), \
             patch.object(module.subprocess, "check_output", return_value="mock-cli-version"), \
             patch.object(module.subprocess, "Popen", side_effect=self.fake_cli) as calls:
            self.assertEqual(module.run(self.bundle, execute=True)["status"], "COMPLETE")
            self.assertEqual(calls.call_count, 2)
            with self.assertRaises(FileExistsError):
                module.run(self.bundle, execute=True)
            self.assertEqual(calls.call_count, 2)
        self.assertEqual(len(list((self.bundle / "execution").glob("*/result.json"))), 2)

    def test_runtime_failure_stops_no_retry(self):
        self.prepare()
        with patch.object(module.shutil, "which", return_value="/fake/codex"), \
             patch.object(module.subprocess, "check_output", return_value="mock-cli-version"), \
             patch.object(module.subprocess, "Popen", side_effect=OSError("mock failure")) as calls:
            with self.assertRaises(OSError):
                module.run(self.bundle, execute=True)
            self.assertEqual(calls.call_count, 1)
        self.assertEqual(len(list((self.bundle / "execution").glob("*/failure.json"))), 1)
        self.assertFalse((self.bundle / "execution/completed.json").exists())

    def test_timeout_terminates_process_group_and_records_failure(self):
        self.prepare()
        class TimeoutProcess:
            pid = 12345
            def communicate(self, *args, **kwargs):
                raise subprocess.TimeoutExpired("mock-codex", 600)
            def wait(self, **kwargs):
                return -15
        with patch.object(module.shutil, "which", return_value="/fake/codex"), \
             patch.object(module.subprocess, "check_output", return_value="mock-cli-version"), \
             patch.object(module.subprocess, "Popen", return_value=TimeoutProcess()) as calls, \
             patch.object(module.os, "killpg") as kill:
            with self.assertRaises(subprocess.TimeoutExpired):
                module.run(self.bundle, execute=True)
            self.assertEqual(calls.call_count, 1)
            kill.assert_called_once_with(12345, module.signal.SIGTERM)
        self.assertEqual(len(list((self.bundle / "execution").glob("*/failure.json"))), 1)

    def test_empty_export_no_model_call(self):
        self.source.write_text("")
        self.prepare()
        with patch.object(module.shutil, "which", return_value="/fake/codex"), \
             patch.object(module.subprocess, "check_output", return_value="mock-cli-version"), \
             patch.object(module.subprocess, "Popen", side_effect=AssertionError("No model calls")):
            self.assertEqual(module.run(self.bundle, execute=True)["status"], "EMPTY_EXPORT_NO_QUALITY_ESTIMATE")


if __name__ == "__main__":
    unittest.main()
