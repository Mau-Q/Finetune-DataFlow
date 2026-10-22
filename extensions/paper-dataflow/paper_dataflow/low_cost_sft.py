"""Deterministic transforms for the PDF multitask candidate pipeline.

These functions are used by the existing PandasOperator. They never call a
model, parse a PDF, download a tokenizer, or modify source materials.
"""
import hashlib
import json
import math
import uuid
from collections import Counter
from pathlib import Path

import pandas as pd


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def strict_json(value):
    if not isinstance(value, str):
        raise ValueError('Expected a JSON response string')
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ValueError('Duplicate JSON key: ' + key)
            result[key] = item
        return result
    return json.loads(value, object_pairs_hook=pairs,
                      parse_constant=lambda v: (_ for _ in ()).throw(ValueError(v)))


def prepare_sources(df):
    rows, seen = [], {}
    for row in df.to_dict('records'):
        value = row.get('source_path') or row.get('source') or row.get('path')
        path = Path(str(value)).expanduser().resolve(strict=True)
        if path.suffix.lower() != '.pdf' or not path.is_file():
            raise ValueError(f'Expected readable PDF: {path}')
        with path.open('rb') as stream:
            if not stream.read(1024).lstrip().startswith(b'%PDF-'):
                raise ValueError(f'PDF signature missing: {path}')
        with path.open('rb') as stream:
            sha = hashlib.file_digest(stream, 'sha256').hexdigest()
        split = row.get('split') or 'train'
        if split not in {'train', 'dev', 'test'}:
            raise ValueError('Invalid source split')
        if sha in seen:
            existing = seen[sha]
            if existing['split'] != split:
                raise ValueError('Same PDF occurs in multiple splits')
            existing['source_aliases'].append(dict(row))
            continue
        item = dict(row, source_path=str(path), document_id=sha, split=split,
                    source_aliases=[dict(row)])
        seen[sha] = item
        rows.append(item)
    return pd.DataFrame(rows, columns=list(dict.fromkeys([*df.columns,
        'source_path', 'document_id', 'split', 'source_aliases'])))


def build_contexts(df, tokenizer_path, context_tokens=6000, max_samples=4):
    """Join exact structured chunks; use a whole text only when all chunks fit.

    The exact frozen tokenizer is local. No summary or remote tokenizer lookup.
    A partial paper remains labelled partial, even if its surviving text fits.
    """
    from paper_dataflow.operators.paper.generate.structured_chunking import PaperStructuredChunker
    counter = PaperStructuredChunker(tokenizer_path, chunk_size=context_tokens).count
    rows = []
    groups = {}
    for row in df.to_dict('records'):
        meta = row['chunk_metadata']
        groups.setdefault(meta['document_id'], []).append(row)
    for doc, items in groups.items():
        items.sort(key=lambda r: (r['chunk_metadata']['page_numbers'][0],
                                 r['chunk_metadata']['source_segments'][0]['char_start']))
        all_ok = all(r['chunk_metadata'].get('eligible_for_qa') for r in items)
        def text_for(parts):
            return '\n\n'.join(
                f"[{doc[:12]}:{r['chunk_metadata']['chunk_id'][:12]}] "
                f"{r['chunk_metadata'].get('section_title', '')}\n{r['raw_chunk']}" for r in parts)
        whole = text_for(items)
        batches = [items] if all_ok and counter(whole) <= context_tokens else [[r] for r in items]
        for parts in batches:
            text = text_for(parts)
            flags = sorted({f for r in parts for f in r['chunk_metadata'].get('flags', [])})
            valid = not flags and bool(text.strip()) and counter(text) <= context_tokens
            # "paper_text" means all parsed textual evidence, not unseen figures.
            scope = 'paper_text' if len(parts) == len(items) and all_ok else 'section_or_blocks'
            unit = digest(doc + ':' + ':'.join(r['chunk_metadata']['chunk_id'] for r in parts))
            source_map = [dict(s, chunk_id=r['chunk_metadata']['chunk_id'])
                          for r in parts for s in r['chunk_metadata']['source_segments']]
            rows.append(dict(parts[0], unit_id=unit, context=text, context_scope=scope,
                context_tokens=counter(text), context_valid=valid,
                preparation_reason=','.join(flags) or ('' if valid else 'context_budget'),
                source_map=source_map,
                generation_input=f'材料范围：{scope}\n最多样本数：{max_samples}\n'
                                 f'<material>\n{text}\n</material>'))
    return pd.DataFrame(rows, columns=list(dict.fromkeys([*df.columns, 'unit_id', 'context',
        'context_scope', 'context_tokens', 'context_valid', 'preparation_reason',
        'source_map', 'generation_input'])))


def parse_candidates(df, max_samples=4):
    rows = []
    for row in df.to_dict('records'):
        candidates, invalid, keywords = [], [], []
        try:
            obj = strict_json(row['generation_raw'])
            if not isinstance(obj, dict) or set(obj) != {'keywords', 'samples'}:
                raise ValueError('Expected keywords and samples')
            keywords = obj['keywords']
            samples = obj['samples']
            if not isinstance(keywords, list) or len(keywords) > 8 or not all(isinstance(v, str) for v in keywords):
                raise ValueError('Invalid keywords')
            if not isinstance(samples, list) or len(samples) > max_samples:
                raise ValueError('Candidate count exceeds budget')
            seen = set()
            for index, sample in enumerate(samples):
                try:
                    keys = {'reader_level', 'user_goal', 'task_type', 'instruction', 'answer_format', 'answer'}
                    if not isinstance(sample, dict) or set(sample) != keys:
                        raise ValueError('Candidate keys mismatch')
                    if not all(isinstance(sample[k], str) and sample[k].strip() for k in keys):
                        raise ValueError('Candidate values must be nonempty strings')
                    if sample['answer_format'] not in {'text', 'json'}:
                        raise ValueError('Invalid answer_format')
                    if sample['answer_format'] == 'json':
                        strict_json(sample['answer'])
                    fingerprint = digest(sample['instruction'].strip() + '\n' + sample['answer'].strip())
                    if fingerprint in seen:
                        raise ValueError('Exact duplicate candidate')
                    seen.add(fingerprint)
                    candidates.append(dict(sample, sample_id=f"{row['unit_id']}:c{index + 1}"))
                except (ValueError, TypeError) as exc:
                    invalid.append({'candidate_index': index, 'reason': str(exc), 'candidate': sample})
        except (ValueError, TypeError, KeyError) as exc:
            invalid.append({'reason': str(exc)})
        rows.append(dict(row, keywords=keywords, candidates=candidates,
            invalid_candidates=invalid, candidate_count=len(candidates),
            review_input=f"材料范围：{row['context_scope']}\n<material>\n{row['context']}\n</material>\n"
                         f'<candidates>\n{dumps(candidates)}\n</candidates>'))
    return pd.DataFrame(rows, columns=list(dict.fromkeys([*df.columns, 'keywords', 'candidates',
        'invalid_candidates', 'candidate_count', 'review_input'])))


def select_paper_contexts(df, selections, max_candidates_per_paper=8, max_samples_per_context=2):
    """Apply an explicit paper-level budget without losing unselected evidence.

    `selections` maps each PDF hash to the exact reviewed context IDs. Keep all
    rows in the preparation artifact; the ordinary context filter sends only
    selected, originally eligible rows to the billable generator.
    """
    if (type(max_candidates_per_paper) is not int or max_candidates_per_paper < 1
            or type(max_samples_per_context) is not int or max_samples_per_context < 1):
        raise ValueError('Paper candidate budgets must be positive integers')
    rows = df.to_dict('records')
    docs = {r['document_id'] for r in rows}
    if len({(r['document_id'], r['unit_id']) for r in rows}) != len(rows):
        raise ValueError('Duplicate document/context identity')
    if not isinstance(selections, dict) or set(selections) != docs:
        raise ValueError('Context selection must cover exactly the input papers')
    chosen = set()
    for doc, units in selections.items():
        if (not isinstance(units, list) or not units or len(units) != len(set(units))
                or len(units) * max_samples_per_context > max_candidates_per_paper):
            raise ValueError('Context selection exceeds paper candidate budget or repeats IDs')
        available = {r['unit_id']: r for r in rows if r['document_id'] == doc}
        if any(u not in available or not available[u].get('context_valid') for u in units):
            raise ValueError('Selected context is missing or was ineligible before selection')
        chosen.update((doc, unit) for unit in units)
    for row in rows:
        selected = (row['document_id'], row['unit_id']) in chosen
        row['selected_for_generation'] = selected
        row['paper_candidate_budget'] = max_candidates_per_paper
        row['generation_input'] = (f"材料范围：{row.get('context_scope', 'section_or_blocks')}\n"
                                   f'最多样本数：{max_samples_per_context}\n'
                                   f"<material>\n{row['context']}\n</material>")
        if not selected:
            row['context_valid'] = False
            row['preparation_reason'] = row.get('preparation_reason') or 'paper_budget_not_selected'
    return pd.DataFrame(rows)


def parse_reviews(df):
    rows = []
    dimensions = ('grounded', 'task_fit', 'usefulness')
    for row in df.to_dict('records'):
        lookup, error = {}, ''
        candidates = row['candidates']
        expected = {c['sample_id'] for c in candidates}
        try:
            obj = strict_json(row['review_raw'])
            if not isinstance(obj, dict) or set(obj) != {'reviews'} or not isinstance(obj['reviews'], list):
                raise ValueError('Expected reviews array')
            for review in obj['reviews']:
                if not isinstance(review, dict) or set(review) != {'sample_id', *dimensions, 'reason'}:
                    raise ValueError('Review keys mismatch')
                sid = review['sample_id']
                if not isinstance(sid, str) or sid not in expected or sid in lookup:
                    raise ValueError('Unknown or duplicate sample_id')
                if any(review[d] not in {'PASS', 'FAIL', 'UNCERTAIN'} for d in dimensions):
                    raise ValueError('Invalid dimension status')
                if not isinstance(review['reason'], str):
                    raise ValueError('Review reason must be string')
                if any(review[d] != 'PASS' for d in dimensions) and not review['reason'].strip():
                    raise ValueError('Non-PASS review requires reason')
                lookup[sid] = review
        except (ValueError, TypeError, KeyError) as exc:
            error = 'review_protocol_error: ' + str(exc)
            lookup = {}
        for candidate in candidates:
            review = lookup.get(candidate['sample_id'])
            status, reason = 'REVIEW', error or 'missing_sample_review'
            if review:
                states = [review[d] for d in dimensions]
                status = 'REJECT' if 'FAIL' in states else 'REVIEW' if 'UNCERTAIN' in states else 'PASS'
                reason = review['reason']
            item = dict(row)
            item.update(candidate)
            item.update(review_status=status, review_reason=reason,
                        sample_review=review, input=row['context'], output=candidate['answer'])
            item['dedup_text'] = dumps([item['context'], item['instruction'].strip(), item['output'].strip()])
            rows.append(item)
    return pd.DataFrame(rows, columns=list(dict.fromkeys([*df.columns, 'sample_id', 'task_type',
        'reader_level', 'user_goal', 'instruction', 'answer_format', 'answer', 'input', 'output',
        'review_status', 'review_reason', 'sample_review', 'dedup_text'])))


def export_results(df, output_dir, tokenizer_path=None, max_tokens=6144):
    """Export before filtering so all review outcomes remain auditable.

    A fresh directory per invocation prevents overwrite. The returned frame
    retains source bindings for the platform's ordinary text-SFT collection.
    """
    root = Path(output_dir).expanduser().resolve() / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=False)
    all_rows = df.to_dict('records')
    tokenizer = None
    if tokenizer_path:
        from transformers import AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained(tokenizer_path, local_files_only=True, trust_remote_code=False)

    kept, seen = [], set()
    for row in all_rows:
        row['export_status'] = row['review_status']
        if tokenizer is not None and row['review_status'] == 'PASS':
            messages = [{'role':'user','content':'\n'.join(v for v in (row['instruction'], row['input']) if v)},
                        {'role':'assistant','content':row['output']}]
            tokens = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=False, enable_thinking=False)
            row['training_tokens'] = len(tokens)
            row['training_tokenizer'] = str(tokenizer_path)
            row['training_cutoff'] = max_tokens
            if len(tokens) > max_tokens:
                row['export_status'] = 'TOO_LONG'
                continue
        if row['review_status'] == 'PASS':
            if row['dedup_text'] in seen:
                row['export_status'] = 'DUPLICATE'
            else:
                seen.add(row['dedup_text'])
                row['sft_row'] = len(kept) + 1
                kept.append(row)
    def safe(value):
        if isinstance(value, dict): return {k: safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)): return [safe(v) for v in value]
        if isinstance(value, float) and not math.isfinite(value): return None
        return value
    def write(name, records):
        with (root / name).open('w', encoding='utf-8') as stream:
            for record in records:
                stream.write(dumps(safe(record)) + '\n')
    write('sft.jsonl', [{k: r[k] for k in ('instruction', 'input', 'output')} for r in kept])
    write('audit.jsonl', all_rows)
    write('record_mapping.jsonl', [dict(sample_id=r['sample_id'], sft_row=r['sft_row'],
        document_id=r.get('document_id'), source=r.get('source'), material_id=r.get('material_id'),
        source_map=r['source_map']) for r in kept])
    summary = {'reviewed': len(all_rows), 'accepted': len(kept),
        'outcomes': dict(Counter(r['export_status'] for r in all_rows)),
        'tasks': dict(Counter(r['task_type'] for r in kept)),
        'model_calls_performed_by_exporter': 0}
    (root / 'summary.json').write_text(dumps(summary) + '\n', encoding='utf-8')
    result = pd.DataFrame(kept, columns=list(dict.fromkeys([*df.columns, 'export_status', 'sft_row'])))
    result['export_dir'] = str(root)
    return result
