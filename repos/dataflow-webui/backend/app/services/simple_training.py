"""Input validation and owned snapshots shared by API training workflows."""
import json
import shutil
import uuid
from pathlib import Path
from app.services.data_library import LibraryError, _hash, _json_bytes
from app.services.simple_training_operators import image_data


def read_inputs(c, config):
    dataset_id = config.get('input_dataset')
    dataset_id = dataset_id.get('id') if isinstance(dataset_id, dict) else dataset_id
    dataset = c.dataset_registry.get(dataset_id) if dataset_id else None
    if not dataset or not Path(dataset['root']).is_file():
        raise LibraryError('请选择已经导入的本地输入数据集', 422)
    manifest = Path(dataset['root'])
    if manifest.suffix.lower() != '.jsonl':
        raise LibraryError('API 训练流程输入需要 JSONL；文本导入 text.jsonl，图片使用原始材料导入', 422)
    try:
        rows = [json.loads(line) for line in manifest.read_text('utf-8-sig').splitlines() if line.strip()]
    except (ValueError, UnicodeError) as exc:
        raise LibraryError('输入不是有效 JSONL', 422) from exc
    if not rows or len(rows) > 100:
        raise LibraryError('API 训练流程每次支持 1–100 条输入', 422)
    modality = config['execution_options']['simple_training']['modality']
    for row in rows:
        if not isinstance(row, dict):
            raise LibraryError('输入行必须是 JSON 对象', 422)
        if {'candidate', 'training_sample', 'media_ref'} & row.keys():
            raise LibraryError('输入不能包含候选、训练输出或固定媒体字段', 422)
        if modality == 'text':
            if not isinstance(row.get('text'), str) or (not config.get('execution_options', {}).get('representative_training') and not row['text'].strip()):
                raise LibraryError('文本输入需要非空 text 字段', 422)
        else:
            if not row.get('material_id'):
                raise LibraryError('请通过原始数据集的图片材料入口导入图片', 422)
            path, material = c.data_library.material_file(row['material_id'])
            if material['kind'] != 'image':
                raise LibraryError('图片 pipeline 仅接受图片材料', 422)
            image_data(path)
    return dataset_id, rows


def freeze_inputs(c, config):
    dataset_id, rows = read_inputs(c, config)
    root = c.data_library.root / 'task_inputs' / uuid.uuid4().hex
    root.mkdir(parents=True)
    materials, bindings = [], {}
    try:
        if config['execution_options']['simple_training']['modality'] == 'image_text':
            for row in rows:
                source, material = c.data_library.material_file(row['material_id'])
                content = source.read_bytes()
                if _hash(content) != material['sha256']:
                    raise LibraryError('图片在提交期间发生变化', 409)
                ref = 'images/' + material['sha256'] + source.suffix.lower()
                target = root / ref
                c.data_library._atomic(target, content)
                row.update(source=str(target.resolve()), media_ref=ref)
                bindings[ref] = row['material_id']
                materials.append(dict(path=str(target.resolve()), sha256=_hash(content), material_id=row['material_id'], media_ref=ref))
        target = root / 'input.jsonl'
        content = b''.join(_json_bytes(row)+b'\n' for row in rows)
        c.data_library._atomic(target, content)
        return dict(path=str(target.resolve()), sha256=_hash(content), materials=materials, media_bindings=bindings, dataset_id=dataset_id)
    except Exception:
        shutil.rmtree(root)
        raise
