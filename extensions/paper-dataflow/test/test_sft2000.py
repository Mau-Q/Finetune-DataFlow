"""Frozen response replay plus failure/transport contracts; never call a provider."""
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
import pandas as pd
from paper_dataflow.baseline import quality as q
from paper_dataflow.baseline.production import derive_production_terminal_fields
from paper_dataflow.baseline.gateway import OpenAICompatibleModelGateway
from paper_dataflow.operators.paper.generate.sft2000 import (
    PROFILES, SFT2000Generator, SFT2000Verifier, SFT2000Exporter,
    check_evidence, finalize_generation, gateway_for, tokenizer_at,
)

ROOT = Path(__file__).resolve().parents[3]


class Storage:
    def __init__(self, rows):
        self.frame = pd.DataFrame(rows)
    def read(self, kind):
        return self.frame.copy()
    def write(self, frame):
        self.frame = frame


def serving(role):
    p = PROFILES[role]
    return SimpleNamespace(model_name=p['model'], configs=copy.deepcopy(p['configs']),
        timeout=(10, p['timeout']), max_retries=p['attempts'], api_key='offline-test',
        api_url='https://provider.invalid/v1/chat/completions')


@unittest.skipUnless((ROOT / 'data/sft2000/manifest.json').is_file(),
                     'Historical SFT2000 replay dataset is not included in a fresh checkout')
class Contracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        m = json.loads((ROOT / 'data/sft2000/manifest.json').read_text())
        with (Path(m['checkpoint']) / 'audit.jsonl').open() as stream:
            cls.audit = json.loads(next(stream))
        with (ROOT / 'data/sft2000/evidence-smoke3.jsonl').open() as stream:
            cls.record = json.loads(next(stream))['evidence_record']
        cls.tokenizer = tokenizer_at(ROOT / 'models/tokenizers/Qwen3.6-27B-6a9e13bd')

    def test_integrity_budget_and_split_before_calls(self):
        with self.assertRaisesRegex(ValueError, 'budget'):
            check_evidence([self.record] * 4, 3)
        bad = {**self.record, 'evidence': self.record['evidence'] + ' changed'}
        with self.assertRaisesRegex(ValueError, 'integrity'):
            check_evidence([bad], 3)
        with self.assertRaisesRegex(ValueError, 'train'):
            check_evidence([{**self.record, 'split': 'test'}], 3)

    def test_model_identity_and_generator_skip(self):
        observation = dict(self.audit['semantic_result']['generator_observation'])
        observation['actual_model'] = 'wrong-model'
        result = finalize_generation(observation, self.record, self.tokenizer)
        self.assertEqual(result['reason_codes'], ['GENERATOR_ACTUAL_MODEL_MISMATCH'])
        observation.update(actual_model='qwen3.7-plus', raw_response='{"status":"SKIP","reason":"Insufficient evidence"}')
        self.assertEqual(finalize_generation(observation, self.record, self.tokenizer)['quality_decision'], 'SKIP')

    def test_bad_quote_and_length_gate(self):
        observation = dict(self.audit['semantic_result']['generator_observation'])
        raw = json.loads(q.strip_json_fence(observation['raw_response']))
        raw['support_quotes'] = ['A fabricated quotation that is not in the source.']
        observation['raw_response'] = json.dumps(raw)
        self.assertEqual(finalize_generation(observation, self.record, self.tokenizer)['quality_decision'], 'REJECT')
        raw['support_quotes'] = self.audit['semantic_result']['generated']['support_quotes']
        raw['answer'] = '长度超限' * 500
        observation['raw_response'] = json.dumps(raw)
        self.assertIn('FULL_RECORD_MIXED_COUNT_EXCEEDED', finalize_generation(observation, self.record, self.tokenizer)['reason_codes'])

    def test_verifier_protocol_and_identity(self):
        old = self.audit['semantic_result']
        observed = {'verifier_observation': {**old['verifier_observation'], 'actual_model': 'wrong-model'}}
        result = q.finalize_verifier_observation(observed, evidence=self.record['evidence'],
                    question=old['generated']['question'], answer=old['generated']['answer'])
        self.assertEqual(result['stage'], 'VERIFIER_IDENTITY')
        observed['verifier_observation'].update(actual_model='deepseek-v4-pro', raw_response='not json')
        result = q.finalize_verifier_observation(observed, evidence=self.record['evidence'],
                    question=old['generated']['question'], answer=old['generated']['answer'])
        self.assertNotEqual(result['quality_decision'], 'PASS')

    def test_production_dedup_and_paper_cap(self):
        item = copy.deepcopy(self.audit)
        duplicate = {**item, 'candidate_id': 'different'}
        decision = derive_production_terminal_fields(duplicate, accepted=[item])
        self.assertEqual(decision[2], ['DUPLICATE_NORMALIZED_QUESTION'])
        decision = derive_production_terminal_fields(duplicate, accepted=[item] * 3)
        self.assertEqual(decision[2], ['MAX_ACCEPTED_PER_PAPER_3'])

    def test_profile_drift_rejected(self):
        config = serving('generator')
        config.configs['max_tokens'] = 1024
        with self.assertRaisesRegex(ValueError, 'frozen'):
            gateway_for(config, 'generator')

    def test_all_three_adapters_with_recorded_responses(self):
        with tempfile.TemporaryDirectory() as temporary:
            gen = SFT2000Generator(serving('generator'), str(ROOT / 'models/tokenizers/Qwen3.6-27B-6a9e13bd'), temporary)
            ver = SFT2000Verifier(serving('verifier'))
            requests = []
            for role, op in [('generator', gen), ('verifier', ver)]:
                observation = self.audit['semantic_result'][role + '_observation']
                def transport(request, timeout, observation=observation):
                    requests.append(json.loads(request.data))
                    return io.BytesIO(json.dumps({'model': observation['actual_model'],
                        'choices': [{'message': {'content': observation['raw_response']}, 'finish_reason': 'stop'}]}).encode())
                op.gateway.transport = transport
            storage = Storage([{'evidence_record': self.record}])
            gen.run(storage)
            ver.run(storage)
            SFT2000Exporter(temporary).run(storage)
            status = storage.frame['export_status'].iloc[0]
            self.assertEqual(status['decision'], 'PASS')
            result = json.loads((Path(status['export_dir']) / 'sft.jsonl').read_text())
            self.assertEqual(result['output'], self.audit['semantic_result']['generated']['answer'])
            self.assertEqual(requests[0]['messages'], q.generator_messages(self.record))
            self.assertFalse(requests[0]['enable_thinking'])
            self.assertEqual(requests[1]['thinking'], {'type': 'disabled'})
            self.assertEqual(len(requests), 2)

    def test_transport_retry_is_not_semantic_retry(self):
        for role, expected_calls in [('generator', 1), ('verifier', 2)]:
            gateway = gateway_for(serving(role), role)
            calls = []
            def timeout(request, timeout):
                calls.append(request)
                raise TimeoutError('offline fixture')
            gateway.transport = timeout
            gateway.retry_backoff_seconds = 0
            with self.assertRaises(Exception):
                gateway.complete([{'role': 'user', 'content': 'JSON'}], operation_id='offline')
            self.assertEqual(len(calls), expected_calls)
            self.assertEqual(len(gateway.call_records), expected_calls)


if __name__ == '__main__':
    unittest.main()
