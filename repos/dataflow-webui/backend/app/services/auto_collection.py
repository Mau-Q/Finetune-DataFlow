"""Backend completion hook: idempotent collection into the run's selected dataset."""
import copy
from pathlib import Path
from types import SimpleNamespace
from typing import Literal
from pydantic import BaseModel, Field
from app.services.data_library import DataLibrary, LibraryError
from app.services.resource_store import ResourceStore
from app.services.task_results import TaskResults


class CollectionTarget(BaseModel):
    mode: Literal['new', 'append'] = 'new'
    name: str = Field(default='', max_length=240)
    draft_id: str | None = None


def target_preferences(library):
    return ResourceStore(library.root.parent / 'collection_preferences.json').read()


def validate_target(target, library, contract=None):
    target = CollectionTarget.model_validate(target).model_dump()
    if target['mode'] == 'new':
        target['name'] = target['name'].strip()
        if not target['name']:
            raise LibraryError('请填写新数据集名称', 422)
        target['draft_id'] = None
    else:
        if not target['draft_id']:
            raise LibraryError('请选择要追加的生成数据集', 422)
        rec = library._get('drafts', target['draft_id'])
        if contract and any(rec.get(k, 'sft' if k == 'training_type' else 'text') != contract[k]
                            for k in ('modality', 'training_type')):
            raise LibraryError('目标数据集的模态或训练类型与 Pipeline 不一致，请重新选择', 422)
        target['name'] = ''
    return target


def pipeline_contract(config):
    contract = config.get('execution_options', {}).get('simple_training')
    if contract:
        return contract
    names = [op['name'] for op in config.get('operators', [])]
    kind = 'dpo' if any('DPO' in n for n in names) else 'sft' if any('SFT' in n for n in names) else None
    return dict(modality='image_text' if any('Image' in n or 'VQA' in n for n in names) else 'text', training_type=kind) if kind else None


def freeze_collection_target(config, library):
    # Freeze both the library and user selection before dispatching any worker.
    options = config.setdefault('execution_options', {})
    options['collection_library_root'] = str(library.root.resolve())
    if options.get('collection_target') is not None:
        contract = pipeline_contract(config)
        target = validate_target(options['collection_target'], library, contract)
        options['collection_target'] = target
        key = f"{contract['modality']}:{contract['training_type']}" if contract else 'general'
        with ResourceStore(library.root.parent / 'collection_preferences.json').writing() as data:
            data[key] = target


def collect_completed_result(config, result, execution_path):
    if result.get('status') != 'completed' or not execution_path:
        return result
    output = result.setdefault('output', {})
    task_id = result['task_id']
    try:
        stored = ResourceStore(execution_path).read().get('tasks', {}).get(task_id)
        if not stored or stored.get('status') == 'cancelled':
            output['auto_collection'] = dict(status='skipped', reason='任务记录不存在或已取消')
            return result
        root = config.get('execution_options', {}).get('collection_library_root')
        if not root:
            raise LibraryError('未固定生成数据集数据库位置，自动收录未执行')
        library = DataLibrary(Path(root))
        task = {**copy.deepcopy(stored), **result, 'pipeline_config': config}
        service = TaskResults(SimpleNamespace(data_library=library, task_registry=SimpleNamespace(get=lambda _: task)))
        try:
            item, rows, _ = service._file(task)
            service._contract(rows)
        except LibraryError as exc:
            output['auto_collection'] = dict(status='skipped', reason=str(exc))
            return result
        name = f"{stored.get('name') or 'Pipeline'} · {task_id}"[:240]
        target = config.get('execution_options', {}).get('collection_target')
        if target:
            target = validate_target(target, library, service._contract(rows))
        collected = service.collect(task_id, item['sha256'],
                                    draft_id=target['draft_id'] if target and target['mode'] == 'append' else None,
                                    name=None if target and target['mode'] == 'append' else (target['name'] if target else name))
        output['auto_collection'] = dict(status='collected', dataset_id=collected['id'], name=collected['name'],
                                         row_count=collected['row_count'], added=collected['added'], reused=collected['reused'])
    except Exception as exc:
        # Generation is still complete; expose database failures separately.
        output['auto_collection'] = dict(status='failed', reason=str(exc))
        result.setdefault('logs', []).append(f'自动收录失败: {type(exc).__name__}: {exc}')
    return result
