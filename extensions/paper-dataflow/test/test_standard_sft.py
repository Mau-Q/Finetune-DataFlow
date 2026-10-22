import json
from unittest.mock import patch
import pandas as pd
from paper_dataflow.standard_sft import apply_plans, parse_planned_candidates

class Counter:
    def __init__(self,*args,**kwargs):pass
    def count(self,text):return len(text)

def task(instruction,goals,units):return dict(instruction=instruction,goal_ids=goals,unit_ids=units)

def frame(tasks):
    units=[dict(unit_id='u'+str(i),context='original evidence '+str(i),context_valid=i!=3,
           source_map=[dict(page_number=i+1)],context_scope='section_or_blocks') for i in range(4)]
    return pd.DataFrame([dict(document_id='doc',source='file.pdf',all_contexts=units,
        planning_raw=json.dumps(dict(goals=[dict(id='a',description='method'),dict(id='b',description='boundary')],tasks=tasks)))])

def run(tasks,cap=8,tokens=3000):
    with patch('paper_dataflow.operators.paper.generate.structured_chunking.PaperStructuredChunker',Counter):
        return apply_plans(frame(tasks),'unused',tokens,cap)

def test_goal_cover_removes_redundancy_and_preserves_packed_exact_evidence():
    result=run([task('explain method',['a'],['u0']),task('repeat method',['a'],['u1']),task('explain boundary',['b'],['u2'])])
    assert len(result)==1
    row=result.iloc[0]
    assert row.generation_sample_budget==2
    assert row.planned_instructions==['explain method','explain boundary']
    assert row.context=='original evidence 0\n\noriginal evidence 2'
    assert row.source_map==[dict(page_number=1),dict(page_number=3)]
    assert row.paper_plan_audit['uncovered_goals']==[]

def test_budget_and_bad_evidence_never_trigger_extra_generation():
    row=run([task('method',['a'],['u0']),task('boundary',['b'],['u2'])],cap=1).iloc[0]
    assert row.generation_sample_budget==1 and row.paper_plan_audit['uncovered_goals']==['b']
    bad=run([task('corrupt',['a'],['u3'])]).iloc[0]
    assert not bad.context_valid and 'planning_protocol_error' in bad.preparation_reason
    long=run([task('large',['a'],['u0','u1'])],tokens=5).iloc[0]
    assert not long.context_valid and long.paper_plan_audit['planned_samples']==0

def test_generator_cannot_replace_or_duplicate_planned_task():
    row=run([task('planned',['a'],['u0'])])
    sample=dict(reader_level='student',user_goal='learn',task_type='explain',instruction='invented',answer_format='text',answer='answer')
    row['generation_raw']=json.dumps(dict(keywords=[],samples=[sample]))
    result=parse_planned_candidates(row).iloc[0]
    assert result.candidate_count==0 and result.invalid_candidates[0]['reason']=='instruction differs from allocated task'
    assert {'candidate_count','candidates'}.issubset(parse_planned_candidates(row.iloc[:0]).columns)
