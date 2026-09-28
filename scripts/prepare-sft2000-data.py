"""Verify the immutable checkpoint and prepare evidence-only local datasets."""
import hashlib
import json
import zipfile
from pathlib import Path

from paper_dataflow.baseline.quality import normalized

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = Path('/Users/rui/zhiyan/zhiyan-data-quality-center-retired-2026-09-19/02-final-data/sft-checkpoint-2000')
EXPECTED = {'audit.jsonl': 'dc823b34abb7f6a0752c46ee4ffb525f8ca399111e0169256205b3a93ee5335f',
            'record_mapping.jsonl': '700ab569b716f43e5283ab83bca4a2b3b484adf9ea40027d5899f47ef8b6debf',
            'sft.jsonl': '515c56fcfaa2a94f4747f057d6f20de42a4e40ea1d211586c574dec707231bcb'}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_jsonl(path, rows):
    path.write_text(''.join(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n' for row in rows))


def main():
    for name, expected in EXPECTED.items():
        if digest((ARCHIVE / name).read_bytes()) != expected:
            raise ValueError('Frozen asset mismatch: ' + name)
    audit = [json.loads(line) for line in (ARCHIVE / 'audit.jsonl').read_text().splitlines()]
    mapping = [json.loads(line) for line in (ARCHIVE / 'record_mapping.jsonl').read_text().splitlines()]
    if len(audit) != 2000 or [r['candidate_id'] for r in audit] != [r['candidate_id'] for r in mapping]:
        raise ValueError('Frozen record mapping mismatch')
    rows = []
    for item in audit:
        evidence = item['source_evidence']
        if digest(normalized(evidence).encode()) != item['evidence_sha256']:
            raise ValueError('Evidence hash mismatch')
        record = {k: item[k] for k in ('candidate_id', 'paper_id', 'chunk_id', 'chunk_sha256', 'domain',
                                      'split', 'evidence_sha256', 'run_identity_sha256')}
        record.update(evidence=evidence, evidence_raw_sha256=digest(evidence.encode()),
                      source_scope='historical_accepted_2000_integration_only')
        rows.append({'evidence_record': record})
    if any(r['evidence_record']['split'] != 'train' for r in rows):
        raise ValueError('Unexpected historical split')
    out = ROOT / 'data/sft2000'
    out.mkdir(parents=True, exist_ok=True)
    write_jsonl(out / 'evidence-2000.jsonl', rows)
    sample, seen = [], set()
    for row in rows:
        paper = row['evidence_record']['paper_id']
        if paper not in seen:
            sample.append(row)
            seen.add(paper)
        if len(sample) == 3:
            break
    write_jsonl(out / 'evidence-smoke3.jsonl', sample)
    source = Path('/Users/rui/Downloads/1199_clean_only.zip')
    catalog = []
    with zipfile.ZipFile(source) as bundle:
        for name in sorted(bundle.namelist()):
            if name.endswith('.txt'):
                data = bundle.read(name)
                catalog.append({'paper_id': Path(name).stem, 'source_archive': str(source), 'archive_member': name,
                                'text_sha256': digest(data), 'text': data.decode('utf-8'),
                                'scope': 'source_inventory_only_not_new_candidate_queue'})
    if len(catalog) != 1199:
        raise ValueError('Unexpected TXT inventory count')
    write_jsonl(out / 'txt1199-source-catalog.jsonl', catalog)
    manifest = {'checkpoint': str(ARCHIVE), 'checkpoint_asset_hashes': EXPECTED, 'evidence_count': len(rows),
                'sample_count': len(sample), 'paper_count': len({r['paper_id'] for r in audit}),
                'source_txt_count': len(catalog), 'source_zip_sha256': digest(source.read_bytes()),
                'scope': 'Integration replay of accepted records; not an unbiased evaluation or original full candidate queue.',
                'datasets': {p.name: digest(p.read_bytes()) for p in out.glob('*.jsonl')}}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({k: v for k, v in manifest.items() if k not in {'datasets', 'checkpoint_asset_hashes'}}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
