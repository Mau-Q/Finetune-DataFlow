"""Import five real local source fixtures through normal APIs; reruns verify and reuse."""
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import quote
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parent
BASE = sys.argv[1].rstrip('/') if len(sys.argv) > 1 else 'http://127.0.0.1:8000'
EXAMPLES = [
    ('PDF（示例）', ['shapes.pdf'], 'pdf'),
    ('图片（示例）', ['shapes.png'], 'image'),
    ('文本（示例）', ['shapes.txt'], 'text'),
    ('结构化数据（示例）', ['shapes.csv'], None),
    ('混合（示例）', ['shapes.pdf', 'shapes.png'], 'pdf_image'),
]


def request(path, files=None, fields=None, binary=False):
    body = None
    headers = {}
    if files:
        boundary = uuid.uuid4().hex
        chunks = []
        for key, value in (fields or {}).items():
            chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
        for key, file in files:
            chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"; filename="{file.name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode() + file.read_bytes() + b'\r\n')
        body = b''.join(chunks) + f'--{boundary}--\r\n'.encode()
        headers['Content-Type'] = f'multipart/form-data; boundary={boundary}'
    req = urllib.request.Request(BASE + '/api/v1' + path, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as response:
        if binary:
            return response.read()
        result = json.load(response)
    if not result['success']:
        raise RuntimeError(result['message'])
    return result['data']


def digest(content):
    return hashlib.sha256(content).hexdigest()


def verify(record, filenames, content_type):
    detail = request('/datasets/' + record['id'])
    if detail['content_type'] != content_type:
        raise RuntimeError('同名数据集类型不同，保留现有记录：' + record['name'])
    if content_type:
        if detail['file_count'] != len(filenames):
            raise RuntimeError('文件数量不同，保留现有记录：' + record['name'])
        for index, filename in enumerate(filenames):
            content = request(f'/library/inputs/{record["id"]}/file?row={index}', binary=True)
            if digest(content) != digest((ROOT / filename).read_bytes()):
                raise RuntimeError('文件内容不同，保留现有记录：' + record['name'])
    else:
        content = request('/datasets/file_type_sample/' + record['id'], binary=True)
        if digest(content) != digest((ROOT / filenames[0]).read_bytes()):
            raise RuntimeError('文件内容不同，保留现有记录：' + record['name'])
    preview = request('/library/inputs/' + record['id'] + '/preview')
    expected = len(filenames) if content_type else 3 if filenames[0].endswith('.csv') else 1
    if len(preview) != expected:
        raise RuntimeError('预览条数不一致：' + record['name'])
    return detail


def main():
    records = request('/datasets/')
    for name, filenames, content_type in EXAMPLES:
        matches = [record for record in records if record['name'] == name]
        if len(matches) > 1:
            raise RuntimeError('存在多个同名数据集：' + name)
        record = matches[0] if matches else None
        if record is None:
            if content_type in {'pdf', 'image', 'pdf_image'}:
                record = request('/library/inputs/upload', [('files', ROOT / file) for file in filenames], {'name': name})
            else:
                record = request('/datasets/upload?name=' + quote(name), [('file', ROOT / filenames[0])])
        detail = verify(record, filenames, content_type)
        print(json.dumps({'name': name, 'id': detail['id'], 'files': filenames,
                          'content_type': detail['content_type'], 'records': detail['num_samples'],
                          'owned_path': detail['root']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
