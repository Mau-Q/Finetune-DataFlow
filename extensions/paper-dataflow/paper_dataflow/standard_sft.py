"""Paper-level planning and bounded coverage selection for the standard SFT flow."""
import json
import pandas as pd
from paper_dataflow.low_cost_sft import build_contexts, dumps, strict_json, parse_candidates


def planning_rows(df, tokenizer_path, context_tokens=3000):
    contexts = build_contexts(df, tokenizer_path, context_tokens, max_samples=8)
    rows = []
    for doc, group in contexts.groupby('document_id', sort=False):
        items = group.to_dict('records')
        index = [dict(unit_id=r['unit_id'], section=r['chunk_metadata'].get('section_title', ''),
                      pages=r['chunk_metadata'].get('page_numbers', []), eligible=bool(r['context_valid']),
                      excerpt=r['context'][:700]) for r in items]
        rows.append(dict(items[0], all_contexts=items, planning_input=dumps(dict(document_id=doc,
            scope='section index with excerpts, not full text; answers must use original blocks', contexts=index))))
    return pd.DataFrame(rows)


def apply_plans(df, tokenizer_path, context_tokens=3000, max_candidates_per_paper=8):
    """Greedy goal cover followed by redundant-plan deletion, with exact evidence."""
    from paper_dataflow.operators.paper.generate.structured_chunking import PaperStructuredChunker
    count = PaperStructuredChunker(tokenizer_path, context_tokens).count
    if type(max_candidates_per_paper) is not int or not 1 <= max_candidates_per_paper <= 8:
        raise ValueError('Standard paper candidate cap must be 1..8')
    output = []
    for paper in df.to_dict('records'):
        contexts = {r['unit_id']: r for r in paper['all_contexts']}
        error, selected, goals, feasible = '', [], {}, []
        try:
            plan = strict_json(paper['planning_raw'])
            if not isinstance(plan, dict) or set(plan) != {'goals', 'tasks'}:
                raise ValueError('Expected goals and tasks')
            if not isinstance(plan['goals'], list) or not 1 <= len(plan['goals']) <= 12:
                raise ValueError('Expected 1..12 core goals')
            for goal in plan['goals']:
                if (not isinstance(goal, dict) or set(goal) != {'id', 'description'}
                        or not all(isinstance(goal[k], str) and goal[k].strip() for k in goal)
                        or goal['id'] in goals):
                    raise ValueError('Invalid or duplicate core goal')
                goals[goal['id']] = goal['description']
            if not isinstance(plan['tasks'], list) or len(plan['tasks']) > 16:
                raise ValueError('Expected at most 16 task specifications')
            seen = set()
            for task in plan['tasks']:
                if not isinstance(task, dict) or set(task) != {'instruction', 'goal_ids', 'unit_ids'}:
                    raise ValueError('Invalid task specification')
                instruction, ids, units = task['instruction'], task['goal_ids'], task['unit_ids']
                if not isinstance(instruction, str) or not instruction.strip():
                    raise ValueError('Empty task instruction')
                if (not isinstance(ids, list) or not ids or len(set(ids)) != len(ids)
                        or any(g not in goals for g in ids)
                        or not isinstance(units, list) or not units or len(set(units)) != len(units)
                        or any(u not in contexts or not contexts[u]['context_valid'] for u in units)):
                    raise ValueError('Task references missing or ineligible evidence/goal')
                key = ' '.join(instruction.split())
                if key in seen:
                    continue
                seen.add(key)
                text = '\n\n'.join(contexts[u]['context'] for u in units)
                if count(text) > context_tokens:
                    continue  # Keep full plan + source; never truncate evidence to make it fit.
                feasible.append(dict(task, context=text, context_tokens=count(text)))
            covered = set()
            remaining = list(feasible)
            while remaining and len(selected) < max_candidates_per_paper:
                best = max(remaining, key=lambda t: (len(set(t['goal_ids'])-covered), -t['context_tokens']))
                if not set(best['goal_ids'])-covered:
                    break
                selected.append(best);covered.update(best['goal_ids']);remaining.remove(best)
            # Remove a specification only if the other selected specs cover all its goals.
            for task in list(reversed(selected)):
                others = set(g for t in selected if t is not task for g in t['goal_ids'])
                if set(task['goal_ids']) <= others:
                    selected.remove(task)
        except (ValueError, TypeError, KeyError) as exc:
            error, selected = 'planning_protocol_error: '+str(exc), []
        covered = {g for t in selected for g in t['goal_ids']}
        audit = dict(algorithm='greedy-core-goal-cover-with-backward-deletion-v1',
                     core_goals=goals, covered_goals=sorted(covered), uncovered_goals=sorted(set(goals)-covered),
                     feasible_task_count=len(feasible), planned_samples=len(selected),
                     max_candidates_per_paper=max_candidates_per_paper, error=error)
        bundles = []
        for task in selected:
            for bundle in bundles:
                units = list(dict.fromkeys([*bundle['unit_ids'], *task['unit_ids']]))
                if count('\n\n'.join(contexts[u]['context'] for u in units)) <= context_tokens:
                    bundle['unit_ids'] = units;bundle['tasks'].append(task);break
            else:
                bundles.append(dict(unit_ids=list(task['unit_ids']), tasks=[task]))
        # Unselected evidence is retained by planning_rows, not duplicated into every generation row.
        for index, bundle in enumerate(bundles or [None]):
            row = dict(paper)
            row.pop('all_contexts', None)
            allowance = len(bundle['tasks']) if bundle else 0
            row.update(paper_plan_audit=audit, context_valid=bundle is not None,
                       generation_sample_budget=allowance,
                       preparation_reason='' if bundle else error or 'no_evidence_grounded_task',
                       original_planning_raw=paper.get('planning_raw'))
            if bundle:
                parts = [contexts[u] for u in bundle['unit_ids']]
                text = '\n\n'.join(part['context'] for part in parts)
                instructions = [task['instruction'] for task in bundle['tasks']]
                row.update(unit_id=paper['document_id']+':plan-group'+str(index+1), context=text,
                           context_scope='section_or_blocks', context_tokens=count(text),
                           source_map=[s for part in parts for s in part['source_map']], planned_instructions=instructions,
                           goal_ids=sorted({g for t in bundle['tasks'] for g in t['goal_ids']}),
                           evidence_unit_ids=bundle['unit_ids'])
                row['generation_input'] = ('最多样本数：'+str(allowance)+'\n仅完成以下已规划任务，instruction 必须逐字保留，每个任务至多一条；'
                    '证据不足时跳过该任务，不另创任务。\n任务列表：'+dumps(instructions)+
                    '\n<material>\n'+text+'\n</material>')
            output.append(row)
    return pd.DataFrame(output)


def parse_planned_candidates(df):
    result = parse_candidates(df, max_samples=8)
    rows = []
    for row in result.to_dict('records'):
        accepted, seen = [], set()
        for candidate in row['candidates']:
            if candidate['instruction'] not in row.get('planned_instructions', []) or candidate['instruction'] in seen:
                row['invalid_candidates'].append(dict(reason='instruction differs from allocated task', candidate=candidate))
            else:
                accepted.append(candidate);seen.add(candidate['instruction'])
        row['candidates'], row['candidate_count'] = accepted, len(accepted)
        row['review_input'] = (f"材料范围：{row['context_scope']}\n<material>\n{row['context']}\n</material>\n"
                               f"<candidates>\n{dumps(accepted)}\n</candidates>")
        rows.append(row)
    return pd.DataFrame(rows, columns=result.columns)
