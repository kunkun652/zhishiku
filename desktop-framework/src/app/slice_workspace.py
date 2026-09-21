"""Readable source slices with conservative source ordering."""
import json,sqlite3
import hashlib
from contextlib import closing
from fastapi import HTTPException
from . import content_quality as quality

def install(app,connect,root,now):
    def ordered_page(c,file_id,page):
        rows=[dict(x) for x in c.execute('SELECT id,text FROM chunks WHERE file_id=? AND page=?',(file_id,page))]
        if not rows:return [],False
        f=c.execute('SELECT path,sha256 FROM files WHERE id=?',(file_id,)).fetchone()
        if f:
            path=(root/f['path']).resolve()
            if path.is_relative_to(root/'assets') and path.suffix.lower()=='.pdf' and path.is_file():
                try:
                    if hashlib.sha256(path.read_bytes()).hexdigest()!=f['sha256']:return None,False
                    import fitz
                    with fitz.open(path) as doc:
                        text=doc[page-1].get_text(sort=True).strip().replace('\x00','') if 0<page<=len(doc) else ''
                    for row in rows:
                        start=text.find(row['text'])
                        if start<0 or text.find(row['text'],start+1)>=0:return None,False
                        row['source_start']=start
                    return sorted(rows,key=lambda r:r['source_start']),True
                except (ImportError,ValueError,RuntimeError,OSError):pass
        # A single registered slice needs no inferred within-page ordering.
        return (rows,False) if len(rows)==1 else (None,False)
    def units(cid=None,key='',offset=0):
        from index_generations import index_path
        path=index_path(root)
        if not path.exists():return {'items':[],'total':0,'encoding':None}
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=20)) as c:
            c.row_factory=sqlite3.Row
            where=' WHERE u.parent=?' if cid is not None else ' WHERE u.key=?' if key else ''
            args=[f'c:{cid}'] if cid is not None else [key] if key else []
            count=c.execute('SELECT COUNT(*) FROM units u'+where,args).fetchone()[0]
            rows=[dict(r) for r in c.execute('SELECT u.*,v.key IS NOT NULL encoded FROM units u LEFT JOIN vectors v ON v.key=u.key'+where+' ORDER BY u.start LIMIT 30 OFFSET ?',args+[offset])]
            enc=c.execute("SELECT value FROM meta WHERE key='encoding'").fetchone()
        return {'items':rows,'total':count,'encoding':json.loads(enc[0]) if enc else None}

    @app.get('/api/slice-options')
    def options(q:str='',offset:int=0):
        with connect() as c:
            rows=[dict(r) for r in c.execute('SELECT id,name FROM files WHERE name LIKE ? ORDER BY name LIMIT 100 OFFSET ?',('%'+q+'%',max(0,offset)))]
            count=c.execute('SELECT COUNT(*) FROM files WHERE name LIKE ?',('%'+q+'%',)).fetchone()[0]
            cats=[r[0] for r in c.execute('SELECT DISTINCT category FROM sources ORDER BY category')]
        return {'files':rows,'total':count,'categories':cats}

    @app.get('/api/source-slices')
    def listing(q:str='',category:str='',file_id:str='',object_id:str='',content:str='body',encoding:str='',offset:int=0,limit:int=30):
        with connect() as c:
            c.create_function('quality_state',2,lambda text,status:status or quality.classify(text)[0])
            import hashlib
            c.create_function('text_sha',1,lambda text:hashlib.sha256(text.encode()).hexdigest())
            from index_generations import index_path
            path=index_path(root)
            has_units=path.exists()
            if has_units:c.execute('ATTACH DATABASE ? AS unit_index',(path.as_uri()+'?mode=ro',))
            enc="CASE WHEN ux.current=1 AND ux.complete=1 AND ux.first=0 AND ux.last>=length(c.text) THEN 'encoded' WHEN ux.current=0 THEN 'stale' ELSE 'pending' END" if has_units else "'pending'"
            where=[];args=[]
            for field,value in [('c.file_id',file_id),('c.object_id',object_id),("json_extract(o.payload,'$.category')",category)]:
                if value:where.append(field+'=?');args.append(value)
            if q:
                where.append("(c.text LIKE ? OR f.name LIKE ? OR o.title LIKE ? OR json_extract(o.payload,'$.tags') LIKE ?)");args.extend(['%'+q+'%']*4)
            state='quality_state(c.text,CASE WHEN z.text_hash=text_sha(c.text) THEN z.status END)'
            if content=='body':where.append("(z.status IS NULL OR z.status!='noise' OR z.text_hash!=text_sha(c.text)) AND length(trim(c.text))>0")
            elif content in ('suspect','noise'):where.append(state+'=?');args.append(content)
            if encoding:where.append(enc+'=?');args.append(encoding)
            base=' FROM chunks c LEFT JOIN files f ON f.id=c.file_id LEFT JOIN objects o ON o.id=c.object_id LEFT JOIN chunk_quality z ON z.chunk_id=c.id'
            if has_units:base+=" LEFT JOIN (SELECT u.parent,MAX(u.parent_hash=text_sha(pc.text)) current,MIN(CASE WHEN u.parent_hash=text_sha(pc.text) THEN u.start END) first,MAX(CASE WHEN u.parent_hash=text_sha(pc.text) THEN u.end END) last,MIN(CASE WHEN u.parent_hash=text_sha(pc.text) THEN v.key IS NOT NULL ELSE 1 END) complete FROM unit_index.units u JOIN main.chunks pc ON u.parent='c:'||pc.id LEFT JOIN unit_index.vectors v ON v.key=u.key GROUP BY u.parent) ux ON ux.parent='c:'||c.id"
            clause=' WHERE '+' AND '.join(where) if where else ''
            total=c.execute('SELECT COUNT(*)'+base+clause,args).fetchone()[0]
            raw=c.execute("SELECT c.*,f.name filename,o.title,json_extract(o.payload,'$.category') category,o.status review_status,"+enc+' encoding_status'+base+clause+' ORDER BY c.file_id,c.page,c.id LIMIT ? OFFSET ?',args+[max(1,min(limit,100)),max(0,offset)]).fetchall()
            rows=[]
            for row in raw:
                r=dict(row);r['quality']=quality.get(c,r['id'],r['text']);r['characters']=len(r['text']);pos=r['text'].casefold().find(q.casefold()) if q else 0
                r['preview']=r.pop('text')[max(0,pos-100):max(0,pos-100)+650];rows.append(r)
            parents=c.execute('SELECT COUNT(*) FROM chunks').fetchone()[0]
            encoded=c.execute('SELECT COUNT(*) FROM unit_index.units').fetchone()[0] if has_units else 0
        return {'items':rows,'total':total,'offset':offset,'source_count':parents,'unit_count':encoded,'order_note':'按文件及登记页码排列；同页片内顺序未登记，ID 仅作稳定展示排序'}

    @app.get('/api/source-slices/{cid}')
    def detail(cid:int):
        with connect() as c:
            row=c.execute('SELECT * FROM chunks WHERE id=?',(cid,)).fetchone()
            if not row:raise HTTPException(404,'片段不存在')
            r=dict(row);r['quality']=quality.get(c,cid,r['text'])
            f=c.execute('SELECT * FROM files WHERE id=?',(r['file_id'],)).fetchone();r['file']=dict(f) if f else None
            s=c.execute('SELECT paths,category FROM sources WHERE file_id=?',(r['file_id'],)).fetchone();r['source']=dict(s) if s else None
            o=c.execute('SELECT title,payload,status FROM objects WHERE id=?',(r['object_id'],)).fetchone();r['object']={'title':o['title'],'data':json.loads(o['payload']),'status':o['status']} if o else None
            r.update(previous=None,next=None,order_note='按同文件已登记页码定位；页码未经原件人工复核')
            ordered,verified=ordered_page(c,r['file_id'],r['page'])
            r['source_start']=None;r['page_sequence']=None
            if not r['file_id'] or not r['page'] or ordered is None:r['order_note']='缺少可靠的页内片段顺序；不使用数据库 ID 推断邻片，已禁用相邻切换'
            else:
                index=next(i for i,x in enumerate(ordered) if x['id']==cid)
                r['page_sequence']=index+1;r['source_start']=ordered[index].get('source_start')
                if verified:r['order_note']='已核对原文件 SHA-256；按原 PDF 页码及页内文本精确匹配偏移排列'
                if index>0:r['previous']=ordered[index-1]['id']
                if index+1<len(ordered):r['next']=ordered[index+1]['id']
                for field,op,order in [('previous','<','DESC'),('next','>','ASC')]:
                    if r[field] is not None:continue
                    other=c.execute(f'SELECT page FROM chunks WHERE file_id=? AND page{op}? AND page>0 GROUP BY page ORDER BY page {order} LIMIT 1',(r['file_id'],r['page'])).fetchone()
                    if other:
                        adjacent,_=ordered_page(c,r['file_id'],other[0])
                        if adjacent:r[field]=adjacent[-1 if field=='previous' else 0]['id']
                        elif adjacent is None:r['order_note']+='；相邻页含多片，片内顺序待确认'
        r['units']=units(cid);return r

    @app.get('/api/source-units')
    def source_units(cid:int|None=None,key:str='',offset:int=0):return units(cid,key,max(0,offset))

    @app.post('/api/source-slices/{cid}/quality')
    def update_quality(cid:int,body:dict):
        status=body.get('status');reason=str(body.get('reason','')).strip()
        if status not in ('body','suspect','noise','reset') or not reason:raise HTTPException(422,'需要内容状态和纠正理由')
        with connect() as c:
            row=c.execute('SELECT text FROM chunks WHERE id=?',(cid,)).fetchone()
            if not row:raise HTTPException(404,'片段不存在')
            import hashlib
            values=(cid,status,reason,'manual/'+quality.RULE,hashlib.sha256(row[0].encode()).hexdigest(),now())
            c.execute('INSERT INTO chunk_quality_events(chunk_id,status,reason,rule,text_hash,updated) VALUES(?,?,?,?,?,?)',values)
            if status=='reset':c.execute('DELETE FROM chunk_quality WHERE chunk_id=?',(cid,))
            else:c.execute('INSERT OR REPLACE INTO chunk_quality VALUES(?,?,?,?,?,?)',values)
        return {'status':status,'text_preserved':True,'index_restarted':False}

    @app.post('/api/slice-quality/pilot')
    def pilot(body:dict):
        file_id=str(body.get('file_id','')).strip()
        if not file_id:raise HTTPException(422,'请先选择一个文件，试点不扫描全库')
        from collections import Counter
        import hashlib
        with connect() as c:
            rows=c.execute('SELECT id,text,page FROM chunks WHERE file_id=?',(file_id,)).fetchall()
            boundary=Counter()
            for r in rows:
                lines=[x.strip() for x in r['text'].splitlines() if x.strip()]
                boundary.update(set(lines[:1]+lines[-1:]))
            marked=0
            for r in rows:
                prior=c.execute('SELECT rule FROM chunk_quality WHERE chunk_id=?',(r['id'],)).fetchone()
                if prior and prior[0].startswith('manual/'):continue
                status,reason=quality.classify(r['text'])
                lines=[x.strip() for x in r['text'].splitlines() if x.strip()]
                repeats=[x for x in lines[:1]+lines[-1:] if boundary[x]>=3 and len(x)>4]
                if repeats and status=='body':status,reason='suspect','重复页首/页尾行（至少3片）；保留正文，待人工对照：'+repeats[0][:120]
                if status=='body':continue
                values=(r['id'],status,reason,quality.RULE,hashlib.sha256(r['text'].encode()).hexdigest(),now())
                c.execute('INSERT OR REPLACE INTO chunk_quality VALUES(?,?,?,?,?,?)',values)
                c.execute('INSERT INTO chunk_quality_events(chunk_id,status,reason,rule,text_hash,updated) VALUES(?,?,?,?,?,?)',values);marked+=1
        return {'checked':len(rows),'marked':marked,'text_preserved':True,'index_restarted':False}
