"""Stream-hash existing model, frozen data and initial adapter; no model loading."""
import hashlib
import json
from pathlib import Path
import time


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(8*1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    root = Path('/runs/strategy-20261023')
    model = Path('/models/Qwen3.5-9B')
    transfer = json.loads((model/'transfer-manifest.json').read_text())
    assert transfer['revision'] == 'c202236235762e1c871ad0ccb60c8ee5ba337b9a'
    model_files = {}
    for name, expected in transfer['files'].items():
        path = model/name
        assert path.stat().st_size == expected['bytes']
        actual = sha(path)
        assert actual == expected['sha256'], name
        model_files[name] = actual
    assert sha(root/'data-manifest.json') == 'f2e723257b323c022729a01207b45c036d3c98d61debdc71087a252e58c66b7e'
    data = json.loads((root/'data-manifest.json').read_text())
    for name, expected in data['files'].items():
        assert sha(root/'data'/name) == expected, name
    initial = root/'paired-initialization-v2/adapter_init.safetensors'
    assert sha(initial) == 'c56d3f34fbb0d1b4001c77fa2eba35eb5ad4f88e91a2e94c5db38e34ba30809a'
    result = {'status': 'MODEL_SHARDS_FROZEN_DATA_AND_INITIAL_FILE_HASHES_MATCH', 'timestamp': time.time(),
              'model_revision': transfer['revision'], 'model_files': model_files, 'data_files': data['files'],
              'data_manifest_sha256': sha(root/'data-manifest.json'), 'initial_adapter_file_sha256': sha(initial),
              'initial_tensor_sha256_expected_and_checked_by_training': '3bf6a156850eca6cc0a5a0f914ed9eae38002687fc94f6ec585a1dbcd321820f'}
    (root/'gpu1-gates-20261024/frozen-identity.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'status': result['status'], 'model_files': len(model_files), 'data_files': len(data['files'])}))


if __name__ == '__main__':
    main()
