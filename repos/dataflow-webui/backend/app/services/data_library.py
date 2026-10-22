"""Local source library and SFT drafts. No dependency on DatasetRegistry.

Each record is an atomic JSON document. Media are owned copies addressed by UUID;
filenames never determine identity. A process/thread lock serializes mutations.
"""
import copy
import hashlib
import io
import json
import re
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.services.dataset_persistence import dataset_lock, checkpoint, atomic_write
from app.services.dataset_database import DatasetDatabase
from PIL import Image
from pypdf import PdfReader
from app.core.config import settings
from app.schemas.data_library import MaterialMetadata

MAX_BYTES = 100 * 1024 * 1024
MAX_IMPORT_BYTES = 20 * 1024 * 1024
IMAGE_TYPES = {'.png': 'PNG', '.jpg': 'JPEG', '.jpeg': 'JPEG', '.webp': 'WEBP', '.gif': 'GIF', '.bmp': 'BMP'}
MIMES = {'PNG': 'image/png', 'JPEG': 'image/jpeg', 'WEBP': 'image/webp', 'GIF': 'image/gif', 'BMP': 'image/bmp'}


class LibraryError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _now():
    return datetime.now(timezone.utc).isoformat()


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode('utf-8')


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'重复 JSON 字段: {key}')
        result[key] = value
    return result


def _parse_json(text):
    return json.loads(text, object_pairs_hook=_unique_object,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f'非法数值: {value}')))


class DataLibrary:
    def __init__(self, root=None):
        self.root = Path(root or Path(settings.BASE_DIR) / settings.RESOURCE_DIR / 'library')
        self.root.mkdir(parents=True, exist_ok=True)
        self.materials = self.root / 'materials'
        self.drafts = self.root / 'drafts'
        self.materials.mkdir(exist_ok=True)
        self.drafts.mkdir(exist_ok=True)
        self.db = DatasetDatabase(self.root.parent)
        self.db.import_library(self.root)

    @contextmanager
    def _writing(self):
        with dataset_lock(self.root.parent):
            with self.db.transaction():
                yield
            checkpoint(self.root.parent)

    def _atomic(self, path, data):
        path = Path(path)
        if path.suffix == '.json' and path.parent.name in {'materials', 'drafts', 'releases'}:
            self.db.put(path.parent.name, json.loads(data))
            return
        with dataset_lock(self.root.parent):
            atomic_write(path, data)

    def _path(self, kind, record_id):
        if not re.fullmatch(r'(mat|ds)_[0-9a-f]{32}', record_id):
            raise LibraryError('记录不存在', 404)
        return (self.materials if kind == 'materials' else self.drafts) / (record_id + '.json')

    def _get(self, kind, record_id):
        self._path(kind, record_id)  # Keep the existing ID contract.
        record = self.db.get(kind, record_id)
        if record is None:
            raise LibraryError('记录不存在', 404)
        return record

    def list_materials(self):
        return self._list(self.materials)

    def _list(self, directory):
        records = self.db.list(directory.name)
        return sorted(records, key=lambda r: r['created_at'], reverse=True)

    def get_material(self, record_id):
        return self._get('materials', record_id)

    def _metadata(self, meta):
        meta = MaterialMetadata.model_validate(meta).model_dump()
        parent = meta['parent_material_id']
        if parent:
            self.get_material(parent)
        if meta['relation'] != 'source' and not parent:
            raise LibraryError('解析产物必须关联原始材料')
        return meta

    def add_material(self, filename, content, metadata, registered_path=None):
        meta = self._metadata(metadata)
        filename = Path(filename.replace('\\', '/')).name
        suffix = Path(filename).suffix.lower()
        if not content or len(content) > MAX_BYTES:
            raise LibraryError('材料为空或超过 100 MiB 限制')
        try:
            if suffix == '.pdf':
                reader = PdfReader(io.BytesIO(content))
                if not content.startswith(b'%PDF-') or reader.is_encrypted or not len(reader.pages):
                    raise ValueError('空 PDF 或加密 PDF')
                info = {'kind': 'pdf', 'mime_type': 'application/pdf', 'pages': len(reader.pages)}
            elif suffix in IMAGE_TYPES:
                with Image.open(io.BytesIO(content)) as image:
                    if image.format != IMAGE_TYPES[suffix]:
                        raise ValueError('扩展名与内容格式不一致')
                    info = {'kind': 'image', 'mime_type': MIMES[image.format], 'width': image.width, 'height': image.height}
                    image.verify()
            else:
                raise LibraryError('仅支持 PDF、PNG、JPEG、WebP、GIF、BMP')
        except LibraryError:
            raise
        except Exception as exc:
            raise LibraryError(f'无法读取材料: {exc}') from exc
        digest = _hash(content)
        with self._writing():
            duplicate = next((r for r in self.list_materials() if r['sha256'] == digest), None)
            if duplicate:
                raise LibraryError(f'重复材料，已存在: {duplicate["name"]} ({duplicate["id"]})', 409)
            record_id = 'mat_' + uuid.uuid4().hex
            blob = self.materials / (record_id + suffix)
            record = dict(meta, **info, id=record_id, filename=filename, sha256=digest,
                          size_bytes=len(content), created_at=_now(), updated_at=_now(),
                          registered_path=registered_path, blob_name=blob.name)
            self._atomic(blob, content)
            try:
                self._atomic(self._path('materials', record_id), _json_bytes(record))
            except Exception:
                blob.unlink(missing_ok=True)
                raise
            return record

    def register_material(self, request):
        path = Path(request.path).expanduser()
        if not path.is_file():
            raise LibraryError('登记路径不是可读取的本地文件')
        with path.open('rb') as handle:
            content = handle.read(MAX_BYTES + 1)
        return self.add_material(path.name, content, request.model_dump(exclude={'path'}), str(path.resolve()))

    def update_material(self, record_id, metadata):
        with self._writing():
            rec = self.get_material(record_id)
            meta = self._metadata(metadata)
            parent = meta['parent_material_id']
            seen = {record_id}
            while parent:
                if parent in seen:
                    raise LibraryError('材料关联不能形成循环')
                seen.add(parent)
                parent = self.get_material(parent)['parent_material_id']
            rec.update(meta, updated_at=_now())
            self._atomic(self._path('materials', record_id), _json_bytes(rec))
            return rec

    def material_file(self, record_id):
        record = self.get_material(record_id)
        path = self.materials / record['blob_name']
        if not path.is_file():
            raise LibraryError('材料文件已缺失', 409)
        if _hash(path.read_bytes()) != record['sha256']:
            raise LibraryError('材料内容已变化，请重新导入', 409)
        return path, record

    def create_draft(self, request):
        rec = dict(request.model_dump(), id='ds_' + uuid.uuid4().hex, status='draft',
                   created_at=_now(), updated_at=_now(), rows=[], imports=[], media_bindings={})
        with self._writing():
            self._atomic(self._path('drafts', rec['id']), _json_bytes(rec))
        return self._summary(rec)

    def _summary(self, rec):
        summary = {k: v for k, v in rec.items() if k != 'rows'}
        summary['row_count'] = len(rec['rows'])
        summary['fields'] = sorted({key for row in rec['rows'] for key in row})
        return summary

    def list_drafts(self):
        # Serialize with dataset mutations while joining versions for the catalog.
        with dataset_lock(self.root.parent):
            latest = {}
            for release in self.db.list('releases'):
                key = release['draft_id']
                latest[key] = max(latest.get(key, 0), release['version'])
            return [dict(r, latest_release_version=latest.get(r['id']))
                    for r in sorted(self.db.draft_summaries(), key=lambda r: r['created_at'], reverse=True)]

    def get_draft(self, record_id, offset=0, limit=20):
        from app.services.training_lifecycle import TrainingLifecycle
        return TrainingLifecycle(self).view(record_id, offset, limit)

    def _validate_row(self, row, modality, training_type='sft'):
        if not isinstance(row, dict):
            raise LibraryError('每条样本必须是 JSON 对象')
        refs = []
        if training_type == 'dpo':
            if not all(isinstance(row.get(key), str) and row[key].strip() for key in ('prompt', 'chosen', 'rejected')):
                raise LibraryError('DPO 样本需要非空 prompt/chosen/rejected')
            if row['chosen'].strip() == row['rejected'].strip():
                raise LibraryError('DPO chosen 与 rejected 不能相同')
        elif 'messages' in row:
            messages = row['messages']
            if not isinstance(messages, list) or not messages:
                raise LibraryError('messages 必须是非空数组')
            has_user = has_assistant = False
            for msg in messages:
                if not isinstance(msg, dict) or msg.get('role') not in {'system', 'user', 'assistant', 'tool'}:
                    raise LibraryError('messages.role 无效')
                content = msg.get('content')
                if isinstance(content, list):
                    if not content:
                        raise LibraryError('messages.content 不能为空')
                    for block in content:
                        if not isinstance(block, dict):
                            raise LibraryError('消息内容块必须是对象')
                        if block.get('type') == 'text' and isinstance(block.get('text'), str) and block['text'].strip():
                            continue
                        if block.get('type') == 'image_url':
                            ref = block.get('image_url')
                            ref = ref.get('url') if isinstance(ref, dict) else ref
                            if isinstance(ref, str) and ref.strip():
                                refs.append(ref)
                                continue
                        raise LibraryError('仅支持非空 text 或 image_url 消息块')
                elif not isinstance(content, str) or not content.strip():
                    raise LibraryError('messages.content 必须是非空文本或内容块数组')
                has_user |= msg['role'] == 'user'
                has_assistant |= msg['role'] == 'assistant'
            if not has_user or not has_assistant:
                raise LibraryError('SFT messages 需要 user 和 assistant 消息')
        else:
            if not all(isinstance(row.get(k), str) and row[k].strip() for k in ('instruction', 'output')):
                raise LibraryError('SFT 样本需要非空 instruction/output，或 messages')
            if 'input' in row and not isinstance(row['input'], str):
                raise LibraryError('input 必须是字符串')
        if 'image' in row:
            if not isinstance(row['image'], str) or not row['image'].strip():
                raise LibraryError('image 必须是非空图片引用')
            refs.append(row['image'])
        images = row.get('images', [])
        if not isinstance(images, list) or any(not isinstance(x, str) or not x.strip() for x in images):
            raise LibraryError('images 必须是非空图片引用组成的数组')
        refs.extend(images)
        if modality == 'text' and refs:
            raise LibraryError('文本数据集含图片引用，请选择图文分类')
        if modality == 'image_text' and not refs:
            raise LibraryError('图文样本需要 image、images 或 image_url 图片引用')
        return set(refs)

    def import_rows(self, record_id, filename, content, media_bindings):
        if not content or len(content) > MAX_IMPORT_BYTES:
            raise LibraryError('训练文件为空或超过 20 MiB 限制')
        suffix = Path(filename).suffix.lower()
        try:
            text = content.decode('utf-8-sig')
            if suffix == '.jsonl':
                rows = []
                for line_number, line in enumerate(text.splitlines(), 1):
                    if line.strip():
                        try:
                            rows.append(_parse_json(line))
                        except ValueError as exc:
                            raise LibraryError(f'第 {line_number} 行 JSON 无效: {exc}') from exc
            elif suffix == '.json':
                rows = _parse_json(text)
            else:
                raise LibraryError('仅支持 JSON 数组或 JSONL 文件')
        except (UnicodeError, ValueError) as exc:
            if isinstance(exc, LibraryError):
                raise
            raise LibraryError(f'训练文件解析失败: {exc}') from exc
        if not isinstance(rows, list) or not rows:
            raise LibraryError('训练文件必须包含非空样本数组')
        if not isinstance(media_bindings, dict) or any(not isinstance(v, str) for v in media_bindings.values()):
            raise LibraryError('媒体映射必须是 图片引用 → 材料 ID 的 JSON 对象')
        with self._writing():
            rec = self._get('drafts', record_id)
            refs = set()
            for i, row in enumerate(rows, 1):
                try:
                    refs.update(self._validate_row(row, rec['modality'], rec.get('training_type', 'sft')))
                except LibraryError as exc:
                    raise LibraryError(f'第 {i} 条样本: {exc}') from exc
            bindings = copy.deepcopy(rec['media_bindings'])
            for ref in sorted(refs):
                material_id = media_bindings.get(ref) or bindings.get(ref)
                if not material_id:
                    raise LibraryError(f'媒体缺失: {ref}；请显式绑定已导入的图片材料')
                if ref in bindings and bindings[ref] != material_id:
                    raise LibraryError(f'媒体引用已绑定其他材料: {ref}', 409)
                _, material = self.material_file(material_id)
                if material['kind'] != 'image':
                    raise LibraryError(f'媒体引用不是图片: {ref}')
                bindings[ref] = material_id
            fingerprint = _hash(_json_bytes(rows))
            if any(r['sha256'] == fingerprint for r in rec['imports']):
                raise LibraryError('此训练文件内容已经导入该草稿', 409)
            existing = {_hash(_json_bytes(row)) for row in rec['rows']}
            unique = []
            duplicates = 0
            for row in rows:
                digest = _hash(_json_bytes(row))
                if digest in existing:
                    duplicates += 1
                else:
                    existing.add(digest)
                    unique.append(row)
            if not unique:
                raise LibraryError('所有样本均已存在，未重复写入', 409)
            from app.services.training_lifecycle import TrainingLifecycle
            lifecycle = TrainingLifecycle(self)
            lifecycle._members(rec)
            rec['rows'].extend(unique)
            lifecycle._members(rec)
            rec['media_bindings'] = bindings
            rec['imports'].append({'filename': Path(filename).name, 'sha256': fingerprint,
                                   'file_sha256': _hash(content), 'added': len(unique),
                                   'duplicates_skipped': duplicates, 'created_at': _now()})
            rec['updated_at'] = _now()
            self._atomic(self._path('drafts', record_id), _json_bytes(rec))
            return dict(self._summary(rec), added=len(unique), duplicates_skipped=duplicates)
