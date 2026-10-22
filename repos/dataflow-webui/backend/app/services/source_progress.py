"""Evidence-based source/task/result aggregation; never infer coverage from output rows."""
import copy
import json
from pathlib import Path
from app.services.data_library import _hash, _json_bytes, LibraryError


def dataset_id(config):
    value=config.get('input_dataset')
    return value.get('id') if isinstance(value,dict) else value


def content_identity(record):
    path=Path(record['root'])
    if not path.is_file():return None
    content=path.read_bytes()
    members=[]
    if path.suffix.lower()=='.jsonl':
        try:
            rows=[json.loads(s) for s in content.decode('utf-8-sig').splitlines() if s.strip()]
            if rows and all(isinstance(r,dict) and isinstance(r.get('source'),str) and not set(r)-{'source','source_name','material_id'} for r in rows):
                for i,row in enumerate(rows):
                    p=Path(row['source']);members.append({'position':i,'sha256':_hash(p.read_bytes()) if p.is_file() else None,'material_id':row.get('material_id')})
        except (ValueError,UnicodeError,OSError):pass
    value={'dataset_id':record['id'],'file_sha256':_hash(content),'members':members}
    return dict(value,identity=_hash(_json_bytes({'members':members} if members else {'file_sha256':value['file_sha256']})))


def freeze_source(config,registry,library):
    """Capture identity and actual input bytes before execution; reuse existing frozen inputs."""
    if registry is None or library is None:return None
    prior=config.get('execution_options',{}).get('source_identity')
    if prior and prior.get('dataset_id')==dataset_id(config) and config.get('execution_options',{}).get('input_snapshot'):return copy.deepcopy(prior)
    rid=dataset_id(config)
    record=registry.get(rid) if rid else None
    if not record:return None
    record=dict(record,id=rid)
    snapshot=content_identity(record)
    if snapshot is None:raise LibraryError('输入文件不可用',409)
    options=config.setdefault('execution_options',{})
    if not options.get('input_snapshot'):
        original=Path(record['root']);content=original.read_bytes()
        if _hash(content)!=snapshot['file_sha256']:raise LibraryError('固定输入期间内容变化',409)
        root=library.root/'task_inputs'/snapshot['identity'];root.mkdir(parents=True,exist_ok=True)
        materials=[]
        if snapshot['members']:
            rows=[json.loads(s) for s in content.decode('utf-8-sig').splitlines() if s.strip()]
            for i,row in enumerate(rows):
                source=Path(row['source'])
                if not source.is_file():raise LibraryError('输入成员缺失',409)
                blob=source.read_bytes()
                if _hash(blob)!=snapshot['members'][i]['sha256']:raise LibraryError('固定输入期间内容变化',409)
                target=root/(str(i)+source.suffix.lower());library._atomic(target,blob)
                row['source']=str(target)
                materials.append({'path':str(target),'sha256':_hash(blob),'material_id':row.get('material_id')})
            content=b''.join(_json_bytes(row)+b'\n' for row in rows)
        target=root/('input'+original.suffix.lower());library._atomic(target,content)
        options['input_snapshot']={'dataset_id':rid,'path':str(target),'sha256':_hash(content),'materials':materials,'material_count':len(materials) or None}
    options["source_identity"]=copy.deepcopy(snapshot)
    return snapshot


class SourceProgress:
    def __init__(self,registry,library,tasks):self.registry,self.lib,self.tasks=registry,library,tasks

    def page(self,offset=0,limit=50,filters=None,source=None):
        sources=self.registry.list()
        if source:sources=[s for s in sources if s['id']==source]
        tasks=self.tasks.list_executions();drafts=self.lib.db.list('drafts');releases=self.lib.db.list('releases')
        result=[self.aggregate(source,tasks,drafts,releases) for source in sources]
        for key,value in (filters or {}).items():
            if value is not None:result=[r for r in result if bool(r[key])==value]
        return {'total':len(result),'offset':offset,'limit':limit,'items':result[offset:offset+limit]}

    def aggregate(self,source,tasks,drafts,releases):
        current=content_identity(source)
        linked=[t for t in tasks if dataset_id(t.get('pipeline_source_config') or t.get('pipeline_config',{}))==source['id'] or (t.get('input_identity') or {}).get('dataset_id')==source['id']]
        task_ids={t['task_id'] for t in linked}
        linked_drafts=[]
        for draft in drafts:
            count=sum(any(s.get('task_id') in task_ids for s in refs) for sid,refs in draft.get('sample_sources',{}).items() if sid in draft.get('sample_ids',[]))
            if count:linked_drafts.append({'id':draft['id'],'name':draft['name'],'source_sample_count':count,'total_sample_count':len(draft['rows']),'archived':bool(draft.get('archived'))})
        linked_releases=[]
        for release in releases:
            count=sum(any(s.get('task_id') in task_ids for s in refs) for sid,refs in release.get('sample_sources',{}).items() if sid in release.get('sample_ids',[]))
            if count:linked_releases.append({'id':release['id'],'source_sample_count':count,'total_sample_count':release['row_count']})
        active=[t['task_id'] for t in linked if t.get('status') in {'queued','pending','running'}]
        collected={key for d in drafts for key in d.get('collections',[])}
        pending=[];zero=[];old=[];unknown=[];details=[]
        for task in linked:
            tid=task['task_id'];artifacts=task.get('output',{}).get('artifacts',[])
            training=[a for a in artifacts if a.get('kind')=='training']
            if any(tid+':'+a['id'] not in collected and a.get('row_count',a.get('rows',1))!=0 for a in training):pending.append(tid)
            if task.get('status')=='completed' and training and all(a.get('row_count',a.get('rows'))==0 for a in training):zero.append(tid)
            identity=task.get('input_identity')
            if not identity:unknown.append(tid)
            elif current and identity.get('identity')!=current['identity']:old.append(tid)
            details.append({'task_id':tid,'status':task.get('status'),'pipeline_id':task.get('pipeline_id'),'input_identity':identity,'created_at':task.get('created_at'),'artifacts':[{k:v for k,v in a.items() if k!='path'} for a in artifacts],'coverage':task.get('input_coverage') if task.get('input_coverage',{}).get('evidence')=='executor_members' else None})
        return {'id':source['id'],'name':source['name'],'input_identity':current,'datasets':linked_drafts,'releases':linked_releases,'active':active,'pending':pending,'zero_samples':zero,'old_content':old,'unknown_source':unknown,'tasks':details,'generated':bool(linked_drafts),'published':bool(linked_releases),'coverage':None,'partial_success':[t['task_id'] for t in linked if t.get('output',{}).get('sample_summary',{}).get('valid',0)>0 and t.get('output',{}).get('sample_summary',{}).get('invalid',0)>0],'recent_failures':[t['task_id'] for t in linked if t.get('status') in {'failed','cancelled'}]}
