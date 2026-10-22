"""No live database/model writes: replay mixed batches through real finalization."""
import json
from pathlib import Path
from types import SimpleNamespace
import pandas as pd
import pytest
from app.services.simple_training_operators import TrainingPairFormatter, APIImagePairGenerator, same_answer
from app.services.representative_training_operators import TrainingPreferenceBuilder, TrainingQAExpander
from app.services.task_artifacts import finalize_artifacts
from app.services.result_storage import persist

class Storage:
    def __init__(self,rows):self.frame=pd.DataFrame(rows)
    def read(self,_):return self.frame.copy()
    def write(self,frame):self.frame=frame.copy()


def formatter(kind,mode):
    keys=['question','answer'] if kind=='sft' else ['question','chosen','rejected']
    schema=dict(type='object',properties={k:dict(type='string',minLength=1) for k in keys},required=keys)
    return TrainingPairFormatter(kind,mode,schema,allow_empty=True)

@pytest.mark.parametrize('kind',['sft','dpo'])
@pytest.mark.parametrize('mode',['text','image_text'])
def test_invalid_row_cannot_discard_valid_batch_or_final_file(tmp_path,kind,mode):
    good=dict(question='Q',**(dict(answer='A') if kind=='sft' else dict(chosen='A',rejected='B')))
    bad='not json' if kind=='sft' else dict(question='Q',chosen='268',rejected='268')
    rows=[dict(text='source',media_ref='images/a.png',candidate=c) for c in [good,bad,good]]
    storage=Storage(rows);formatter(kind,mode).run(storage)
    assert [isinstance(v,dict) for v in storage.frame['training_sample']]==[True,False,True]
    root=tmp_path/'cache'/'fixture_output';root.mkdir(parents=True)
    path=root/'dataflow_cache_step_step1.jsonl';storage.frame.to_json(path,orient='records',lines=True,force_ascii=False)
    output_dir=tmp_path/'results';output_dir.mkdir()
    config={'operators':[{}],'execution_options':dict(capture_responses=True,training_output=True,simple_training=dict(modality=mode,training_type=kind),result_directory=str(output_dir))}
    result=dict(task_id='fixture',status='completed',output={'execution_results':[dict(index=0,file_path=str(path))]},logs=[])
    finalize_artifacts(config,result,tmp_path/'cache');persist(config,result)
    assert result['status']=='completed'
    assert result['output']['sample_summary']==dict(valid=2,invalid=1)
    assert len(Path(result['output']['final_file']).read_text().splitlines())==2
    rejected=json.loads(Path(result['output']['invalid_samples_file']).read_text())
    assert rejected['row_index']==1 and rejected['source']['candidate']==bad and rejected['reasons']

@pytest.mark.parametrize('a,b',[('268','268'),('4','4小时'),(' 4 小时 ','4小时'),('answer。','answer')])
def test_equal_answer_recognizes_conservative_format_variations(a,b):assert same_answer(a,b)

def test_numeric_values_with_different_units_are_not_declared_equal():
    assert not same_answer('4秒','4小时')
    assert not same_answer('4.5','45')

@pytest.mark.parametrize('mode',['text','image_text'])
def test_negative_regeneration_uses_context_and_stops_after_success(tmp_path,mode):
    from PIL import Image
    path=tmp_path/'image.png';Image.new('RGB',(3,3),'red').save(path)
    row=dict(text='original source',source=str(path),candidate_a=dict(question='Q',answer='268'),candidate_b=dict(question='Q',answer='268'))
    if mode=='image_text':row['media_ref']='images/a.png'
    calls=[]
    def reply(prompts):
        calls.append(prompts)
        return [json.dumps(dict(question='Q',answer='269'))]
    serving=SimpleNamespace(generate_from_input=reply,generate_from_conversations=reply)
    storage=Storage([row]);TrainingPreferenceBuilder(serving,2).run(storage)
    assert len(calls)==1 and storage.frame.iloc[0]['alternatives']['answer_b']=='269'
    assert not storage.frame.iloc[0]['_training_issues']
    assert len(storage.frame.iloc[0]['negative_retry_responses'])==1
    assert ('original source' in str(calls)) if mode=='text' else ('data:image/png;base64,' in str(calls))


def test_exhausted_row_keeps_other_pairs_and_records_all_retry_responses():
    calls=[]
    def reply(prompts):calls.append(prompts);return [json.dumps(dict(question='Q',answer='268'))]
    serving=SimpleNamespace(generate_from_input=reply)
    storage=Storage([dict(text='source',candidate_a=dict(question='Q',answer='268'),candidate_b=dict(question='Q',answer=b)) for b in ['268','269']])
    TrainingPreferenceBuilder(serving,2).run(storage)
    assert len(calls)==2
    assert storage.frame.iloc[0]['_training_issues'] and len(storage.frame.iloc[0]['negative_retry_responses'])==2
    assert storage.frame.iloc[1]['alternatives']['answer_b']=='269' and not storage.frame.iloc[1]['_training_issues']


def test_invalid_text_qa_does_not_discard_other_source():
    storage=Storage([dict(text='a',qa_pairs=[None]),dict(text='b',qa_pairs=[dict(question='Q',answer='A')])])
    TrainingQAExpander().run(storage)
    assert len(storage.frame)==2 and storage.frame.iloc[0]['_training_issues']
    assert storage.frame.iloc[1]['candidate']['answer']=='A'


def test_all_invalid_rows_produce_empty_final_and_full_diagnostics(tmp_path):
    storage=Storage([dict(candidate='bad')]);formatter('sft','text').run(storage)
    assert storage.frame['training_sample'].tolist()==[None]
    cache=tmp_path/'cache';step=cache/'empty_output'/'step.jsonl';step.parent.mkdir(parents=True)
    storage.frame.to_json(step,orient='records',lines=True)
    destination=tmp_path/'result';destination.mkdir()
    config={'operators':[{}],'execution_options':dict(capture_responses=True,training_output=True,simple_training=dict(modality='text',training_type='sft'),result_directory=str(destination))}
    result=dict(task_id='empty',status='completed',output={'execution_results':[dict(index=0,file_path=str(step))]},logs=[])
    finalize_artifacts(config,result,cache);persist(config,result)
    assert result['output']['sample_summary']==dict(valid=0,invalid=1)
    assert Path(result['output']['final_file']).read_bytes()==b''
    assert Path(result['output']['invalid_samples_file']).is_file()


def test_retry_transport_failure_remains_bounded_and_local():
    calls=[]
    def failed(prompts):calls.append(prompts);raise TimeoutError('fixture')
    storage=Storage([dict(text='source',candidate_a=dict(question='Q',answer='A'),candidate_b=dict(question='Q',answer='A'))])
    TrainingPreferenceBuilder(SimpleNamespace(generate_from_input=failed),2).run(storage)
    assert len(calls)==2 and storage.frame.iloc[0]['_training_issues']
    assert storage.frame.iloc[0]['negative_retry_responses']==[{'error_type':'TimeoutError'}]*2


def test_migration_preserves_inputs_and_original_serving_and_is_idempotent():
    from app.services.representative_training import isolate_rows
    import copy
    config={'input_dataset':{'id':'original'},'execution_options':{},'operators':[
        {'name':'Generator','params':{'init':[{'name':'llm_serving','value':'my-service'}],'run':[]}},
        {'name':'TrainingPreferenceBuilder','params':{'init':[],'run':[{'name':'input_key','value':'a'}]}}]}
    old=copy.deepcopy(config);migrated=isolate_rows(config)
    assert config==old and migrated['input_dataset']==old['input_dataset']
    params={p['name']:p['value'] for p in migrated['operators'][1]['params']['init']}
    assert params==dict(llm_serving='my-service',max_negative_retries=2)
    assert isolate_rows(migrated)==migrated


def test_image_generation_isolates_invalid_paths_and_context_without_row_misalignment(tmp_path):
    from PIL import Image
    path=tmp_path/'image.png';Image.new('RGB',(3,3),'red').save(path)
    calls=[]
    def reply(conversations):calls.extend(conversations);return [json.dumps(dict(question='Q',answer='A')) for _ in conversations]
    storage=Storage([dict(source=None,question={'question':'Q'},media_ref='images/a.png'),
        dict(source=str(path),question={'question':'Q','invalid':float('nan')},media_ref='images/a.png'),
        dict(source=str(path),question={'question':'Q'},media_ref='images/a.png')])
    APIImagePairGenerator(SimpleNamespace(generate_from_conversations=reply),SimpleNamespace(build_prompt=lambda:'fixture')).run(storage,input_context_key='question')
    assert len(calls)==1
    assert storage.frame['candidate'].tolist()[:2]==['','']
    formatter('sft','image_text').run(storage)
    assert [isinstance(v,dict) for v in storage.frame['training_sample']]==[False,False,True]
