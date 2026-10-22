"""Owned task artifacts and model-text capture shared by both execution loops."""
import functools
import inspect
import json
import uuid
from pathlib import Path
from app.core.config import settings
from app.services.data_library import DataLibrary, LibraryError, _hash, _json_bytes


class ResponseCapture:
    def __init__(self, serving, directory):
        self._serving = serving
        self._directory = directory

    def __getattr__(self, name):
        value = getattr(self._serving, name)
        if name not in {'generate_from_input', 'generate_from_conversations'}:
            return value
        def call(*args, **kwargs):
            responses = value(*args, **kwargs)
            # Exact returned model text, before operator parsing; no HTTP headers/keys.
            content = _json_bytes({'method': name, 'responses': responses}) + b'\n'
            self._directory.mkdir(parents=True, exist_ok=True)
            (self._directory / (uuid.uuid4().hex + '.jsonl')).write_bytes(content)
            return responses
        return call


def capture_responses(serving, config, task_id):
    if not config.get('execution_options', {}).get('capture_responses'):
        return serving
    return ResponseCapture(serving, Path(settings.CACHE_DIR) / f'{task_id}_output' / 'raw_responses')


def finalize_artifacts(config, result, cache_root=None):
    if not config.get('execution_options', {}).get('capture_responses'):
        return result
    directory = Path(cache_root or settings.CACHE_DIR) / f'{result["task_id"]}_output'
    owned = directory / 'artifacts'
    owned.mkdir(parents=True, exist_ok=True)
    artifacts = []
    def add(path, kind, index=None, content=None):
        content = path.read_bytes() if content is None else content
        aid = kind + '_' + _hash(content + str(index).encode())[:20]
        target = owned / (aid + '.jsonl')
        target.write_bytes(content)
        artifacts.append(dict(id=aid, kind=kind, step=index, path=str(target.resolve()),
                              sha256=_hash(content), size_bytes=len(content),
                              row_count=sum(bool(line.strip()) for line in content.splitlines())))
    for path in sorted((directory / 'raw_responses').glob('*.jsonl')):
        add(path, 'raw_response', path.stem)
    steps = result.get('output', {}).get('execution_results', [])
    for step in steps:
        path = Path(step.get('file_path') or directory / f'dataflow_cache_step_step{step["index"]+1}.jsonl')
        if not path.is_file():
            raise LibraryError(f'已完成步骤产物未落盘: {step["index"]}')
        add(path, 'candidate', step['index'])
    if result['status'] == 'completed' and config.get('execution_options', {}).get('training_output'):
        if len(steps) != len(config.get('operators', [])) or not steps:
            raise LibraryError('批次步骤尚未完整完成，不能固定训练产物')
        last = steps[-1]
        path = Path(last.get('file_path') or directory / f'dataflow_cache_step_step{last["index"]+1}.jsonl')
        training, invalid = [], []
        simple = config.get('execution_options', {}).get('simple_training')
        for line in path.read_text('utf-8').splitlines():
            if line.strip():
                row = json.loads(line)
                sample = row.get('training_sample') if simple else {k: row.get(k, '') for k in ('instruction', 'input', 'output')}
                if simple and (sample is None or row.get('_training_issues')):
                    invalid.append(dict(row_index=len(training)+len(invalid), reasons=row.get('_training_issues') or ['候选未通过训练格式校验'], source=row))
                    continue
                try:
                    DataLibrary._validate_row(None, sample, simple['modality'] if simple else 'text', simple['training_type'] if simple else 'sft')
                except LibraryError:
                    invalid.append(dict(row_index=len(training)+len(invalid), reasons=['最终训练样本不符合契约'], source=row))
                    continue
                training.append(sample)
        add(path, 'training', last['index'], b''.join(_json_bytes(row)+b'\n' for row in training))
        if simple:
            artifacts[-1].update(**simple, media_bindings=config['execution_options'].get('input_snapshot', {}).get('media_bindings', {}))
        if invalid:
            add(path, 'invalid_samples', last['index'], b''.join(_json_bytes(row)+b'\n' for row in invalid))
        result.setdefault('output', {})['sample_summary'] = dict(valid=len(training), invalid=len(invalid))
    result.setdefault('output', {})['artifacts'] = artifacts
    result['output']['progress_unit'] = 'batch'
    result['output']['completed_units'] = int(result['status'] == 'completed')
    return result


def with_task_artifacts(function):
    signature = inspect.signature(function)
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        bound = signature.bind(*args, **kwargs).arguments
        config = bound['pipeline_config']
        snapshot = config.get('execution_options', {}).get('input_snapshot')
        if snapshot:
            for item in [snapshot, *snapshot.get('materials', [])]:
                path = Path(item['path'])
                if not path.is_file() or _hash(path.read_bytes()) != item['sha256']:
                    from app.services.result_storage import persist
                    return persist(config, {'task_id': bound['task_id'], 'status': 'failed', 'output': {'error': '固定的输入文件缺失或已变化'}, 'logs': ['输入快照校验失败，未执行算子']})
        result = function(*args, **kwargs)
        try:
            result = finalize_artifacts(config, result)
        except Exception as exc:
            result['status'] = 'failed'
            result.setdefault('output', {})['artifact_error'] = str(exc)
            result['logs'].append(f'Artifact finalization failed: {exc}')
        from app.services.result_storage import persist
        result = persist(config, result)
        from app.services.auto_collection import collect_completed_result
        return collect_completed_result(config, result, bound.get('execution_path'))
    return wrapped
