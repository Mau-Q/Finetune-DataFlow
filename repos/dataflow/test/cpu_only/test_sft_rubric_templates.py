"""Optional rubrics preserve sample inputs, score protocols and built-in defaults."""
import pandas as pd
from dataflow.core.prompt import DIYPromptABC
from dataflow.operators.core_text import Text2QASampleEvaluator
from dataflow.operators.text_sft import AlpagasusSampleEvaluator


class Rubric(DIYPromptABC):
    def __init__(self,text):self.text=text
    def build_prompt(self):return self.text


class Serving:
    def __init__(self,response):self.response=response;self.seen=[]
    def generate_from_input(self,user_inputs,**kwargs):
        self.seen.extend(user_inputs)
        return [self.response]*len(user_inputs)


class Storage:
    def __init__(self,row):self.frame=pd.DataFrame([row])
    def read(self,_):return self.frame.copy()
    def write(self,frame):self.frame=frame


def test_optional_rubrics_are_independent_and_keep_evidence_and_score_protocol():
    serving=Serving('**Grading**: 4\n**Feedback**: supported')
    evaluator=Text2QASampleEvaluator(serving,answer_verifiability_prompt_template=Rubric('CUSTOM evidence rubric'))
    storage=Storage(dict(q='QUESTION',a='ANSWER',source='SOURCE evidence'))
    evaluator.run(storage,input_question_key='q',input_answer_key='a',input_context_key='source')
    assert 'CUSTOM evidence rubric' not in serving.seen[0]
    assert 'CUSTOM evidence rubric' in serving.seen[2]
    assert all(part in serving.seen[2] for part in ('SOURCE evidence','QUESTION','ANSWER','**Grading**','1 to 5'))
    assert storage.frame.answer_verifiability_grades.tolist()==[4]
    assert evaluator._parse_grade_and_feedback('**Grading**: 6\n**Feedback**: bad')[0] is None


def test_alpagasus_optional_rubric_keeps_inputs_and_rejects_nonfinite_score():
    serving=Serving('0\nNo evidence')
    evaluator=AlpagasusSampleEvaluator(serving,prompt_template=Rubric('CUSTOM grading criteria'))
    row=dict(q='QUESTION',i='CONTEXT',a='ANSWER')
    assert evaluator.get_score([row],'q','i','a')==[0]
    assert all(part in serving.seen[0] for part in ('CUSTOM grading criteria','QUESTION','CONTEXT','ANSWER','0 to 5'))
    serving.response='nan'
    assert evaluator.get_score([row],'q','i','a')==[None]


def test_default_alpagasus_keeps_dimension_rubric():
    serving=Serving('4\nGood')
    evaluator=AlpagasusSampleEvaluator(serving,dimension='helpfulness')
    evaluator.get_score([dict(q='Q',i='',a='A')],'q','i','a')
    assert 'helpfulness' in serving.seen[0] and 'CUSTOM' not in serving.seen[0]
