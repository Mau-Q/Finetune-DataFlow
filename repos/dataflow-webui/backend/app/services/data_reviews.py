"""Single-reviewer batches over immutable sample revisions, in the dataset transaction."""
import copy
import json
import random
import uuid
from app.services.data_library import LibraryError, _json_bytes, _hash, _now
from app.services.training_lifecycle import TrainingLifecycle

DEFAULT_TEMPLATE={'dimensions':[{'id':k,'name':n,'required':True} for k,n in [('correctness','正确性'),('support','来源支持'),('usability','表达与可用性')]],'tags':['事实错误','缺少依据','答非所问','格式错误','重复','图片不匹配','其他']}


def revision(row):return _hash(_json_bytes(row))


class DataReviews:
    def __init__(self,library,tasks=None):
        self.lib=library;self.db=library.db;self.tasks=tasks
        with self.db.reading() as c:
            if c.execute("SELECT 1 FROM sqlite_master WHERE name='review_context'").fetchone():return
        with self.db.transaction() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS sample_revisions(sample_id TEXT, revision TEXT, payload TEXT NOT NULL,
              parent TEXT, reason TEXT, actor TEXT, created TEXT, PRIMARY KEY(sample_id,revision));
            CREATE TABLE IF NOT EXISTS review_batches(id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS review_items(id TEXT PRIMARY KEY, batch TEXT NOT NULL REFERENCES review_batches(id),
              sample_id TEXT NOT NULL, revision TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE(batch,sample_id,revision));
            CREATE INDEX IF NOT EXISTS review_batch_items ON review_items(batch);
            CREATE TABLE IF NOT EXISTS review_context(id TEXT PRIMARY KEY, batch TEXT NOT NULL, item TEXT NOT NULL, path TEXT NOT NULL, sha256 TEXT NOT NULL, name TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS data_exports(id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, payload TEXT NOT NULL);
            ''')

    def remember(self,c,sid,row,parent=None,reason=None,actor=None):
        rev=revision(row)
        c.execute('INSERT OR IGNORE INTO sample_revisions VALUES(?,?,?,?,?,?,?)',(sid,rev,self.db.encode(row),parent,reason,actor,_now()))
        return rev

    def snapshot(self,source,kind='draft'):
        if kind=='draft':
            rec=self.lib._get('drafts',source);TrainingLifecycle(self.lib)._members(rec)
            return copy.deepcopy(rec)
        if kind!='release':raise LibraryError('来源类型无效')
        lifecycle=TrainingLifecycle(self.lib);path=lifecycle.download(source,'jsonl');meta=self.db.get('releases',source)
        rows=meta.get('snapshot_rows') or [json.loads(s) for s in path.read_text('utf-8').splitlines() if s.strip()]
        bindings=meta.get('snapshot_media_bindings') or {v['path']:v['material_id'] for v in meta.get('media',{}).values()}
        return dict(meta,rows=rows,media_bindings=bindings)

    def create(self,body,actor):
        key=body.get('request_id')
        if not isinstance(key,str) or not 1<=len(key)<=200:raise LibraryError('需要幂等请求标识')
        with self.lib._writing():
            with self.db.transaction() as c:
                existing=c.execute('SELECT id,payload FROM review_batches WHERE request_key=?',(actor+':'+key,)).fetchone()
                if existing:return json.loads(existing[1])
                kind=body.get('kind','draft');rec=self.snapshot(body.get('source'),kind)
                rows=rec['rows'];ids=rec['sample_ids']
                if not rows:raise LibraryError('空数据集不能发起评测')
                count=body.get('count',len(rows));seed=body.get('seed',0)
                if type(count) is not int or not 1<=count<=len(rows):raise LibraryError('抽样数量超出可选范围')
                if not isinstance(seed,(str,int)):raise LibraryError('抽样种子无效')
                reviewers=body.get('reviewers',[])
                if not reviewers or not isinstance(reviewers,list) or any(not isinstance(x,str) for x in reviewers):raise LibraryError('请选择允许评测人员')
                template=copy.deepcopy(body.get('template') or DEFAULT_TEMPLATE)
                dims=template.get('dimensions',[])
                if not dims or any(not isinstance(d.get('id'),str) or not isinstance(d.get('name'),str) for d in dims) or len({d['id'] for d in dims})!=len(dims):raise LibraryError('评分模板无效')
                if not isinstance(template.get('tags'),list):raise LibraryError('问题标签模板无效')
                positions=list(range(len(rows))) if count==len(rows) else sorted(random.Random(seed).sample(range(len(rows)),count))
                bid='review_'+uuid.uuid4().hex
                batch={'id':bid,'source':rec['id'],'draft_id':rec.get('draft_id',rec['id']),'kind':kind,'name':body.get('name') or rec['name']+' · 人工评测','total_available':len(rows),'count':count,'seed':seed,'sampled':count<len(rows),'template':template,'reviewers':list(dict.fromkeys(reviewers)),'created_by':actor,'created_at':_now(),'status':'in_progress','version':1,'media_bindings':rec.get('media_bindings',{}),'modality':rec['modality'],'training_type':rec.get('training_type','sft')}
                c.execute('INSERT INTO review_batches VALUES(?,?,?)',(bid,actor+':'+key,self.db.encode(batch)))
                for position in positions:
                    sid=ids[position];rev=self.remember(c,sid,rows[position]);item={'id':'item_'+uuid.uuid4().hex,'batch':bid,'sample_id':sid,'revision':rev,'original_revision':rev,'row':rows[position],'original_row':rows[position],'sources':rec.get('sample_sources',{}).get(sid,[]),'source_missing':not rec.get('sample_sources',{}).get(sid),'status':'pending','owner':None,'version':1,'saved':{},'decision':None,'history':[],'skipped':False}
                    item['context']=[]
                    context_seen=set()
                    for source in item['sources']:
                        task=self.tasks.get(source.get('task_id')) if self.tasks else None
                        frozen=(task or {}).get('pipeline_config',{}).get('execution_options',{}).get('input_snapshot',{})
                        entries=frozen.get('materials') or ([frozen] if frozen.get('path') else [])
                        for entry in entries:
                            path=entry.get('path');sha=entry.get('sha256')
                            if not path or not sha or (path,sha) in context_seen:continue
                            context_seen.add((path,sha));cid='context_'+uuid.uuid4().hex
                            from pathlib import Path
                            name=entry.get('source_name') or Path(path).name
                            c.execute('INSERT INTO review_context VALUES(?,?,?,?,?,?)',(cid,bid,item['id'],path,sha,name))
                            item['context'].append({'id':cid,'name':name,'sha256':sha})
                    item['source_missing'] = not item['context'] and not bool(batch['media_bindings'])
                    c.execute('INSERT INTO review_items VALUES(?,?,?,?,?)',(item['id'],bid,sid,rev,self.db.encode(item)))
                return batch

    def _batch(self,c,bid,actor,roles):
        row=c.execute('SELECT payload FROM review_batches WHERE id=?',(bid,)).fetchone()
        if not row:raise LibraryError('评测批次不存在',404)
        batch=json.loads(row[0])
        if not set(roles)&{'manage','develop'} and actor not in batch['reviewers']:raise LibraryError('评测批次不存在',404)
        return batch

    def list(self,actor,roles):
        with self.db.reading() as c:
            batches=[json.loads(r[0]) for r in c.execute('SELECT payload FROM review_batches ORDER BY rowid DESC')]
            return [self.detail(b['id'],actor,roles,False) for b in batches if set(roles)&{'manage','develop'} or actor in b['reviewers']]

    def detail(self,bid,actor,roles,include=True):
        with self.db.reading() as c:
            b=self._batch(c,bid,actor,roles)
            items=[json.loads(r[0]) for r in c.execute('SELECT payload FROM review_items WHERE batch=? ORDER BY rowid',(bid,))]
            submitted=[i for i in items if i['status']=='submitted']
            summary={'total':len(items),'submitted':len(submitted),'pending':len(items)-len(submitted),'pass':sum(i['decision']['conclusion']=='pass' for i in submitted),'needs_changes':sum(i['decision']['conclusion']=='needs_changes' for i in submitted),'reject':sum(i['decision']['conclusion']=='reject' for i in submitted),'skipped':sum(i['skipped'] for i in items),'unjudgeable':sum(any(isinstance(v,dict) for v in i['decision']['scores'].values()) for i in submitted)}
            summary['completion_rate']=len(submitted)/len(items) if items else None
            summary['pass_rate']=summary['pass']/len(submitted) if submitted else None
            summary['dimensions']={d['id']:{str(n):sum(i['decision']['scores'].get(d['id'])==n for i in submitted) for n in range(1,6)} for d in b['template']['dimensions']}
            summary['tags']={tag:sum(tag in i['decision'].get('tags',[]) for i in submitted) for tag in b['template']['tags']}
            result=dict(b,summary=summary)
            if include:result['items']=items
            return result

    def _validate_decision(self,batch,body):
        scores=body.get('scores',{});conclusion=body.get('conclusion');comment=body.get('comment','');tags=body.get('tags',[])
        if conclusion not in {'pass','needs_changes','reject'}:raise LibraryError('请选择明确的最终结论')
        if not isinstance(comment,str) or not isinstance(tags,list) or set(tags)-set(batch['template']['tags']):raise LibraryError('评语或标签无效')
        if (conclusion!='pass' or '其他' in tags) and not comment.strip():raise LibraryError('此结论或标签需要评语')
        if set(scores)-{d['id'] for d in batch['template']['dimensions']}:raise LibraryError('评分维度不属于模板')
        for dim in batch['template']['dimensions']:
            value=scores.get(dim['id'])
            if value is None and not dim.get('required',True):continue
            if type(value) is int and 1<=value<=5:continue
            if isinstance(value,dict) and isinstance(value.get('unknown'),str) and value['unknown'].strip():
                if conclusion=='pass':raise LibraryError('必评维度无法判断时不能直接通过')
                continue
            raise LibraryError('所有必评维度需要 1–5 整数或无法判断原因')
        return {'scores':scores,'conclusion':conclusion,'comment':comment,'tags':tags}

    def action(self,bid,iid,operation,body,actor,roles):
        with self.lib._writing():
            with self.db.transaction() as c:
                b=self._batch(c,bid,actor,roles)
                result=c.execute('SELECT payload FROM review_items WHERE id=? AND batch=?',(iid,bid)).fetchone()
                if not result:raise LibraryError('评测项不存在',404)
                item=json.loads(result[0]);key=body.get('request_id')
                if operation in {'submit','revise'} and item.get('decision') and key and item['decision'].get('request_id')==key and item['decision']['reviewer']==actor:return item
                if body.get('version')!=item['version']:raise LibraryError('评测项已更新，请刷新',409)
                manager=bool(set(roles)&{'manage','develop'})
                if operation=='reopen':
                    if not manager or not body.get('reason','').strip():raise LibraryError('重开需要开发权限和原因',403)
                    if item['decision']:item['history'].append(item['decision'])
                    item.update(status='pending',owner=None,decision=None,saved={},revision=item['original_revision'],row=item['original_row'])
                    b['status']='in_progress'
                else:
                    if b['status'] in {'closed','completed'}:raise LibraryError('批次已关闭或完成',409)
                    if operation=='release' and manager:
                        if not body.get('reason','').strip():raise LibraryError('重新分配需要原因')
                        item['history'].append({'released_by':actor,'reason':body['reason'],'saved':item.get('saved',{}),'time':_now()})
                        item.update(status='pending',owner=None)
                    else:
                        if 'review' not in roles or actor not in b['reviewers']:raise LibraryError('未获此批次评测权限',403)
                        if operation=='claim':
                            if item['status']!='pending':raise LibraryError('评测项已被领取',409)
                            item.update(status='claimed',owner=actor,skipped=False)
                        else:
                            if item['status']!='claimed' or item['owner']!=actor:raise LibraryError('领取归属已失效',409)
                            if operation=='release':item.update(status='pending',owner=None)
                            elif operation=='save':item.update(saved=body.get('draft',{}),skipped=bool(body.get('skipped')))
                            elif operation in {'submit','revise'}:
                                if not key:raise LibraryError('需要提交请求标识')
                                decision=self._validate_decision(b,body)
                                if operation=='revise':
                                    if decision['conclusion']!='pass' or not body.get('reason','').strip():raise LibraryError('修改并通过需要通过结论和修改原因')
                                    row=body.get('row')
                                    TrainingLifecycle(self.lib)._validate(dict(b,rows=[row]))
                                    if b['kind']=='draft':
                                        current=self.lib._get('drafts',b['source']);ids=current['sample_ids']
                                        if item['sample_id'] not in ids or revision(current['rows'][ids.index(item['sample_id'])])!=item['revision']:raise LibraryError('当前草稿修订已变化，整笔修改已取消',409)
                                        self.remember(c,item['sample_id'],row,item['revision'],body['reason'],actor)
                                        TrainingLifecycle(self.lib).edit(b['source'],item['sample_id'],row,expected_updated_at=current['updated_at'])
                                    new=self.remember(c,item['sample_id'],row,item['revision'],body['reason'],actor)
                                    decision.update(parent_revision=item['revision'],reason=body['reason'])
                                    item.update(row=row,revision=new)
                                decision.update(revision=item['revision'],reviewer=actor,time=_now(),request_id=key)
                                item.update(status='submitted',decision=decision,saved={},skipped=False)
                            else:raise LibraryError('操作无效')
                item['version']+=1
                c.execute('UPDATE review_items SET payload=? WHERE id=?',(self.db.encode(item),iid))
                c.execute('UPDATE review_batches SET payload=? WHERE id=?',(self.db.encode(b),bid))
                if all(json.loads(r[0])['status']=='submitted' for r in c.execute('SELECT payload FROM review_items WHERE batch=?',(bid,))):
                    b['status']='completed';c.execute('UPDATE review_batches SET payload=? WHERE id=?',(self.db.encode(b),bid))
                return item

    def close(self,bid,actor,roles,version):
        if not set(roles)&{'manage','develop'}:raise LibraryError('需要开发权限',403)
        with self.db.transaction() as c:
            b=self._batch(c,bid,actor,roles)
            if b['version']!=version:raise LibraryError('批次已更新',409)
            b.update(status='closed',version=b['version']+1,closed_by=actor,closed_at=_now())
            c.execute('UPDATE review_batches SET payload=? WHERE id=?',(self.db.encode(b),bid));return b

    def passed(self,bid,actor,roles):
        return [i for i in self.detail(bid,actor,roles)['items'] if i['decision'] and i['decision']['conclusion']=='pass']

    def derive(self,bid,actor,roles):
        from app.schemas.data_library import DraftCreate
        if not set(roles)&{'manage','develop'}:raise LibraryError('需要开发权限',403)
        with self.lib._writing():
            b=self.detail(bid,actor,roles);items=self.passed(bid,actor,roles)
            if not items:raise LibraryError('没有通过的样本')
            rec=self.lib.create_draft(DraftCreate(name=b['name']+' · 通过样本',modality=b['modality'],training_type=b['training_type']))
            rec=self.lib._get('drafts',rec['id'])
            rec.update(rows=[i['row'] for i in items],sample_ids=[i['sample_id'] for i in items],sample_sources={i['sample_id']:i['sources'] for i in items},media_bindings=b['media_bindings'],review_references={i['sample_id']:{'batch':bid,'revision':i['revision'],'item':i['id']} for i in items})
            self.db.put('drafts',rec);return rec

    def current_status(self,draft_id,actor,roles):
        if not set(roles)&{'manage','develop'}:raise LibraryError('需要开发权限',403)
        draft=self.lib._get('drafts',draft_id)
        current={sid:revision(row) for sid,row in zip(draft['sample_ids'],draft['rows'])}
        result=[]
        referenced={r.get('batch') for r in draft.get('review_references',{}).values()}
        for batch in self.list(actor,roles):
            if batch['draft_id']!=draft_id and batch['id'] not in referenced:continue
            items=self.detail(batch['id'],actor,roles)['items']
            applicable=[i for i in items if i['decision'] and current.get(i['sample_id'])==i['revision']]
            result.append({'id':batch['id'],'name':batch['name'],'sampled':batch['sampled'],'batch_count':batch['count'],'current_total':len(current),'applicable':len(applicable),'passed':sum(i['decision']['conclusion']=='pass' for i in applicable),'stale':sum(i['decision'] is not None and current.get(i['sample_id'])!=i['revision'] for i in items)})
        return {'draft_id':draft_id,'current_total':len(current),'batches':result}
