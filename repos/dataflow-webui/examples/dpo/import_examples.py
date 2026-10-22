"""Import the neighboring JSONL and PNG files through the local dataset APIs."""
import hashlib
import json
from pathlib import Path
import sys
import urllib.request
import uuid

BASE = sys.argv[1].rstrip('/') if len(sys.argv) > 1 else 'http://127.0.0.1:8000'
ROOT = Path(__file__).resolve().parent


def request(path, data=None, files=None):
    headers = {}
    if files:
        boundary = uuid.uuid4().hex
        chunks = []
        for name, value in (data or {}).items():
            chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
        for name, file in files.items():
            chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{file.name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode() + file.read_bytes() + b'\r\n')
        body = b''.join(chunks) + f'--{boundary}--\r\n'.encode()
        headers['Content-Type'] = f'multipart/form-data; boundary={boundary}'
    elif data is not None:
        body = json.dumps(data).encode()
        headers['Content-Type'] = 'application/json'
    else:
        body = None
    req = urllib.request.Request(BASE + '/api/v1' + path, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        result = json.load(response)
    if not result['success']:
        raise RuntimeError(result['message'])
    return result['data']


def main():
    drafts = request('/library/drafts')
    picture = ROOT / 'images/shapes.png'
    digest = hashlib.sha256(picture.read_bytes()).hexdigest()
    material = next((m for m in request('/library/materials') if m['sha256'] == digest), None)
    if not material:
        material = request('/library/materials/upload', {'metadata': json.dumps({'name':'DPO 几何图形（示例）'}, ensure_ascii=False)}, {'file':picture})
    for filename, name, modality in [('text.jsonl','文本 DPO（示例）','text'), ('image.jsonl','图文 DPO（示例）','image_text')]:
        file = ROOT / filename
        rows = [json.loads(line) for line in file.read_text().splitlines() if line.strip()]
        matches = [d for d in drafts if d['name'] == name]
        if len(matches) > 1:
            raise RuntimeError(f'存在多个同名数据集：{name}')
        draft = matches[0] if matches else request('/library/drafts', {'name':name,'modality':modality,'training_type':'dpo'})
        if draft['training_type'] != 'dpo' or draft['modality'] != modality:
            raise RuntimeError(f'同名数据集类型不同：{name}')
        current = request('/library/drafts/' + draft['id'])
        if not current['row_count']:
            bindings = {'images/shapes.png':material['id']} if modality == 'image_text' else {}
            request('/library/drafts/' + draft['id'] + '/import', {'media_bindings':json.dumps(bindings)}, {'file':file})
        elif current['rows'] != rows or current['row_count'] != len(rows):
            raise RuntimeError(f'已有数据集内容不同，保留原数据：{name}')
        print(json.dumps({'name':name,'id':draft['id'],'file':str(file),'rows':len(rows)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
