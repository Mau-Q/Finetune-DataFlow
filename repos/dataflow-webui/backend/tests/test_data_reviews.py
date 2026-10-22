from concurrent.futures import ThreadPoolExecutor
import copy
import pytest
from app.services.data_library import DataLibrary, LibraryError
from app.services.data_reviews import DataReviews, revision
from app.services.training_lifecycle import TrainingLifecycle
from app.schemas.data_library import DraftCreate

ROLES=['develop','review']


@pytest.fixture
def setup(tmp_path):
    lib=DataLibrary(tmp_path/'data/library');draft=lib.create_draft(DraftCreate(name='review',modality='text',training_type='sft'))
    lib.import_rows(draft['id'],'a.jsonl',b'{"instruction":"Q1","output":"A1"}\n{"instruction":"Q2","output":"A2"}\n{"instruction":"Q3","output":"A3"}\n',{})
    service=DataReviews(lib);body={'source':draft['id'],'reviewers':['r1','r2'],'count':2,'seed':42,'request_id':'create'}
    batch=service.create(body,'dev')
    return lib,service,body,batch


def decision(item,**extras):
    return dict(version=item['version'],request_id='decision',scores={'correctness':5,'support':5,'usability':5},conclusion='pass',**extras)


def test_frozen_reproducible_members_and_atomic_claim(setup):
    lib,s,body,b=setup
    assert s.create(body,'dev')['id']==b['id']
    b2=s.create(dict(body,request_id='new'),'dev')
    items=s.detail(b['id'],'r1',['review'])['items']
    assert [i['sample_id'] for i in items]==[i['sample_id'] for i in s.detail(b2['id'],'r1',['review'])['items']]
    i=items[0];original=copy.deepcopy(i['row'])
    TrainingLifecycle(lib).edit(body['source'],i['sample_id'],{'instruction':'changed','output':'new'})
    assert s.detail(b['id'],'r1',['review'])['items'][0]['row']==original
    def claim(user):
        try:return s.action(b['id'],i['id'],'claim',{'version':1},user,['review'])['owner']
        except LibraryError as e:return e.status
    with ThreadPoolExecutor(2) as pool:r=list(pool.map(claim,['r1','r2']))
    assert r.count(409)==1
    owner=next(x for x in r if x!=409);claimed=s.detail(b['id'],owner,['review'])['items'][0]
    s.action(b['id'],i['id'],'release',{'version':claimed['version'],'reason':'reassign'},'dev',['develop'])
    with pytest.raises(LibraryError):s.action(b['id'],i['id'],'submit',decision(claimed),owner,['review'])


def test_revision_conflict_validation_idempotency_and_history(setup):
    lib,s,body,b=setup;i=s.detail(b['id'],'r1',['review'])['items'][0]
    i=s.action(b['id'],i['id'],'claim',{'version':1},'r1',['review'])
    i=s.action(b['id'],i['id'],'save',{'version':i['version'],'draft':{'comment':'later'},'skipped':True},'r1',['review'])
    assert s.detail(b['id'],'r1',['review'])['summary']['submitted']==0
    invalid=decision(i);invalid['scores']['correctness']={'unknown':'缺少来源'}
    with pytest.raises(LibraryError):s.action(b['id'],i['id'],'submit',invalid,'r1',['review'])
    release=TrainingLifecycle(lib).publish(body['source']);before=TrainingLifecycle(lib).download(release['id'],'jsonl').read_bytes()
    new={'instruction':'Q1 edited','output':'A edited'}
    submitted=s.action(b['id'],i['id'],'revise',decision(i,row=new,reason='修正回答'),'r1',['review'])
    assert submitted['revision']==revision(new) and submitted['original_row']!=new
    assert s.current_status(body['source'],'dev',['develop'])['batches'][0]['passed']==1
    assert s.action(b['id'],i['id'],'revise',decision(i,row=new,reason='修正回答'),'r1',['review'])==submitted
    assert TrainingLifecycle(lib).download(release['id'],'jsonl').read_bytes()==before
    derived=s.derive(b['id'],'dev',['develop']);assert derived['rows']==[new]
    assert s.current_status(derived['id'],'dev',['develop'])['batches'][0]['passed']==1
    TrainingLifecycle(lib).edit(body['source'],i['sample_id'],{'instruction':'concurrent','output':'new'})
    assert s.current_status(body['source'],'dev',['develop'])['batches'][0]['passed']==0
    assert s.current_status(body['source'],'dev',['develop'])['batches'][0]['stale']==1
    s.action(b['id'],i['id'],'reopen',{'version':submitted['version'],'reason':'重新核对'},'dev',['develop'])
    i=s.detail(b['id'],'r1',['review'])['items'][0];i=s.action(b['id'],i['id'],'claim',{'version':i['version']},'r1',['review'])
    with pytest.raises(LibraryError):s.action(b['id'],i['id'],'revise',decision(i,row=new,reason='must conflict'),'r1',['review'])
    current=s.detail(b['id'],'r1',['review'])['items'][0]
    assert current['status']=='claimed' and len(current['history'])==1


@pytest.mark.parametrize('overrides',[
    {'conclusion':'needs_changes','comment':''},
    {'conclusion':'reject','comment':''},
    {'conclusion':'pass','tags':['其他'],'comment':''},
    {'scores':{'correctness':0,'support':5,'usability':5}},
    {'scores':{'correctness':True,'support':5,'usability':5}},
])
def test_decision_validation_preserves_claim(setup,overrides):
    lib,s,body,b=setup;i=s.detail(b['id'],'r1',['review'])['items'][0];i=s.action(b['id'],i['id'],'claim',{'version':1},'r1',['review'])
    payload=decision(i);payload.update(overrides)
    with pytest.raises(LibraryError):s.action(b['id'],i['id'],'submit',payload,'r1',['review'])
    assert s.detail(b['id'],'r1',['review'])['items'][0]['version']==i['version']
