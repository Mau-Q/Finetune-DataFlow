"""Task-result collection shared by automatic completion and explicit imports."""
import copy
from pathlib import Path
from app.core.config import settings
from app.schemas.data_library import DraftCreate
from app.services.data_library import LibraryError, MAX_IMPORT_BYTES, _hash, _json_bytes, _now, _parse_json
from app.services.dataset_persistence import atomic_write
from app.services.training_lifecycle import TrainingLifecycle


class TaskResults:
    def __init__(self, app_container=None):
        if app_container is None:
            from app.core.container import container
            app_container = container
        self.c = app_container
        self.lib = self.c.data_library

    def task(self, task_id):
        task = self.c.task_registry.get(task_id)
        if not task:
            raise LibraryError('任务不存在', 404)
        return task

    def _file(self, task):
        if task.get('status') != 'completed':
            raise LibraryError('任务尚未成功完成；中间结果可在画布步骤中查看', 409)
        output = task.get('output', {})
        training = [a for a in output.get('artifacts', []) if a.get('kind') == 'training']
        if training:
            item = copy.deepcopy(training[-1])
        else:
            steps = output.get('execution_results', [])
            if not steps:
                raise LibraryError('任务未记录最终输出文件', 409)
            last = max(steps, key=lambda s: s['index'])
            expected = len(task.get('pipeline_config', {}).get('operators', []))
            if expected and (len(steps) != expected or last['index'] != expected-1):
                raise LibraryError('任务步骤未完整完成，不能作为最终结果', 409)
            path = last.get('file_path') or Path(settings.CACHE_DIR) / f'{task["task_id"]}_output' / f'dataflow_cache_step_step{last["index"]+1}.jsonl'
            item = {'path': str(path), 'step': last['index']}
        if output.get('final_file') and Path(output['final_file']).is_file():
            item['path'] = output['final_file']
        saved = self.lib.root / 'task_results' / task['task_id'] / 'manifest.json'
        if saved.is_file():
            item = _parse_json(saved.read_text('utf-8'))
        path = Path(item['path'])
        if not path.is_file():
            raise LibraryError('最终结果文件已缺失', 409)
        if path.stat().st_size > MAX_IMPORT_BYTES:
            raise LibraryError('最终结果超过 20 MiB；请通过步骤下载后拆分导入', 409)
        content = path.read_bytes()
        digest = _hash(content)
        if item.get('sha256') and item['sha256'] != digest:
            raise LibraryError('固定的任务产物内容已变化', 409)
        item.update(sha256=digest, path=str(path.resolve()), size_bytes=len(content))
        item.setdefault('id', 'final_' + _hash(_json_bytes([task['task_id'], item['step'], digest]))[:24])
        try:
            rows = [_parse_json(line) for line in content.decode('utf-8-sig').splitlines() if line.strip()]
        except (ValueError, UnicodeError) as exc:
            raise LibraryError('最终结果不是有效的 JSONL 文件', 409) from exc
        item['row_count'] = len(rows)
        return item, rows, content

    def _contract(self, rows):
        if not rows:
            raise LibraryError('最终结果为 0 条，可保留完成记录，不能收录空数据集')
        training_type = 'dpo' if isinstance(rows[0], dict) and all(k in rows[0] for k in ('prompt', 'chosen', 'rejected')) else 'sft'
        modality = None
        refs = set()
        for i, row in enumerate(rows, 1):
            try:
                # Validate the training structure first; image_text requires at least one image.
                try:
                    row_refs = self.lib._validate_row(row, 'image_text', training_type)
                    row_modality = 'image_text'
                except LibraryError as exc:
                    if str(exc) != '图文样本需要 image、images 或 image_url 图片引用':
                        raise
                    row_refs = self.lib._validate_row(row, 'text', training_type)
                    row_modality = 'text'
                if modality and modality != row_modality:
                    raise LibraryError('文本与图文样本混合，请分开收录')
                modality = row_modality
                refs.update(row_refs)
            except LibraryError as exc:
                raise LibraryError(f'第 {i} 条样本: {exc}') from exc
        return {'training_type': training_type, 'modality': modality, 'media_refs': sorted(refs)}

    def _collections(self, task_id, artifact_id):
        key = task_id + ':' + artifact_id
        return [{'id': d['id'], 'name': d['name'], 'row_count': d['row_count']}
                for d in self.lib.list_drafts() if key in d.get('collections', [])]

    def detail(self, task_id):
        task = self.task(task_id)
        result = {k: task.get(k) for k in ('task_id', 'pipeline_id', 'name', 'status', 'created_at', 'completed_at')}
        result.update(available=False, collectable=False, collections=[], sample_data=[],
                      auto_collection=(task.get('output') or {}).get('auto_collection'),
                      sample_summary=(task.get('output') or {}).get('sample_summary'),
                      invalid_samples_file=(task.get('output') or {}).get('invalid_samples_file'),
                      invalid_artifact=next((a['id'] for a in (task.get('output') or {}).get('artifacts', []) if a.get('kind') == 'invalid_samples'), None),
                      result_directory=task.get('output', {}).get('result_directory') or task.get('pipeline_config', {}).get('execution_options', {}).get('result_directory'),
                      storage_error=task.get('output', {}).get('storage_error'))
        try:
            item, rows, _ = self._file(task)
        except LibraryError as exc:
            result['reason'] = str(exc)
            return result
        result.update(available=True, artifact=item, sample_data=rows[:15], collections=self._collections(task_id, item['id']))
        try:
            result.update(self._contract(rows), collectable=True)
        except LibraryError as exc:
            result['reason'] = str(exc)
        return result

    def collect(self, task_id, expected_sha256, draft_id=None, name=None, media_bindings=None):
        if bool(draft_id) == bool(name and name.strip()):
            raise LibraryError('请选择已有数据集，或填写新数据集名称', 422)
        task = self.task(task_id)
        item, rows, content = self._file(task)
        if item['sha256'] != expected_sha256:
            raise LibraryError('最终结果已变化，请刷新后重新确认', 409)
        contract = self._contract(rows)
        bindings = {**item.get('media_bindings', {}), **(media_bindings or {})}
        item.update(kind='training', **{k: contract[k] for k in ('training_type', 'modality')},
                    media_bindings={ref: bindings[ref] for ref in contract['media_refs'] if ref in bindings})
        if not draft_id and not (name and name.strip()):
            raise LibraryError('请填写新数据集名称')
        life = TrainingLifecycle(self.lib)
        with self.lib._writing():
            if not draft_id:
                # Stable target for retried/double-clicked new-dataset requests.
                draft_id = 'ds_' + _hash(_json_bytes([task_id, item['id'], 'collection']))[:32]
                if self.lib.db.get('drafts', draft_id) is None:
                    request = DraftCreate(name=name, modality=contract['modality'], training_type=contract['training_type'],
                                          description=f'收录自 Pipeline 任务 {task_id}')
                    rec = dict(request.model_dump(), id=draft_id, status='draft', created_at=_now(), updated_at=_now(),
                               rows=[], imports=[], media_bindings={})
                    self.lib._atomic(self.lib._path('drafts', draft_id), _json_bytes(rec))
            collected = life._collect_rows(draft_id, task, item, rows, idempotent=True)
            # Keep an owned copy for legacy final outputs, without modifying their cache file.
            if not collected['reused']:
                target = self.lib.root / 'task_results' / task_id / (item['id'] + '.jsonl')
                atomic_write(target, content)
                # Durable outputs keep their original directory so relative images
                # remain readable. Legacy cache outputs use the owned copy.
                saved_path = item['path'] if task.get('output', {}).get('final_file') else str(target.resolve())
                saved_item = dict(item, path=saved_path)
                atomic_write(target.parent / 'manifest.json', _json_bytes(saved_item))
        return collected

    def download(self, task_id):
        item, _, _ = self._file(self.task(task_id))
        return Path(item['path'])
