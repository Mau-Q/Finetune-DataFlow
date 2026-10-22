"""Per-run durable outputs; runtime caches remain private to the executor."""
import copy
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from app.core.config import settings
from app.services.data_library import LibraryError, _hash, _json_bytes
from app.services.dataset_persistence import atomic_write
from app.services.resource_store import ResourceStore


def store():
    return ResourceStore(Path(settings.BASE_DIR) / settings.RESOURCE_DIR / 'result_storage.json')


def preferences():
    return {'output_root': store().read().get('output_root') or str(Path(settings.BASE_DIR) / 'results')}


def check_root(value):
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise LibraryError('请填写本机的绝对目录路径', 422)
    path = path.resolve()
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=path) as probe:
            probe.write(b'check'); probe.flush(); os.fsync(probe.fileno())
    except OSError as exc:
        raise LibraryError('目录不可写，请检查路径和访问权限', 422) from exc
    return str(path)


def save_preferences(value):
    root = check_root(value)
    with store().writing() as data:
        data['output_root'] = root
    return {'output_root': root}


def prepare(config, task_id, name='Pipeline'):
    """Call after generating a task ID, before persisting or submitting the task."""
    options = config.setdefault('execution_options', {})
    root = check_root(options.get('output_root') or preferences()['output_root'])
    label = re.sub(r'[^\w\-\u4e00-\u9fff]+', '_', name).strip('_')[:60] or 'Pipeline'
    directory = Path(root) / f'{label}_{datetime.now().strftime("%Y%m%d_%H%M%S")}_{task_id}'
    try:
        directory.mkdir(exist_ok=False)
    except OSError as exc:
        raise LibraryError('无法创建本次任务目录，请重新选择保存位置', 422) from exc
    options.update(output_root=root, result_directory=str(directory.resolve()))
    return str(directory.resolve())


def persist(config, result):
    directory = config.get('execution_options', {}).get('result_directory')
    if not directory:
        return result  # Historical tasks and older workers keep their original behavior.
    directory = Path(directory)
    output = result.setdefault('output', {})
    output['result_directory'] = str(directory)
    files = []
    def write(name, content, kind):
        target = directory / name
        atomic_write(target, content)
        files.append({'path': name, 'kind': kind, 'sha256': _hash(content), 'size_bytes': len(content)})
        return str(target.resolve())
    try:
        snapshot = config.get('execution_options', {}).get('input_snapshot', {})
        for material in snapshot.get('materials', []):
            if material.get('media_ref'):
                content = Path(material['path']).read_bytes()
                if _hash(content) != material['sha256']:
                    raise LibraryError('固定图片内容已变化')
                write(material['media_ref'], content, 'image')
        steps = output.get('execution_results', [])
        for step in steps:
            source = Path(step.get('file_path') or Path(settings.CACHE_DIR) / f'{result["task_id"]}_output' / f'dataflow_cache_step_step{step["index"]+1}.jsonl')
            if source.is_file():
                step['file_path'] = write(f'intermediate/step-{step["index"]+1}.jsonl', source.read_bytes(), 'intermediate')
        artifacts = copy.deepcopy(output.get('artifacts', []))
        for item in artifacts:
            source = Path(item['path'])
            if source.is_file():
                content = source.read_bytes()
                if _hash(content) != item['sha256']:
                    raise LibraryError('任务产物校验失败')
                item['path'] = write(f'artifacts/{item["id"]}.jsonl', content, item['kind'])
                if item['kind'] == 'invalid_samples':
                    output['invalid_samples_file'] = write('invalid_samples.jsonl', content, 'invalid_samples')
        output['artifacts'] = artifacts
        if result.get('status') == 'completed':
            training = [a for a in artifacts if a.get('kind') == 'training']
            last = max(steps, key=lambda s: s['index']) if steps else None
            final = training[-1]['path'] if training else last.get('file_path') if last else None
            if final and Path(final).is_file():
                output['final_file'] = write('final.jsonl', Path(final).read_bytes(), 'final')
        if result.get('status') == 'completed' and not output.get('final_file'):
            raise LibraryError('最终文件未落盘')
        write('logs.json', _json_bytes(result.get('logs', [])), 'logs')
        atomic_write(directory / 'manifest.json', _json_bytes({'task_id': result['task_id'], 'status': result.get('status'), 'files': files}))
    except Exception as exc:
        output['storage_error'] = f'任务结果保存不完整：{type(exc).__name__}。请检查磁盘与目录权限。'
        result.setdefault('logs', []).append(output['storage_error'])
    return result
