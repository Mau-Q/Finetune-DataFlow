"""DataFlow adapters for the frozen SFT-2000 prompts and decision functions."""
import hashlib
import json
import os
import uuid
from collections import Counter
from pathlib import Path

from dataflow.core import OperatorABC, LLMServingABC
from dataflow.utils.registry import OPERATOR_REGISTRY
from dataflow.utils.storage import DataFlowStorage
from paper_dataflow.baseline import quality as q
from paper_dataflow.baseline.production import derive_production_terminal_fields
from paper_dataflow.baseline.gateway import ModelGatewayError, OpenAICompatibleModelGateway
from paper_dataflow.baseline.token_contract import Qwen2BpeTokenizer, sha256_text
from .preparation import read_input, sha256

TOKENIZER_HASHES = {
    'merges.txt': 'a9d356d7bdf1ef4949e3e748e95b8e10ad9d4e2e838eddc38a0a7b6b94d1db8d',
    'tokenizer_config.json': '5186f0defcd7f232382c7f0aebcd2252d073bb921ab240e407b7ae8745d2b29b',
    'vocab.json': 'ce99b4cb2983d118806ce0a8b777a35b093e2000a503ebde25853284c9dfa003',
}
PROFILES = {
    'generator': {'model': 'qwen3.7-plus', 'temperature': 0.2, 'timeout': 60, 'attempts': 1,
                  'configs': {'enable_thinking': False, 'max_tokens': 2048, 'response_format': {'type': 'json_object'}, 'temperature': 0.2}},
    'verifier': {'model': 'deepseek-v4-pro', 'temperature': 0, 'timeout': 120, 'attempts': 2,
                 'configs': {'thinking': {'type': 'disabled'}, 'max_tokens': 3200, 'response_format': {'type': 'json_object'}, 'temperature': 0}},
}


def tokenizer_at(path):
    root = Path(path).resolve(strict=True)
    for name, expected in TOKENIZER_HASHES.items():
        if sha256(root / name) != expected:
            raise ValueError('Frozen tokenizer mismatch: ' + name)
    return Qwen2BpeTokenizer(root)


def gateway_for(serving, role):
    profile = PROFILES[role]
    if (serving.model_name != profile['model'] or serving.configs != profile['configs']
            or serving.timeout[1] != profile['timeout'] or serving.max_retries != profile['attempts']):
        raise ValueError(f'{role} serving does not match frozen SFT-2000 profile')
    if not serving.api_url.endswith('/chat/completions'):
        raise ValueError('Serving api_url must end in /chat/completions')
    return OpenAICompatibleModelGateway(
        base_url=serving.api_url.removesuffix('/chat/completions'), api_key=serving.api_key,
        model_name=profile['model'], temperature=profile['temperature'], timeout=profile['timeout'],
        max_output_tokens=profile['configs']['max_tokens'], response_format='json_object',
        enable_thinking=False if role == 'generator' else None,
        thinking='disabled' if role == 'verifier' else None, transport_retries=profile['attempts'] - 1)


def check_evidence(records, max_records):
    if not 0 < len(records) <= max_records:
        raise ValueError(f'Input count {len(records)} exceeds run budget {max_records} or is empty')
    ids = set()
    for record in records:
        if not isinstance(record, dict) or record.get('split') != 'train':
            raise ValueError('Expected a train evidence_record object')
        evidence = record['evidence']
        if (not evidence.strip() or sha256_text(evidence) != record['evidence_raw_sha256']
                or sha256_text(q.normalized(evidence)) != record['evidence_sha256']):
            raise ValueError('Evidence integrity mismatch')
        if record['candidate_id'] in ids:
            raise ValueError('Duplicate candidate_id')
        ids.add(record['candidate_id'])


def persist(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def observe(gateway, messages, record, role):
    operation = f'{record["candidate_id"]}:{role}'
    gateway.set_call_context(operation, {'candidate_id': record['candidate_id'], 'paper_id': record['paper_id'],
                                         'stage': role, 'semantic_attempt': 1})
    error, raw = None, ''
    try:
        raw = gateway.complete(messages, operation_id=operation)
    except ModelGatewayError as exc:
        error = {'code': exc.code, 'http_status': exc.http_status}
    call = gateway.latest_call_record(operation) or {}
    return {'raw_response': raw, 'actual_model': call.get('actual_model'),
            'configured_model': gateway.model_name, 'provider_base_url': gateway.base_url,
            'operation_id': operation, 'error_payload': error, 'call_record': call,
            'request_sha256': call.get('request_sha256'), 'response_sha256': call.get('response_sha256')}


def finalize_generation(observation, record, tokenizer):
    result = {'generator_observation': observation, 'processing_status': 'ERROR', 'quality_decision': None,
              'generated': None, 'reason_codes': [], 'stage': 'GENERATOR'}
    if observation.get('error_payload'):
        result['reason_codes'] = [observation['error_payload']['code']]
    elif observation.get('actual_model') != 'qwen3.7-plus':
        result['reason_codes'] = ['GENERATOR_ACTUAL_MODEL_MISMATCH']
    else:
        try:
            generated, metrics = q.validate_generated(observation['raw_response'], record, tokenizer)
            result.update(generated=generated, metrics=metrics, processing_status='COMPLETED',
                          quality_decision='PENDING_VERIFIER' if generated else 'SKIP')
        except q.GeneratorQualityReject as exc:
            result.update(processing_status='COMPLETED', quality_decision='REJECT', reason_codes=[str(exc)])
        except (q.GeneratorProtocolError, ValueError, TypeError) as exc:
            result['reason_codes'] = [str(exc)]
    return result


@OPERATOR_REGISTRY.register()
class SFT2000Generator(OperatorABC):
    def __init__(self, llm_serving: LLMServingABC, tokenizer_path: str, output_dir: str, max_records: int = 3):
        super().__init__()
        if max_records < 1:
            raise ValueError('max_records must be positive')
        self.gateway = gateway_for(llm_serving, 'generator')
        self.tokenizer = tokenizer_at(tokenizer_path)
        self.output_dir, self.max_records = Path(output_dir).resolve(), max_records

    @staticmethod
    def get_desc(lang: str = 'zh'):
        return ('旧 2000 条基线：Qwen 原提示词生成，400 混合单位 / 4096 token 校验；默认最多 3 条，记录原始响应。'
                if lang == 'zh' else 'Frozen SFT-2000 Qwen generation and length gates; three-row default budget.')

    def run(self, storage: DataFlowStorage, input_key: str = 'evidence_record', output_key: str = 'generation_result'):
        frame = read_input(storage, input_key, output_key)
        records = frame[input_key].tolist()
        check_evidence(records, self.max_records)  # Validate the entire batch before a paid call.
        run_dir = self.output_dir / uuid.uuid4().hex
        run_dir.mkdir(parents=True, exist_ok=False)
        vendor = Path(__file__).resolve().parents[3] / 'baseline/vendor_manifest.json'
        manifest = {'scope': 'bounded_integration', 'records': len(records), 'generator_profile': PROFILES['generator'],
                    'verifier_profile': PROFILES['verifier'], 'generator_url': self.gateway.base_url,
                    'generator_prompt': q.GENERATOR_PROMPT_VERSION, 'verifier_prompt': q.VERIFIER_PROMPT_VERSION,
                    'generator_prompt_sha256': sha256_text(q.GENERATOR_SYSTEM_PROMPT),
                    'verifier_prompt_sha256': sha256_text(q.VERIFIER_SYSTEM_PROMPT),
                    'vendor_manifest_sha256': sha256(vendor), 'adapter_sha256': sha256(__file__),
                    'tokenizer_files': TOKENIZER_HASHES, 'input_sha256': sha256_text(q.canonical_json(records)),
                    'execution_concurrency': 1, 'historical_production_concurrency': 48,
                    'note': 'Accepted historical evidence subset; not an unbiased experiment or exact historical endpoint reproduction.'}
        (run_dir / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
        results = []
        for record in records:
            observation = observe(self.gateway, q.generator_messages(record), record, 'generator')
            persist(run_dir / 'generator-observations.jsonl', {'candidate_id': record['candidate_id'], **observation})
            result = finalize_generation(observation, record, self.tokenizer)
            result['run_dir'] = str(run_dir)
            persist(run_dir / 'generation.jsonl', {'candidate_id': record['candidate_id'], **result})
            results.append(result)
        frame[output_key] = results
        storage.write(frame)
        return [output_key]


@OPERATOR_REGISTRY.register()
class SFT2000Verifier(OperatorABC):
    def __init__(self, llm_serving: LLMServingABC):
        super().__init__()
        self.gateway = gateway_for(llm_serving, 'verifier')

    @staticmethod
    def get_desc(lang: str = 'zh'):
        return ('旧 2000 条基线：DeepSeek V4 Pro 原独立审核提示词、逐声明证据检查及原判定规则；不重写失败答案。'
                if lang == 'zh' else 'Frozen independent DeepSeek V4 Pro verification; preserve failures without answer retries.')

    def run(self, storage: DataFlowStorage, input_key: str = 'generation_result', input_evidence_key: str = 'evidence_record', output_key: str = 'verification_result'):
        frame = read_input(storage, input_key, output_key)
        if input_evidence_key not in frame:
            raise ValueError('Missing evidence field')
        results = []
        for row in frame.to_dict('records'):
            result, record = row[input_key], row[input_evidence_key]
            check_evidence([record], 1)
            if result['quality_decision'] == 'PENDING_VERIFIER':
                generated = result['generated']
                messages = q.verifier_messages(evidence=record['evidence'], question=generated['question'], answer=generated['answer'])
                observation = observe(self.gateway, messages, record, 'verifier')
                persist(Path(result['run_dir']) / 'verifier-observations.jsonl', {'candidate_id': record['candidate_id'], **observation})
                result = {**result, 'verifier_observation': observation}
                if observation['error_payload']:
                    result.update(processing_status='ERROR', quality_decision=None, stage='VERIFIER',
                                  reason_codes=[observation['error_payload']['code']])
                else:
                    result = q.finalize_verifier_observation(result, evidence=record['evidence'],
                                                             question=generated['question'], answer=generated['answer'])
            persist(Path(result['run_dir']) / 'verification.jsonl', {'candidate_id': record['candidate_id'], **result})
            results.append(result)
        frame[output_key] = results
        storage.write(frame)
        return [output_key]


@OPERATOR_REGISTRY.register()
class SFT2000Exporter(OperatorABC):
    def __init__(self, output_dir: str):
        super().__init__()
        self.output_dir = Path(output_dir).resolve()

    @staticmethod
    def get_desc(lang: str = 'zh'):
        return ('仅导出 PASS：规范化问题精确去重、每篇最多 3 条；保留所有拒绝/错误审计及 instruction/input/output。'
                if lang == 'zh' else 'Export PASS only, normalized question dedup and three records per paper; retain every audit row.')

    def run(self, storage: DataFlowStorage, input_key: str = 'verification_result', input_evidence_key: str = 'evidence_record', output_key: str = 'export_status'):
        frame = read_input(storage, input_key, output_key)
        out = self.output_dir / uuid.uuid4().hex
        out.mkdir(parents=True, exist_ok=False)
        accepted, audit, mapping, statuses = [], [], [], []
        accepted_items = []
        for row in frame.to_dict('records'):
            result, record = row[input_key], row[input_evidence_key]
            check_evidence([record], 1)
            item = {**record, 'semantic_result': result}
            decision, stage, reasons, question_hash = derive_production_terminal_fields(item, accepted=accepted_items)
            if decision == 'PASS':
                generated = result['generated']
                accepted_items.append({**item, 'normalized_question_sha256': question_hash})
                accepted.append({'instruction': generated['question'], 'input': record['evidence'], 'output': generated['answer']})
                mapping.append({'record_index': len(accepted), 'candidate_id': record['candidate_id'],
                                'paper_id': record['paper_id'], 'chunk_id': record['chunk_id'],
                                'evidence_sha256': record['evidence_sha256'], 'normalized_question_sha256': question_hash})
            status = {'decision': decision, 'stage': stage, 'reason_codes': reasons,
                      'export_dir': str(out), 'candidate_id': record['candidate_id']}
            statuses.append(status)
            audit.append({'evidence_record': record, 'semantic_result': result, 'terminal_state': decision,
                          'stage': stage, 'reason_codes': reasons})
        for name, values in [('sft.jsonl', accepted), ('audit.jsonl', audit), ('record_mapping.jsonl', mapping)]:
            (out / name).write_text(''.join(json.dumps(v, ensure_ascii=False, sort_keys=True) + '\n' for v in values))
        summary = {'input_count': len(audit), 'accepted_count': len(accepted),
                   'decisions': dict(Counter(s['decision'] for s in statuses)),
                   'assets': {name: sha256(out / name) for name in ['sft.jsonl', 'audit.jsonl', 'record_mapping.jsonl']},
                   'scope': 'bounded_integration_not_quality_benchmark'}
        (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
        frame[output_key] = statuses
        storage.write(frame)
        return [output_key]
