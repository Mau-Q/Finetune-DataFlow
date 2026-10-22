"""Copy legacy PDF inputs into owned storage without changing dataset IDs or originals."""
import hashlib
import json
from pathlib import Path
from app.services.dataset_persistence import dataset_lock, defer_checkpoints
from app.services.data_library import LibraryError


def adopt_pdf_dataset(registry, library, dataset_id):
    record = registry.get(dataset_id)
    if not record:
        raise LibraryError('数据集不存在',404)
    source_manifest = Path(record['root'])
    rows = [json.loads(line) for line in source_manifest.read_text('utf-8-sig').splitlines() if line.strip()]
    if not rows:
        raise LibraryError('PDF 清单为空')
    evidence = []
    owned = []
    with dataset_lock(library.root.parent), defer_checkpoints(library.root.parent):
        with library.db.transaction():
            for row in rows:
                source = Path(row['source']).resolve()
                if not source.is_file() or source.suffix.lower()!='.pdf':
                    raise LibraryError('只接管可读取的 PDF 清单')
                content = source.read_bytes()
                sha = hashlib.sha256(content).hexdigest()
                material = next((m for m in library.list_materials() if m['sha256']==sha),None)
                if material is None:
                    material = library.add_material(row.get('source_name',source.name),content,
                        {'name':row.get('source_name',source.name),'group':record['name'],'source':str(source)},str(source))
                target,_ = library.material_file(material['id'])
                if target.read_bytes()!=content or source.read_bytes()!=content:
                    raise LibraryError('接管时原文件或副本发生变化')
                owned.append(dict(row,source=str(target.resolve()),material_id=material['id']))
                evidence.append({'original':str(source),'copy':str(target.resolve()),'sha256':sha})
            manifest = library.root/'inputs'/('adopted-'+dataset_id+'.jsonl')
            content = ''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in owned).encode()
            if manifest.exists() and manifest.read_bytes()!=content:
                raise LibraryError('目标清单已有不同内容，未覆盖',409)
            manifest.parent.mkdir(parents=True,exist_ok=True)
            library._atomic(manifest,content)
            data = registry._read()
            current = data['datasets'][dataset_id]
            updated = dict(current,root=str(manifest.resolve()),type='jsonl',num_samples=len(rows),
                file_size=len(content),hash=hashlib.md5(content).hexdigest(),
                meta=dict(current.get('meta',{}),original_root=current.get('meta',{}).get('original_root',str(source_manifest))))
            data['datasets'][dataset_id] = updated
            registry._write(data)
    return {'dataset_id':dataset_id,'manifest':str(manifest.resolve()),'files':evidence}
