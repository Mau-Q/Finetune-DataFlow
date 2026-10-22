"""Thin bridge from owned PDF/image materials to existing pipeline input manifests."""
import hashlib
import json
import mimetypes
import uuid
import csv
from itertools import islice
from pathlib import Path, PurePosixPath
from app.services.data_library import LibraryError, MAX_BYTES, IMAGE_TYPES
from app.services.dataset_persistence import dataset_lock, defer_checkpoints


class SourceDatasets:
    def __init__(self, library, registry):
        self.library = library
        self.registry = registry

    def upload(self, files, name):
        with dataset_lock(self.library.root.parent), defer_checkpoints(self.library.root.parent):
            with self.library.db.transaction():
                return self._upload(files, name)

    def _upload(self, files, name):
        name = name.strip()
        if not name or len(name) > 240:
            raise LibraryError('请填写数据集名称（最多 240 字）')
        if not files or len(files) > 100:
            raise LibraryError('请选择 1–100 个 PDF 或图片文件')
        # Check the selection size and supported extensions before copying.
        contents = []
        total = 0
        seen = set()
        for file in files:
            content = file.file.read(MAX_BYTES + 1)
            total += len(content)
            if not content or len(content) > MAX_BYTES or total > 200 * 1024 * 1024:
                raise LibraryError('每份文件最多 100 MiB，每次导入总量最多 200 MiB')
            suffix = Path(file.filename or '').suffix.lower()
            if suffix not in {'.pdf', *IMAGE_TYPES}:
                raise LibraryError('原始材料仅支持 PDF 和常见图片；结构化文件请单独导入')
            digest = hashlib.sha256(content).hexdigest()
            if digest in seen:
                raise LibraryError(f'同一次选择包含重复内容: {file.filename}')
            seen.add(digest)
            contents.append((file.filename, content))
        signature = hashlib.sha256(''.join(sorted(hashlib.sha256(c).hexdigest() for _, c in contents)).encode()).hexdigest()
        for record in self.registry.list():
            if record.get('meta', {}).get('material_signature') == signature:
                raise LibraryError(f'这些文件已导入：{record["name"]}', 409)
        rows = []
        for filename, content in contents:
            try:
                material = self.library.add_material(filename, content, {'name': Path(filename).name, 'group': name})
            except LibraryError as exc:
                if exc.status != 409:
                    raise
                digest = hashlib.sha256(content).hexdigest()
                material = next(r for r in self.library.list_materials() if r['sha256'] == digest)
            path, _ = self.library.material_file(material['id'])
            rows.append({'source': str(path.resolve()), 'source_name': material['filename'], 'material_id': material['id']})
        path = self.library.root / 'inputs' / (uuid.uuid4().hex + '.jsonl')
        path.parent.mkdir(exist_ok=True)
        self.library._atomic(path, ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows).encode())
        try:
            return self.registry.add_or_update({'name': name, 'root': str(path.resolve()), 'pipeline': 'uploaded',
                                                'meta': {'material_signature': signature}})
        except Exception:
            path.unlink(missing_ok=True)
            raise

    def upload_data(self, file, name):
        name = name.strip()
        if not name or len(name) > 240:
            raise LibraryError('请填写数据集名称（最多 240 字）')
        suffix = Path(file.filename).suffix.lower()
        if suffix not in {'.txt', '.md', '.json', '.jsonl', '.csv', '.parquet'}:
            raise LibraryError('不支持的数据文件格式')
        content = file.file.read(MAX_BYTES + 1)
        if not content or len(content) > MAX_BYTES:
            raise LibraryError('文件为空或超过 100 MiB 限制')
        path = self.library.root / 'files' / (uuid.uuid4().hex + suffix)
        with dataset_lock(self.library.root.parent), defer_checkpoints(self.library.root.parent):
            try:
                with self.library.db.transaction():
                    self.library._atomic(path, content)
                    self._preview_path(path, 0, 20)
                    return self.registry.add_or_update({'name': name, 'root': str(path.resolve()), 'pipeline': 'uploaded', 'meta': {'original_filename': file.filename}})
            except Exception:
                path.unlink(missing_ok=True)
                raise

    def upload_folder(self, files, name, import_kind='folder'):
        name = name.strip()
        if not name or len(name) > 240:
            raise LibraryError('请填写数据集名称（最多 240 字）')
        supported = {'.pdf', '.txt', '.md', '.json', '.jsonl', '.csv', '.parquet', *IMAGE_TYPES}
        accepted, skipped, seen = [], [], set()
        total = 0
        for file in files:
            relative = (file.filename or '').replace('\\', '/')
            path = PurePosixPath(relative)
            if not relative or path.is_absolute() or '..' in path.parts or len(relative) > 2000:
                raise LibraryError('文件夹中包含无效的相对路径')
            if any(part.startswith('.') or part == '__MACOSX' for part in path.parts) or path.suffix.lower() not in supported:
                skipped.append(relative)
                continue
            if relative in seen:
                raise LibraryError('文件夹中存在重复路径: ' + relative)
            seen.add(relative)
            if len(accepted) >= 100:
                raise LibraryError('每个文件夹最多导入 100 个支持的文件')
            content = file.file.read(MAX_BYTES + 1)
            total += len(content)
            if not content or len(content) > MAX_BYTES or total > 200 * 1024 * 1024:
                raise LibraryError('文件不能为空，单份最多 100 MiB，每次导入总量最多 200 MiB')
            if path.suffix.lower() in {'.txt', '.md', '.json', '.jsonl', '.csv'}:
                try:
                    content.decode('utf-8-sig')
                except UnicodeError as exc:
                    raise LibraryError('文本文件必须使用 UTF-8 编码: ' + relative) from exc
            accepted.append((relative, content))
        if not accepted:
            raise LibraryError('文件夹中没有支持的文件（PDF、图片、TXT、Markdown、JSON、JSONL、CSV、Parquet）')
        accepted.sort(key=lambda item: item[0])
        signature = hashlib.sha256(json.dumps([(n, hashlib.sha256(c).hexdigest()) for n, c in accepted]).encode()).hexdigest()
        written = []
        with dataset_lock(self.library.root.parent), defer_checkpoints(self.library.root.parent):
            try:
                with self.library.db.transaction():
                    for record in self.registry.list():
                        if record.get('meta', {}).get('folder_signature') == signature:
                            raise LibraryError('此文件夹内容已经导入：' + record['name'], 409)
                    rows = []
                    for relative, content in accepted:
                        suffix = PurePosixPath(relative).suffix.lower()
                        if suffix in {'.pdf', *IMAGE_TYPES}:
                            digest = hashlib.sha256(content).hexdigest()
                            material = next((m for m in self.library.list_materials() if m['sha256'] == digest), None)
                            if material is None:
                                material = self.library.add_material(PurePosixPath(relative).name, content, {'name': PurePosixPath(relative).name, 'group': name})
                                written.append(self.library.materials / material['blob_name'])
                            path, _ = self.library.material_file(material['id'])
                            row = {'source': str(path.resolve()), 'source_name': relative, 'material_id': material['id']}
                        else:
                            path = self.library.root / 'files' / (uuid.uuid4().hex + suffix)
                            self.library._atomic(path, content)
                            written.append(path)
                            # Validate structured content before committing any registry record.
                            self._preview_path(path, 0, 20)
                            row = {'source': str(path.resolve()), 'source_name': relative}
                        rows.append(row)
                    manifest = self.library.root / 'inputs' / (uuid.uuid4().hex + '.jsonl')
                    self.library._atomic(manifest, ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows).encode())
                    written.append(manifest)
                    return self.registry.add_or_update({'name': name, 'root': str(manifest.resolve()), 'pipeline': 'uploaded',
                        'meta': {'folder_signature': signature, 'import_kind': import_kind, 'skipped_files': json.dumps(skipped, ensure_ascii=False)}})
            except Exception:
                for path in written:
                    path.unlink(missing_ok=True)
                raise

    def member_preview(self, dataset_id, row, offset=0, limit=20):
        path, _ = self.file(dataset_id, row)
        if path.suffix.lower() in {'.pdf', *IMAGE_TYPES}:
            raise LibraryError('PDF 和图片请使用原文件预览')
        return self._preview_path(path, offset, limit)

    def preview(self, dataset_id, offset, limit):
        record = self.registry.get(dataset_id)
        if not record:
            raise LibraryError('数据集不存在', 404)
        path = Path(record['root'])
        if not path.is_file():
            raise LibraryError('数据文件不存在', 404)
        return self._preview_path(path, offset, limit)

    def _preview_path(self, path, offset, limit):
        try:
            suffix = path.suffix.lower()
            if suffix in {'.txt', '.md'}:
                # Text is one document, not one training sample per line.
                return [{'text': path.read_text('utf-8-sig')}] if offset == 0 else []
            if suffix == '.jsonl':
                with path.open(encoding='utf-8-sig') as handle:
                    lines = (line for line in handle if line.strip())
                    return [json.loads(line) for line in islice(lines, offset, offset + limit)]
            if suffix == '.json':
                value = json.loads(path.read_text('utf-8-sig'))
                return (value if isinstance(value, list) else [value])[offset:offset + limit]
            if suffix == '.csv':
                with path.open(encoding='utf-8-sig', newline='') as handle:
                    return list(islice(csv.DictReader(handle), offset, offset + limit))
            if suffix == '.parquet':
                import pandas as pd
                frame = pd.read_parquet(path).iloc[offset:offset + limit]
                return frame.astype(object).where(pd.notna(frame), None).to_dict(orient='records')
            if suffix in {'.pdf', *IMAGE_TYPES}:
                return [{'source': str(path), 'source_name': path.name}] if offset == 0 else []
        except (ValueError, UnicodeError) as exc:
            raise LibraryError(f'数据文件无法解析: {exc}') from exc
        raise LibraryError('此格式不支持内容预览')

    def file(self, dataset_id, row):
        record = self.registry.get(dataset_id)
        if not record:
            raise LibraryError('数据集不存在', 404)
        if not Path(record['root']).is_file():
            raise LibraryError('数据文件不存在', 404)
        if record.get('type') == 'jsonl':
            with Path(record['root']).open(encoding='utf-8') as handle:
                lines = (line for line in handle if line.strip())
                value = next((json.loads(line) for i, line in enumerate(lines) if i == row), None)
            if not value or not isinstance(value, dict) or not isinstance(value.get('source'), str):
                raise LibraryError('此样本没有可预览的原文件', 404)
            if value.get('material_id'):
                path, material = self.library.material_file(value['material_id'])
                return path, material['mime_type']
            path = Path(value['source'])
        else:
            if row:
                raise LibraryError('样本不存在', 404)
            path = Path(record['root'])
        if not path.is_file():
            raise LibraryError('原文件已移动或不存在，请检查来源路径', 404)
        if path.suffix.lower() not in {'.pdf', '.txt', '.md', '.json', '.jsonl', '.csv', '.parquet', *IMAGE_TYPES}:
            raise LibraryError('该文件格式不支持预览')
        return path, mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
