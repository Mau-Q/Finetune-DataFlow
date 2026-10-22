import time
from concurrent.futures import ThreadPoolExecutor
import pytest
from app.services.team_store import TeamStore
from app.services.data_library import LibraryError

PASS='isolated-test-password-123'


def test_sessions_invitations_and_membership(tmp_path):
    s=TeamStore(tmp_path/'state');uid=s.initialize('owner',PASS,tmp_path/'legacy')
    token,csrf=s.login('owner',PASS,'test');actor=s.identity(token)
    invite=s.invite(actor,'reader');s.accept(invite['invitation'],PASS)
    with pytest.raises(LibraryError):s.accept(invite['invitation'],PASS)
    reader,_=s.login('reader',PASS,'test');rid=s.identity(reader)['id']
    assert s.projects(rid)==[]
    with pytest.raises(LibraryError):s.access(rid,'default')
    s.member(actor,'default',rid,['review'],0)
    assert s.access(rid,'default')['roles']==['review']
    with pytest.raises(LibraryError):s.member(actor,'default',rid,['develop'],0)
    s.disable(actor,rid,False)
    with pytest.raises(LibraryError):s.identity(reader)
    with pytest.raises(LibraryError):s.disable(actor,uid,False)
    expired=s.invite(actor,'expired')
    with s.tx() as c:c.execute('UPDATE invitations SET expires=0 WHERE user=?',(expired['user_id'],))
    with pytest.raises(LibraryError):s.accept(expired['invitation'],PASS)
    s.invite(actor,None,reset=uid)
    with pytest.raises(LibraryError):s.identity(token)
    assert TeamStore(s.root).projects(uid)[0]['id']=='default'


def test_concurrent_membership_conflict(tmp_path):
    s=TeamStore(tmp_path);uid=s.initialize('owner',PASS,tmp_path/'legacy');token,_=s.login('owner',PASS,'test');a=s.identity(token)
    def save(roles):
        try:s.member(a,'default',uid,roles,1);return 200
        except LibraryError as e:return e.status
    with ThreadPoolExecutor(2) as pool:assert sorted(pool.map(save,[['manage','review'],['manage','develop']]))==[200,409]


def test_pending_admin_is_not_counted_and_revoked_project_disappears(tmp_path):
    s=TeamStore(tmp_path);uid=s.initialize('owner',PASS,tmp_path/'legacy');token,_=s.login('owner',PASS,'test');a=s.identity(token)
    s.invite(a,'not-yet-usable-admin',admin=True)
    with pytest.raises(LibraryError):s.disable(a,uid,False)
    invite=s.invite(a,'reviewer');s.accept(invite['invitation'],PASS);s.member(a,'default',invite['user_id'],['review'],0)
    s.member(a,'default',invite['user_id'],[],1)
    assert s.projects(invite['user_id'])==[]
    with pytest.raises(LibraryError):s.access(invite['user_id'],'default')
    s.invite(a,None,reset=invite['user_id'])
    with pytest.raises(LibraryError):s.login('reviewer',PASS,'test')


def test_legacy_initialization_is_reentrant_safe_and_preserves_identity(tmp_path):
    import json,hashlib
    from app.services.data_library import DataLibrary
    from app.schemas.data_library import DraftCreate
    legacy=tmp_path/'legacy';lib=DataLibrary(legacy/'data/library');d=lib.create_draft(DraftCreate(name='历史草稿',modality='text',training_type='sft'))
    prefs=legacy/'data/user_preferences.json';prefs.write_text(json.dumps({'language':'cn','theme':'light'}))
    before={p.relative_to(legacy):hashlib.sha256(p.read_bytes()).hexdigest() for p in legacy.rglob('*') if p.is_file()}
    s=TeamStore(tmp_path/'state');uid=s.initialize('owner',PASS,legacy)
    with pytest.raises(LibraryError):s.initialize('another',PASS,legacy)
    assert {p.relative_to(legacy):hashlib.sha256(p.read_bytes()).hexdigest() for p in legacy.rglob('*') if p.is_file()}==before
    assert lib._get('drafts',d['id'])['name']=='历史草稿'
    with s.tx() as c:assert json.loads(c.execute('SELECT preferences FROM users WHERE id=?',(uid,)).fetchone()[0])=={'language':'cn','theme':'light'}
    assert TeamStore(s.root).projects(uid)[0]['id']=='default'
