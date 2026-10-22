import pandas as pd
import pytest

from paper_dataflow.context_selection import propose_contexts, budget_contexts
from paper_dataflow.low_cost_sft import select_paper_contexts


def item(unit, title, text, valid=True, doc='paper'):
    return dict(document_id=doc, unit_id=unit, context=text, raw_chunk=text,
                context_tokens=200, context_valid=valid,
                chunk_metadata={'section_title': title},
                source_map=[{'page_number': 1, 'char_start': 0, 'char_end': len(text)}])


def test_coverage_escapes_repeated_early_sections_and_keeps_exact_evidence():
    rows = [item(str(i), 'Method', 'training data sampling model recipe') for i in range(4)]
    rows += [item('r', 'Results', 'benchmark accuracy improved against baseline'),
             item('l', 'Limitations', 'failure under distribution shift remains unresolved'),
             item('ref', 'References', 'benchmark accuracy citation bibliography'),
             item('bad', 'Ablation', 'corrupt table', False)]
    frame = pd.DataFrame(rows)
    selections, traces = propose_contexts(frame)
    assert set(selections['paper']) == {'0', 'r', 'l'}
    assert traces['paper']['covered_roles'] == ['boundary', 'experiment', 'method']
    allocations = {doc: {unit: 1 for unit in units} for doc, units in selections.items()}
    output = select_paper_contexts(frame, allocations)
    assert len(output) == len(frame)
    assert output.context.tolist() == frame.context.tolist()
    assert output.source_map.tolist() == frame.source_map.tolist()
    assert frame.context_valid.sum() == 7
    assert output.context_valid.sum() == 3
    shuffled, _ = propose_contexts(frame.sample(frac=1, random_state=17))
    assert selections == shuffled
    bounded = budget_contexts(frame, {'paper': {'0': 3, 'r': 4, 'l': 1}})
    assert bounded.generation_sample_budget.sum() == 8
    assert bounded.loc[bounded.unit_id == 'r', 'generation_sample_budget'].iloc[0] == 4


def test_budget_is_per_paper_and_duplicate_ids_fail_closed():
    frame = pd.DataFrame([item(str(i), 'Results', f'experiment measure value{i}', doc=doc)
                          for doc in ['a', 'b'] for i in range(5)])
    selections, _ = propose_contexts(frame, max_contexts=2)
    assert {doc: len(ids) for doc, ids in selections.items()} == {'a': 2, 'b': 2}
    duplicate = pd.concat([frame, frame.iloc[:1]])
    with pytest.raises(ValueError, match='Duplicate'):
        propose_contexts(duplicate)
    with pytest.raises(ValueError, match='Duplicate'):
        select_paper_contexts(duplicate, selections)
    with pytest.raises(ValueError, match='No eligible'):
        propose_contexts(pd.DataFrame([item('x', 'References', 'citation')]))
    unbounded, _ = propose_contexts(frame)
    assert all(len(units) == 5 for units in unbounded.values())
