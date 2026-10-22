import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from paper_dataflow.low_cost_sft import (
    prepare_sources, parse_candidates, parse_reviews, export_results,
    build_contexts, strict_json, select_paper_contexts,
)


def candidate(instruction='解释方法', answer='依据材料解释'):
    return dict(reader_level='初学者', user_goal='理解方法', task_type='解释',
                instruction=instruction, answer_format='text', answer=answer)


def batch(samples=None):
    return pd.DataFrame([dict(unit_id='u1', context='原始材料', context_scope='section_or_blocks',
        source_map=[dict(page_number=1)], source='paper.pdf', document_id='doc',
        generation_raw=json.dumps(dict(keywords=['方法'], samples=samples or [candidate()]), ensure_ascii=False))])


def reviewed(reviews):
    df = parse_candidates(batch())
    df['review_raw'] = json.dumps(dict(reviews=reviews))
    return parse_reviews(df)


def verdict(sid='u1:c1', **changes):
    return dict(sample_id=sid, grounded='PASS', task_fit='PASS', usefulness='PASS', reason='') | changes


def test_paper_budget_preserves_all_evidence_but_admits_at_most_eight_candidates():
    original = pd.DataFrame([dict(document_id=doc, unit_id=f'{doc}-{i}', context_valid=True,
                                  context=f'exact original {doc}-{i}', preparation_reason='')
                             for doc in ('a', 'b') for i in range(10)])
    selected = {'a': {'a-1': 1, 'a-3': 3, 'a-6': 4}, 'b': {f'b-{i}': 1 for i in range(8)}}
    result = select_paper_contexts(original, selected)
    assert result['context'].tolist() == original['context'].tolist()
    assert len(result) == 20
    assert result.loc[result.context_valid].groupby('document_id').size().to_dict() == {'a': 3, 'b': 8}
    assert result.groupby('document_id').generation_sample_budget.sum().to_dict() == {'a': 8, 'b': 8}
    assert '最多样本数：4' in result.loc[result.unit_id == 'a-6', 'generation_input'].iloc[0]
    assert original.context_valid.all()
    with pytest.raises(ValueError):
        select_paper_contexts(original, {'a': {'a-1': 9}, 'b': {}})
    with pytest.raises(ValueError):
        select_paper_contexts(original, {'a': {'b-0': 1}, 'b': {'b-1': 1}})
    original.loc[original.unit_id == 'a-1', 'context_valid'] = False
    with pytest.raises(ValueError):
        select_paper_contexts(original, selected)


def test_paper_budget_allows_empty_plans_and_rejects_invalid_allocations():
    frame = pd.DataFrame([dict(document_id=doc, unit_id=doc, context_valid=True, context='evidence')
                          for doc in ['a', 'b', 'c']])
    plans = {'a': {'a': 7}, 'b': {'b': 1}, 'c': {}}
    result = select_paper_contexts(frame, plans)
    assert result.generation_sample_budget.tolist() == [7, 1, 0]
    assert result.context_valid.tolist() == [True, True, False]
    with pytest.raises(ValueError, match='paper candidate'):
        select_paper_contexts(frame, plans, 6)
    with pytest.raises(ValueError, match='positive integer'):
        select_paper_contexts(frame, plans, None)
    for count in [True, 0, -1, 1.5]:
        with pytest.raises(ValueError, match='positive sample counts'):
            select_paper_contexts(frame, {'a': {'a': count}, 'b': {}, 'c': {}})


def test_candidate_protocol_enforces_variable_allocation_and_preserves_raw_response():
    frame = batch([candidate(str(i)) for i in range(5)])
    frame['generation_sample_budget'] = 5
    assert parse_candidates(frame, max_samples=2).iloc[0].candidate_count == 5
    frame['generation_sample_budget'] = 4
    result = parse_candidates(frame).iloc[0]
    assert result.candidate_count == 0
    assert result.generation_raw == frame.iloc[0].generation_raw
    assert 'exceeds budget' in result.invalid_candidates[0]['reason']


def test_duplicate_pdf_aliases_and_split_isolation(tmp_path):
    p = tmp_path / 'a.pdf'; p.write_bytes(b'%PDF-1.7\nfixture')
    df = pd.DataFrame([dict(source=str(p), material_id='a'), dict(source=str(p), material_id='b')])
    result = prepare_sources(df)
    assert len(result) == 1 and len(result.iloc[0]['source_aliases']) == 2
    df['split'] = ['train', 'test']
    with pytest.raises(ValueError, match='multiple splits'): prepare_sources(df)


def test_invalid_candidate_isolated_without_losing_valid_one():
    bad = candidate(); bad['answer_format'] = 'json'; bad['answer'] = 'invalid'
    result = parse_candidates(batch([candidate(), bad])).iloc[0]
    assert result['candidate_count'] == 1 and len(result['invalid_candidates']) == 1
    assert result['candidates'][0]['sample_id'] == 'u1:c1'


@pytest.mark.parametrize('raw', ['not json', '{"reviews":[],"reviews":[]}', 'null'])
def test_malformed_review_never_passes(raw):
    df = parse_candidates(batch()); df['review_raw'] = raw
    result = parse_reviews(df)
    assert result.iloc[0]['review_status'] == 'REVIEW'


def test_review_matches_id_not_order_and_retains_missing():
    df = parse_candidates(batch([candidate('问题A'), candidate('问题B')]))
    df['review_raw'] = json.dumps(dict(reviews=[verdict('u1:c2')]))
    result = parse_reviews(df)
    assert result['review_status'].tolist() == ['REVIEW', 'PASS']


@pytest.mark.parametrize('reviews', [[verdict(), verdict()], [verdict('unknown')]])
def test_bad_ids_invalidate_entire_batch(reviews):
    assert reviewed(reviews).iloc[0]['review_status'] == 'REVIEW'


def test_fail_overrides_uncertainty_and_requires_reason():
    result = reviewed([verdict(grounded='FAIL', usefulness='UNCERTAIN', reason='数值错误')])
    assert result.iloc[0]['review_status'] == 'REJECT'
    assert reviewed([verdict(grounded='FAIL')]).iloc[0]['review_status'] == 'REVIEW'


def test_export_preserves_rejections_deduplicates_and_does_not_overwrite(tmp_path):
    good = reviewed([verdict()]); bad = reviewed([verdict(grounded='FAIL', reason='错误')])
    df = pd.concat([good, good, bad], ignore_index=True)
    first = export_results(df, tmp_path); second = export_results(df, tmp_path)
    root = Path(first.iloc[0]['export_dir'])
    assert len(first) == 1 and first.iloc[0]['input'] == '原始材料'
    assert root != Path(second.iloc[0]['export_dir'])
    assert len((root / 'audit.jsonl').read_text().splitlines()) == 3
    summary = json.loads((root / 'summary.json').read_text())
    assert summary['outcomes'] == {'PASS': 1, 'DUPLICATE': 1, 'REJECT': 1}
    assert set(json.loads((root / 'sft.jsonl').read_text())) == {'instruction', 'input', 'output'}


def test_all_rejected_export_keeps_empty_training_columns(tmp_path):
    result = export_results(reviewed([verdict(grounded='FAIL', reason='错误')]), tmp_path)
    assert result.empty and {'instruction', 'input', 'output'}.issubset(result.columns)
    assert list(tmp_path.glob('*/sft.jsonl'))[0].read_text() == ''


def test_context_budget_never_silently_truncates():
    class Counter:
        def __init__(self, *args, **kwargs): pass
        def count(self, text): return len(text)
    meta = dict(document_id='doc', chunk_id='c1', page_numbers=[1],
                source_segments=[dict(page_number=1, char_start=0, char_end=20)],
                eligible_for_qa=True, section_title='方法', flags=[])
    df = pd.DataFrame([dict(raw_chunk='x' * 20, chunk_metadata=meta)])
    with patch('paper_dataflow.operators.paper.generate.structured_chunking.PaperStructuredChunker', Counter):
        result = build_contexts(df, 'unused', context_tokens=10)
    assert not result.iloc[0]['context_valid'] and 'x' * 20 in result.iloc[0]['context']


def test_strict_json_rejects_nonfinite_and_duplicate_keys():
    for value in ['{"a":1,"a":2}', '{"v":NaN}']:
        with pytest.raises(ValueError): strict_json(value)


def test_saved_transform_chain_with_fixture_responses(tmp_path):
    """Exercise saved dynamic Pandas bindings, without a PDF/model invocation."""
    from dataflow.operators.core_text import PandasOperator
    from dataflow.prompts.core_text import FormatStrPrompt
    import jsonschema

    resources = Path(__file__).resolve().parents[3] / 'pipelines/paper-multitask-low-cost'
    nodes = json.loads((resources / 'pipeline.webui.json').read_text())['config']['operators']
    class Storage:
        def __init__(self, df): self.df = df
        def read(self, kind): return self.df
        def write(self, df): self.df = df
    storage = Storage(batch())
    def apply(index):
        values = {v['name']: v['value'] for v in nodes[index]['params']['init']}
        functions = [eval(expr) for expr in values['process_fn']]
        PandasOperator(functions).run(storage,
            output_key=nodes[index]['params']['run'][0]['value'])

    apply(7)
    candidate_row = storage.df.iloc[0]
    generated = json.loads(candidate_row['generation_raw'])
    jsonschema.validate(generated, json.loads((resources / 'generate.schema.json').read_text()))
    rendered = FormatStrPrompt((resources / 'review.txt').read_text()).build_prompt(
        {'batch'}, batch=candidate_row['review_input'])
    assert '原始材料' in rendered and 'u1:c1' in rendered and '{batch}' not in rendered
    review = dict(reviews=[verdict()])
    jsonschema.validate(review, json.loads((resources / 'review.schema.json').read_text()))
    storage.df['review_raw'] = json.dumps(review)
    apply(10)
    # Redirect only the exporter destination; never write production outputs.
    with patch('paper_dataflow.low_cost_sft.export_results',
               side_effect=lambda df, **kwargs: export_results(df, tmp_path)):
        apply(11)
    assert storage.df.iloc[0]['review_status'] == 'PASS'
    assert storage.df.iloc[0]['input'] == '原始材料'
    assert list(tmp_path.glob('*/record_mapping.jsonl'))


def test_full_training_length_rejects_without_truncation(tmp_path, monkeypatch):
    import transformers
    from types import SimpleNamespace
    seen = []
    def apply(messages, **kwargs):
        seen.append(messages)
        return list(range(7000))
    monkeypatch.setattr(transformers.AutoTokenizer, 'from_pretrained', lambda *a, **k: SimpleNamespace(apply_chat_template=apply))
    frame = reviewed([verdict()])
    result = export_results(frame, tmp_path, tokenizer_path='offline-fixture', max_tokens=6144)
    assert result.empty
    directory, = list(tmp_path.iterdir())
    audit = json.loads((directory/'audit.jsonl').read_text())
    assert audit['export_status'] == 'TOO_LONG' and audit['training_tokens'] == 7000
    assert audit['output'] == '依据材料解释'
    assert seen[0][0]['content'] == '解释方法\n原始材料'
