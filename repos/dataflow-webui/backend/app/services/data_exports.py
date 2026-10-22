"""Fixed, verified export snapshots. No training, model or remote calls."""
import copy
import csv
import io
import json
from pathlib import Path
import uuid
import zipfile
from app.services.data_library import LibraryError,_hash,_json_bytes,_now
from app.services.data_reviews import DataReviews,revision
from app.services.dataset_persistence import atomic_write
from app.services.training_lifecycle import TrainingLifecycle


def csv_safe(value):
    value=str(value if value is not None else '')
    return "'"+value if value.lstrip().startswith(('=','+','-','@','\t','\r')) or value.startswith(('\t','\r')) else value


class DataExports:
    def __init__(self,library):
        self.lib=library;self.reviews=DataReviews(library);self.db=library.db
        self.root=library.root/'exports';self.root.mkdir(exist_ok=True)

    def selection(self,body,actor,roles):
        rec=self.reviews.snapshot(body.get('source'),body.get('kind','draft'))
        rows=rec['rows'];ids=rec['sample_ids'];references={}
        if body.get('batch'):
            passed=self.reviews.passed(body['batch'],actor,roles)
            current={sid:revision(row) for sid,row in zip(ids,rows)}
            conflicts=[i['sample_id'] for i in passed if current.get(i['sample_id'])!=i['revision']]
            if conflicts:raise LibraryError(f'存在 {len(conflicts)} 条通过修订与当前来源不符；请整理派生草稿或更换范围',409)
            selected={i['sample_id']:i for i in passed}
            pairs=[(sid,row) for sid,row in zip(ids,rows) if sid in selected]
            ids=[p[0] for p in pairs];rows=[p[1] for p in pairs]
            references={i['sample_id']:{'batch':body['batch'],'item':i['id'],'revision':i['revision']} for i in passed}
        if not rows:raise LibraryError('选择范围没有样本，未生成空训练包')
        return dict(rec,rows=copy.deepcopy(rows),sample_ids=list(ids),review_references=references)

    @staticmethod
    def convert(row,format,mapping):
        def field(target,default=None):
            key=mapping.get(target,target)
            if not key:return default
            return row.get(key,default)
        def nonempty(value):return isinstance(value,str) and bool(value.strip())
        def messages(value):
            return isinstance(value,list) and bool(value) and all(isinstance(m,dict) and m.get('role') in {'system','user','assistant','tool'} and (nonempty(m.get('content')) or isinstance(m.get('content'),list) and bool(m['content'])) for m in value)
        if format=='jsonl':return copy.deepcopy(row)
        if format=='alpaca':
            result={k:field(k,'' if k=='input' else None) for k in ('instruction','input','output')}
            if not nonempty(result['instruction']) or not nonempty(result['output']) or not isinstance(result['input'],str):raise LibraryError('Alpaca 需要非空 instruction/output 及字符串 input')
            for key in ('image','images'):
                if key in row:result[key]=copy.deepcopy(row[key])
            return result
        if format=='messages':
            value=field('messages')
            if not messages(value):raise LibraryError('对话格式需要已有且角色、顺序明确的 messages；请显式映射该字段')
            return {'messages':copy.deepcopy(value)}
        if format=='dpo':
            result={k:field(k) for k in ('prompt','chosen','rejected')}
            if not all(nonempty(v) or messages(v) for v in result.values()):raise LibraryError('DPO 需要已有 prompt/chosen/rejected，不能从单一回答生成 rejected')
            if result['chosen']==result['rejected']:raise LibraryError('chosen 与 rejected 不能相同')
            for key in ('image','images'):
                if key in row:result[key]=copy.deepcopy(row[key])
            return copy.deepcopy(result)
        raise LibraryError('导出格式无效')

    def preview(self,body,actor,roles):
        with self.lib._writing():rec=self.selection(body,actor,roles)
        format=body.get('data_format',body.get('format','jsonl'))
        if format=='package':format='jsonl'
        errors=[]
        for sid,row in zip(rec['sample_ids'],rec['rows']):
            try:self.convert(row,format,body.get('mapping',{}))
            except LibraryError as exc:errors.append({'sample_id':sid,'error':str(exc)})
        output_keys=set()
        if not errors:
            for row in rec['rows']:output_keys.update(self.convert(row,format,body.get('mapping',{})))
        return {'total':len(rec['rows']),'compatible':len(rec['rows'])-len(errors),'errors':errors,'output_fields':sorted(output_keys),'excluded_fields':sorted(set().union(*(set(r) for r in rec['rows']))-output_keys),'media_included':body.get('format')=='package'}

    def _review_rows(self,bid,actor,roles):
        batch=self.reviews.detail(bid,actor,roles)
        return [{'batch':bid,'item':i['id'],'sample_id':i['sample_id'],'revision':i['revision'],'original_revision':i['original_revision'],'status':i['status'],**(i['decision'] or {})} for i in batch['items']]

    def create(self,body,actor,roles,project='local'):
        if not set(roles)&{'manage','develop'}:raise LibraryError('需要开发权限',403)
        key=body.get('request_id')
        if not isinstance(key,str) or not 1<=len(key)<=200:raise LibraryError('需要幂等请求标识')
        fingerprint=_hash(_json_bytes(body))
        with self.lib._writing():
            with self.db.transaction() as c:
                previous=c.execute('SELECT payload FROM data_exports WHERE request_key=?',(actor+':'+key,)).fetchone()
                if previous:
                    rec=json.loads(previous[0])
                    if rec['request_hash']!=fingerprint:raise LibraryError('请求标识已用于不同导出',409)
                    return self.public(rec)
                format=body.get('format','jsonl')
                if format in {'review_csv','review_jsonl'}:
                    if not body.get('batch'):raise LibraryError('请选择评测批次')
                    review_rows=self._review_rows(body['batch'],actor,roles);snapshot=None
                    if not review_rows:raise LibraryError('评测批次为空')
                else:
                    snapshot=self.selection(body,actor,roles);review_rows=None
                eid='export_'+uuid.uuid4().hex
                rec={'id':eid,'project_id':project,'source':body.get('source'),'kind':body.get('kind','draft'),'batch':body.get('batch'),'format':format,'data_format':body.get('data_format','jsonl') if format=='package' else format,'mapping':body.get('mapping',{}),'created_by':actor,'created_at':_now(),'status':'preparing','request_hash':fingerprint,'row_count':len(review_rows if review_rows is not None else snapshot['rows']),'sample_revisions':{sid:revision(row) for sid,row in zip(snapshot['sample_ids'],snapshot['rows'])} if snapshot else {},'review_references':snapshot.get('review_references',{}) if snapshot else {},'media':[]}
                c.execute('INSERT INTO data_exports VALUES(?,?,?)',(eid,actor+':'+key,self.db.encode(rec)))
        try:
            content,suffix,media=self.build(rec,snapshot,review_rows,body)
            target=self.root/(eid+suffix);atomic_write(target,content)
            rec.update(status='ready',sha256=_hash(content),size_bytes=len(content),filename=target.name,media=media)
        except (LibraryError,OSError,ValueError,KeyError) as exc:
            rec.update(status='failed',error=str(exc) if isinstance(exc,LibraryError) else '导出文件生成失败，请检查内容和存储')
        with self.db.transaction() as c:c.execute('UPDATE data_exports SET payload=? WHERE id=?',(self.db.encode(rec),eid))
        return self.public(rec)

    def build(self,rec,snapshot,review_rows,body):
        format=rec['format']
        if format in {'review_csv','review_jsonl'}:
            if format=='review_jsonl':return b''.join(_json_bytes(r)+b'\n' for r in review_rows),'.jsonl',[]
            buffer=io.StringIO(newline='');keys=['batch','item','sample_id','revision','original_revision','status','conclusion','scores','tags','comment','reviewer','time','parent_revision','reason']
            writer=csv.DictWriter(buffer,fieldnames=keys);writer.writeheader()
            for row in review_rows:writer.writerow({k:csv_safe(json.dumps(row.get(k),ensure_ascii=False) if isinstance(row.get(k),(dict,list)) else row.get(k,'')) for k in keys})
            return buffer.getvalue().encode('utf-8-sig'),'.csv',[]
        rows=[]
        for sid,row in zip(snapshot['sample_ids'],snapshot['rows']):
            try:rows.append(self.convert(row,rec['data_format'],rec['mapping']))
            except LibraryError as exc:raise LibraryError(f'样本 {sid}: {exc}') from exc
        lifecycle=TrainingLifecycle(self.lib)
        media=lifecycle._validate(dict(snapshot,rows=rows))
        if media and format!='package':
            if body.get('media_policy')!='references_only':raise LibraryError('样本含媒体；请选择 ZIP，或明确确认仅导出相对媒体引用')
            if any(Path(ref).is_absolute() or '..' in Path(ref).parts for ref in media):raise LibraryError('仅 JSONL 不允许主机绝对媒体路径；请选择 ZIP')
        paths={ref:'media/'+meta['id']+path.suffix.lower() for ref,(path,meta) in media.items()}
        manifest_media=[{'path':paths[ref],'sha256':meta['sha256'],'material_id':meta['id']} for ref,(path,meta) in media.items()]
        if format=='package':rows=[lifecycle._portable(row,paths) for row in rows]
        data=b''.join(_json_bytes(row)+b'\n' for row in rows)
        if len([json.loads(line) for line in data.decode('utf-8').splitlines()])!=rec['row_count']:raise LibraryError('导出记录数验证失败')
        if format!='package':return data,'.jsonl',manifest_media
        manifest={k:v for k,v in rec.items() if k not in {'request_hash','mapping'}}
        manifest.update(status='ready',data_sha256=_hash(data),media=manifest_media)
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr('data.jsonl',data);bundle.writestr('manifest.json',_json_bytes(manifest))
            seen=set()
            for ref,(path,meta) in media.items():
                target=paths[ref]
                if target in seen:continue
                blob=path.read_bytes()
                if _hash(blob)!=meta['sha256']:raise LibraryError('媒体内容变化，导出失败',409)
                bundle.writestr(target,blob);seen.add(target)
        content=buffer.getvalue()
        with zipfile.ZipFile(io.BytesIO(content)) as verify:
            if verify.testzip():raise LibraryError('ZIP 完整性检查失败')
            if any(name.startswith('/') or '..' in Path(name).parts for name in verify.namelist()):raise LibraryError('ZIP 路径无效')
        return content,'.zip',manifest_media

    @staticmethod
    def public(rec):return {k:v for k,v in rec.items() if k!='request_hash'}

    def list(self):
        with self.db.reading() as c:return [self.public(json.loads(r[0])) for r in c.execute('SELECT payload FROM data_exports ORDER BY rowid DESC')]

    def download(self,eid):
        with self.db.reading() as c:row=c.execute('SELECT payload FROM data_exports WHERE id=?',(eid,)).fetchone()
        if not row:raise LibraryError('导出不存在',404)
        rec=json.loads(row[0])
        if rec['status']!='ready':raise LibraryError('导出尚不可下载',409)
        path=self.root/rec['filename']
        if not path.is_file() or _hash(path.read_bytes())!=rec['sha256']:raise LibraryError('导出文件已缺失或损坏',409)
        return path

    def expire(self,eid,actor,roles):
        if not set(roles)&{'manage','develop'}:raise LibraryError('需要开发权限',403)
        with self.db.transaction() as c:
            row=c.execute('SELECT payload FROM data_exports WHERE id=?',(eid,)).fetchone()
            if not row:raise LibraryError('导出不存在',404)
            rec=json.loads(row[0])
            if rec['status']=='preparing':raise LibraryError('导出仍在准备中',409)
            rec.update(status='expired',expired_by=actor,expired_at=_now())
            c.execute('UPDATE data_exports SET payload=? WHERE id=?',(self.db.encode(rec),eid))
        if rec.get('filename'):(self.root/rec['filename']).unlink(missing_ok=True)
        return self.public(rec)

    def recover_interrupted(self):
        """Called once on worker startup, never by request constructors."""
        with self.db.transaction() as c:
            for eid,payload in c.execute('SELECT id,payload FROM data_exports').fetchall():
                rec=json.loads(payload)
                if rec['status']=='preparing':
                    rec.update(status='failed',error='服务重启中断了导出，请重新创建快照')
                    c.execute('UPDATE data_exports SET payload=? WHERE id=?',(self.db.encode(rec),eid))
