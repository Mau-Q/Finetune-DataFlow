"""Offline request-level checks. No application startup or real credentials."""

import copy
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.services.serving_params import expand_serving_configs


class ServingParamsTests(unittest.TestCase):
    def test_configs_expand_without_mutating_saved_record(self):
        source = {"model_name": "qwen3.7-plus", "configs": {"enable_thinking": False, "max_tokens": 2048}}
        original = copy.deepcopy(source)
        result = expand_serving_configs(source)
        self.assertNotIn("configs", result)
        self.assertIs(result["enable_thinking"], False)
        self.assertEqual(source, original)

    def test_legacy_string_and_empty_configs(self):
        self.assertEqual(expand_serving_configs({"configs": '{"max_tokens":3200}'}), {"max_tokens": 3200})
        for value in ({}, None, ""):
            self.assertEqual(expand_serving_configs({"configs": value}), {})

    def test_invalid_or_conflicting_configs_rejected(self):
        for value in ([], "{broken", "[]", {"api_key": "dummy"}, {"temperature": 1}):
            with self.subTest(value=type(value).__name__), self.assertRaises(ValueError):
                expand_serving_configs({"configs": value})

    def test_test_endpoint_and_engine_send_expected_provider_payloads(self):
        from app.api.v1.endpoints.serving import test_serving_instance
        from app.core.container import container
        from app.schemas.serving import ServingTestSchema
        from app.services.dataflow_engine import DataFlowEngine

        cases = [
            ("qwen3.7-plus", 0.2, 2048, {"enable_thinking": False}),
            ("deepseek-v4-pro", 0.0, 3200, {"thinking": {"type": "disabled"}}),
        ]
        response = Mock(status_code=200)
        response.json.return_value = {"choices": [{"message": {"content": '{"ok":true}'}, "finish_reason": "stop"}]}
        for model, temperature, budget, thinking in cases:
            params = {"api_url": "https://example.invalid/chat/completions", "model_name": model,
                      "api_key": "offline-dummy", "key_name_of_api_key": "DATAFLOW_OFFLINE_TEST_KEY",
                      "temperature": temperature, "max_workers": 1, "max_retries": 1,
                      "configs": {**thinking, "max_tokens": budget, "response_format": {"type": "json_object"}}}
            info = {"id": "offline", "name": "offline", "cls_name": "APILLMServing_request",
                    "params": [{"name": k, "value": v} for k, v in params.items()]}
            registry = SimpleNamespace(_get=lambda _: copy.deepcopy(info))
            with self.subTest(model=model), patch.object(container, "serving_registry", registry), patch.dict(os.environ), patch("requests.Session.post", return_value=response) as post:
                test_serving_instance("offline", ServingTestSchema(prompt="你好"))
                instance = DataFlowEngine().init_serving_instance("offline")
                instance.generate_from_input(['Return a JSON object: {"ok":true}'])
                instance.cleanup()
                self.assertEqual(post.call_count, 2)
                for call in post.call_args_list:
                    payload = json.loads(call.kwargs["data"])
                    self.assertNotIn("configs", payload)
                    self.assertEqual(payload["model"], model)
                    self.assertEqual(payload["temperature"], temperature)
                    self.assertEqual(payload["max_tokens"], budget)
                    self.assertEqual(payload["response_format"], {"type": "json_object"})
                    for key, value in thinking.items():
                        self.assertEqual(payload[key], value)
                test_payload = json.loads(post.call_args_list[0].kwargs["data"])
                self.assertIn("JSON", test_payload["messages"][-1]["content"])


if __name__ == "__main__":
    unittest.main()
