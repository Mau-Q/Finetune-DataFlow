"""One-shot, scoped cleanup; executed inside the owned idle GPU1 container."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path('/runs')
LATEST = ROOT / 'strategy-20261023/gpu1-core8-20261024'
AUDIT = ROOT / 'strategy-20261023/closeout-20261024'
HOST = '/sharedata/home/huruiqian/DataFlow/runs/qwen35-9b/20261022-smoke'
CACHE = {}


def digest(path):
    key = str(path)
    if key not in CACHE:
        h = hashlib.sha256()
        with path.open('rb') as f:
            for chunk in iter(lambda: f.read(4 * 1024 * 1024), b''):
                h.update(chunk)
        CACHE[key] = h.hexdigest()
    return CACHE[key]


def checked(path):
    assert path.is_file() and ROOT in path.parents, str(path)
    entry = {'path': str(path.relative_to(ROOT)), 'bytes': path.stat().st_size,
             'sha256': digest(path)}
    if path.is_symlink():
        entry['symlink_target'] = os.readlink(str(path))
    else:
        assert path.resolve() == path, str(path)
    return entry


def save(name, value):
    AUDIT.mkdir(exist_ok=True)
    p = AUDIT / name
    tmp = p.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(p)


def plan():
    assert not (AUDIT / 'school-plan.json').exists(), 'Existing plan: inspect before rerunning'
    baseline = CONFIG['full_evidence_sha256']
    external = []
    env = '/sharedata/home/huruiqian/DataFlow/environments/qwen35-9b/gpu1-unified-20261024/'
    for i, (name, expected) in enumerate(baseline.items(), 1):
        if name.startswith(HOST + '/'):
            p = ROOT / name[len(HOST) + 1:]
            assert checked(p)['sha256'] == expected, 'Baseline drift: ' + name
        else:
            assert name.startswith(env), name
            p = Path('/work/strategy-20261023') / name[len(env):]
            assert p.is_file() and not p.is_symlink()
            assert digest(p) == expected, 'Environment evidence drift: ' + name
            external.append({'path': str(p), 'sha256': expected})
        if i % 200 == 0:
            print('verified original evidence', i, flush=True)
    final = []
    for i in range(8):
        out = LATEST / ('G%02d' % i) / 'attempt1/output'
        p = out / 'adapter_model.safetensors'
        final.append(checked(p))
        assert p.stat().st_size > 100 * 1024 * 1024
        assert digest(out / 'checkpoint-24/adapter_model.safetensors') == digest(p)
    candidates = []
    preserved = []
    for p in sorted(ROOT.rglob('*')):
        if not p.is_file() or AUDIT in p.parents:
            continue
        reason = None
        if p.is_symlink():
            pass
        elif p.name == 'adapter_model.safetensors' and LATEST not in p.parents:
            reason = 'historical_adapter_weight'
        elif LATEST in p.parents and p.parent.name in ('checkpoint-12', 'checkpoint-24'):
            out = p.parent.parent
            if p.name == 'adapter_model.safetensors':
                reason = ('duplicate_final_checkpoint_weight' if p.parent.name == 'checkpoint-24'
                          else 'superseded_intermediate_checkpoint_weight')
            elif p.name == 'tokenizer.json':
                assert digest(p) == digest(out / p.name), str(p)
                reason = 'duplicate_checkpoint_tokenizer'
        entry = checked(p)
        if reason:
            entry['reason'] = reason
            candidates.append(entry)
        else:
            preserved.append(entry)
    counts = {}
    for e in candidates:
        counts[e['reason']] = counts.get(e['reason'], 0) + 1
    assert counts == {'historical_adapter_weight': 99,
                      'duplicate_final_checkpoint_weight': 8,
                      'superseded_intermediate_checkpoint_weight': 8,
                      'duplicate_checkpoint_tokenizer': 16}, counts
    result = {'status': 'PREDELETE_VERIFIED', 'created_unix': time.time(),
              'host_root': HOST, 'original_evidence_verified': len(baseline),
              'final_adapters': final, 'delete': candidates, 'preserved': preserved,
              'external_evidence': external,
              'counts': counts, 'delete_bytes': sum(e['bytes'] for e in candidates)}
    save('school-plan.json', result)
    print(json.dumps({k: result[k] for k in ['status','original_evidence_verified','counts','delete_bytes']}), flush=True)


def apply():
    p = AUDIT / 'school-plan.json'
    data = json.loads(p.read_text())
    assert not (AUDIT / 'school-result.json').exists(), 'Already applied'
    # Validate the entire frozen deletion set before the first unlink.
    for e in data['delete']:
        current = checked(ROOT / e['path'])
        assert all(current[k] == e[k] for k in current), e['path']
    for e in data['final_adapters']:
        assert digest(ROOT / e['path']) == e['sha256'], e['path']
    journal = AUDIT / 'deleted.jsonl'
    with journal.open('x') as log:
        for e in data['delete']:
            (ROOT / e['path']).unlink()
            log.write(json.dumps(e) + '\n')
            log.flush()
            os.fsync(log.fileno())
    CACHE.clear()
    for e in data['preserved']:
        current = checked(ROOT / e['path'])
        assert all(current[k] == e[k] for k in current), 'Preserved drift: ' + e['path']
    for e in data['external_evidence']:
        assert digest(Path(e['path'])) == e['sha256'], e['path']
    assert all(not (ROOT / e['path']).exists() for e in data['delete'])
    result = {'status': 'CLEANUP_AND_PRESERVATION_VERIFIED',
              'completed_unix': time.time(), 'deleted_files': len(data['delete']),
              'deleted_bytes': data['delete_bytes'], 'counts': data['counts'],
              'preserved_files_verified': len(data['preserved']),
              'external_evidence_verified': len(data['external_evidence']),
              'final_adapters': data['final_adapters'], 'plan_sha256': digest(p),
              'journal_sha256': digest(journal),
              'scope': 'Only adapter weights and duplicate checkpoint tokenizers; all other run files retained.'}
    save('school-result.json', result)
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    {'plan': plan, 'apply': apply}[sys.argv[1]]()
