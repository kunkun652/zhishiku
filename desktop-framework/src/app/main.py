from __future__ import annotations
import hashlib, json, os, re, sqlite3, sys, uuid, zipfile, io, subprocess, threading
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager, closing
from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from .templates import TEMPLATES, RELATIONS
from . import retrieval, semantic_search

ROOT = Path(os.environ.get('ZH_DATA_ROOT', str(Path(sys.executable).parent / 'data' if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[2]/'data'))).resolve()
STATIC = Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))/'static'
ROOT.mkdir(parents=True,exist_ok=True)
DB = ROOT/'knowledge.sqlite3'
LOCK = threading.RLock()
EMBEDDINGS = semantic_search.Embeddings(ROOT)
@contextmanager
def connect():
    c=sqlite3.connect(DB,timeout=20,uri=True); c.row_factory=sqlite3.Row
    try:
        with c: yield c
    finally: c.close()
with connect() as c:
    c.execute('PRAGMA journal_mode=WAL')
    c.executescript('''CREATE TABLE IF NOT EXISTS objects(id TEXT PRIMARY KEY, type TEXT, title TEXT, version INTEGER, status TEXT, payload TEXT, hash TEXT, updated TEXT);
    CREATE TABLE IF NOT EXISTS versions(id TEXT, version INTEGER, snapshot TEXT, PRIMARY KEY(id,version));
    CREATE TABLE IF NOT EXISTS relations(id TEXT PRIMARY KEY, source TEXT, target TEXT, type TEXT, evidence TEXT, source_version INTEGER, target_version INTEGER);
    CREATE TABLE IF NOT EXISTS files(id TEXT PRIMARY KEY, object_id TEXT, name TEXT, sha256 TEXT, size INTEGER, path TEXT);
    CREATE TABLE IF NOT EXISTS packages(id TEXT PRIMARY KEY, payload TEXT);
    CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
    INSERT OR IGNORE INTO meta VALUES('revision','0');''')
    retrieval.init(c)
    from . import content_quality
    content_quality.init(c)
    from . import wiki
    wiki.init(c)

def now(): return datetime.now(timezone.utc).isoformat()
def encoded(x): return json.dumps(x,ensure_ascii=False,sort_keys=True,allow_nan=False)
def digest(x): return hashlib.sha256(encoded(x).encode()).hexdigest()
def record(row):
    if not row: raise HTTPException(404,'对象不存在')
    r=dict(row); r['data']=json.loads(r.pop('payload')); return r
def get(oid,version=None):
    with connect() as c:
        if version:
            row=c.execute('SELECT snapshot FROM versions WHERE id=? AND version=?',(oid,version)).fetchone()
            if not row: raise HTTPException(404,'版本不存在')
            return json.loads(row[0])
        return record(c.execute('SELECT * FROM objects WHERE id=?',(oid,)).fetchone())
def revision(c): c.execute("UPDATE meta SET value=CAST(value AS INTEGER)+1 WHERE key='revision'")
def validate(body):
    kind=body.get('type'); title=body.get('title','').strip()
    if kind not in TEMPLATES or not title: raise HTTPException(422,'请选择模板并填写名称')
    data=body.get('data',{})
    if not isinstance(data,dict): raise HTTPException(422,'data 必须是结构化对象')
    allowed={f['key'] for f in TEMPLATES[kind]['fields']}
    if set(data)-allowed: raise HTTPException(422,'模板以外字段：'+','.join(set(data)-allowed))
    for key,value in data.items():
        if key in ('properties','regions'):
            if not isinstance(value,list): raise HTTPException(422,key+' 必须是 JSON 数组')
        elif not isinstance(value,str): raise HTTPException(422,key+' 必须是文本')
    if kind=='material':
        if data.get('solver_card') not in ('',None,'MAT1','MAT8'): raise HTTPException(422,'材料只允许 MAT1 / MAT8')
        for p in data.get('properties',[]):
            if not isinstance(p,dict) or not {'name','value','unit','source'} <= p.keys(): raise HTTPException(422,'每个参数需要 name/value/unit/source；未知数值用 null')
            if p['name'].upper() in ('PSHELL','PCOMP','THICKNESS','厚度','铺层'): raise HTTPException(422,'厚度与铺层应放在模型属性')
            if p['value'] is not None and (isinstance(p['value'],bool) or not isinstance(p['value'],(int,float))): raise HTTPException(422,'参数 value 必须为数值或 null')
    if kind=='model':
        for region in data.get('regions',[]):
            if not isinstance(region,dict) or not {'semantic_name','geometry_version','mesh_version','faces','nodes','elements','source'}<=region.keys(): raise HTTPException(422,'区域映射需要 semantic_name/geometry_version/mesh_version/faces/nodes/elements/source')
    return kind,title,data

def save(body,oid=None):
    kind,title,data=validate(body)
    with LOCK,connect() as c:
        old=c.execute('SELECT * FROM objects WHERE id=?',(oid,)).fetchone() if oid else None
        if oid and not old: raise HTTPException(404,'对象不存在')
        if old and (body.get('version')!=old['version']): raise HTTPException(409,'对象已更新，请重新读取后编辑')
        if old and old['type']!=kind: raise HTTPException(422,'不能更改对象类型')
        oid=oid or str(uuid.uuid4()); version=(old['version']+1) if old else 1
        status=body.get('status','candidate')
        if status not in ('candidate','conflict','retired'): raise HTTPException(422,'普通保存只允许候选、冲突或停用；不得自行升级为已复核')
        item={'id':oid,'type':kind,'title':title,'version':version,'status':status,'data':data,'updated':now()}
        item['hash']=digest({k:v for k,v in item.items() if k!='updated'})
        c.execute('INSERT OR REPLACE INTO objects VALUES(?,?,?,?,?,?,?,?)',(oid,kind,title,version,status,encoded(data),item['hash'],item['updated']))
        c.execute('INSERT INTO versions VALUES(?,?,?)',(oid,version,encoded(item))); revision(c)
    return item

app=FastAPI(title='知衡 · 仿真知识库',version='1.3.0-readable-workspaces')
from .slice_workspace import install as install_slices
install_slices(app,connect,ROOT,now)
@app.middleware('http')
async def local_boundary(request:Request,call_next):
    # Prevent cross-site browser writes to a loopback desktop service.
    host=request.headers.get('host','')
    if not re.fullmatch(r'(127\.0\.0\.1|localhost|testserver)(:\d+)?',host): return Response('Invalid host',400)
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin=request.headers.get('origin')
        if origin and origin not in ('http://'+host,'https://'+host): return Response('Cross-origin writes denied',403)
    return await call_next(request)

@app.get('/api/health')
def health():
    with connect() as c:
        counts={r[0]:r[1] for r in c.execute('SELECT type,COUNT(*) FROM objects GROUP BY type')}
        rev=int(c.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0])
    statusfile=ROOT/'semantica-status.json'
    semantic=json.loads(statusfile.read_text('utf-8')) if statusfile.exists() else {'status':'not_built'}
    if semantic.get('status')=='passed' and semantic.get('revision')!=rev: semantic={**semantic,'status':'stale','message':'知识已更新，请重建派生图谱'}
    if (ROOT/'graph-manifest.json').exists():semantic=semantic_consistency_after_build()
    embedding=EMBEDDINGS.status()
    return {'name':'知衡仿真知识库','build':'1.3.0-readable-workspaces','counts':counts,'total':sum(counts.values()),'revision':rev,'data_root':str(ROOT),'agent_connected':False,'retrieval':'关键词 + 本地语义向量 + 有依据的图谱关联','embedding':embedding,'semantica':semantic,'engineering_approval':False}

@app.get('/api/embedding/status')
def embedding_status(): return EMBEDDINGS.status()
@app.post('/api/embedding/build')
def embedding_build():
    try:return EMBEDDINGS.call('/build')
    except Exception as exc:raise HTTPException(503,str(exc))
@app.get('/api/embedding/v2/status')
def embedding_v2_status():
    try:return EMBEDDINGS.call('/v2/status')
    except Exception as exc:raise HTTPException(503,str(exc))
@app.post('/api/embedding/v2/{action}')
def embedding_v2_action(action:str,body:dict={}):
    if action not in ('build','stop','activate'):raise HTTPException(422,'未知操作')
    try:return EMBEDDINGS.call('/v2/'+action,body)
    except Exception as exc:raise HTTPException(503,str(exc))

@app.get('/api/templates')
def templates(): return {'templates':list(TEMPLATES.values()),'relations':RELATIONS}
@app.get('/api/templates/{kind}')
def template(kind:str):
    if kind not in TEMPLATES: raise HTTPException(404,'模板不存在')
    return {'schema':'zhiheng-object/1','type':kind,'title':'','status':'candidate','data':{f['key']:[] if f['kind']=='json' else '' for f in TEMPLATES[kind]['fields']}}
@app.post('/api/objects')
def create(body:dict): return save(body)
@app.put('/api/objects/{oid}')
def update(oid:str,body:dict): return save(body,oid)
@app.get('/api/objects/{oid}')
def read(oid:str,version:int|None=None): return get(oid,version)
@app.get('/api/objects/{oid}/versions')
def history(oid:str):
    with connect() as c: return [json.loads(r[0]) for r in c.execute('SELECT snapshot FROM versions WHERE id=? ORDER BY version DESC',(oid,))]
SEARCH_SNAPSHOTS={}
SEARCH_SNAPSHOT_LOCK=threading.Lock()
@app.get('/api/search')
def search(q:str='',type:str='',analysis_type:str='',status:str='',category:str='',designation:str='',mode:str='hybrid',limit:int=100,offset:int=0,snapshot:str='',graph_backend:str='authority',object_id:str=''):
    import time
    from concurrent.futures import TimeoutError
    from . import orchestrator
    started=time.monotonic()
    if mode not in ('auto','hybrid','keyword','semantic','graph'):raise HTTPException(422,'未知检索模式')
    with connect() as c:quality_revision=c.execute('SELECT COALESCE(MAX(id),0) FROM chunk_quality_events').fetchone()[0]
    signature=encoded([q,type,analysis_type,status,category,designation,mode,graph_backend,object_id,quality_revision])
    if snapshot:
        with SEARCH_SNAPSHOT_LOCK:cached=SEARCH_SNAPSHOTS.get(snapshot)
        if not cached or time.monotonic()-cached['created']>300 or cached['signature']!=signature:raise HTTPException(409,'检索快照已过期，请重新检索')
        with connect() as c:current={r['id']:r['hash'] for r in c.execute('SELECT id,hash FROM objects')}
        page=cached['all'][max(0,offset):max(0,offset)+max(1,min(limit,500))]
        valid=[r for r in page if current.get(r['id'])==r['hash']]
        return {**cached['response'],'items':valid,'snapshot':snapshot,'message':cached['response']['message']+('；本页存在已更新对象，请重新检索' if len(valid)!=len(page) else '')}
    selected_mode,reason=orchestrator.route(q,mode)
    with connect() as c:
        c.execute('BEGIN')
        items=[record(r) for r in c.execute('SELECT * FROM objects ORDER BY updated DESC')]
        eligible=[r for r in items if semantic_search.allowed(r,type,analysis_type,status,category,designation)]
        if object_id:
            scoped={object_id}
            for edge in c.execute('SELECT source,target FROM relations WHERE source=? OR target=?',(object_id,object_id)):scoped.update(edge)
            eligible=[r for r in eligible if r['id'] in scoped]
        rev=int(c.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0])
        vector=[];vector_status={'status':'not_requested'};future=None;channels=[];degradations=[]
        if q.strip() and selected_mode in ('hybrid','semantic'):
            def vector_call():
                state=EMBEDDINGS.status()
                hits=EMBEDDINGS.call('/search',{'query':q,'eligible':{r['id']:r['hash'] for r in eligible}}) if state.get('indexed',0) else []
                return state,hits
            future=orchestrator.POOL.submit(vector_call)
        result=retrieval.retrieve(c,eligible,q,limit=max(len(eligible),1))
        lexical=result['items'] if selected_mode!='semantic' else []
        if selected_mode in ('keyword','hybrid') or not q.strip():channels.append('keyword')
        if future:
            try:
                vector_status,vector=future.result(timeout=25)
                if vector_status.get('indexed',0):channels.append('semantic')
                else:degradations.append('语义索引不可用')
            except Exception as exc:
                future.cancel();vector_status={'status':'failed','message':str(exc)};degradations.append('语义通路超时或失败；已返回可用通路')
        graph_hits=[];graph_status={'status':'not_requested','backend':'authority'};ambiguity=[]
        if selected_mode in ('graph','hybrid') and q.strip():
            exact=[r for r in eligible if r['id']==q or r['title'].casefold()==q.casefold()]
            named=[r for r in eligible if len(r['title'])>2 and r['title'].casefold() in q.casefold()]
            seeds=exact or named
            if selected_mode=='graph' and len(seeds)>1:
                ambiguity=[{'id':r['id'],'title':r['title'],'type':r['type']} for r in seeds]
                seeds=[];degradations.append('对象名称存在歧义，请使用对象 ID')
            if selected_mode=='hybrid' and not seeds:seeds=lexical[:3]
            edges=None;backend='authority';backend_reason='直接查询权威关系'
            if graph_backend=='semantica':
                authority_edges=[dict(r) for r in c.execute('SELECT * FROM relations')]
                state=orchestrator.derived_graph.state(ROOT,rev,items,authority_edges)
                if state['status']=='consistent':
                    edges=json.loads((ROOT/state['artifact']).read_text('utf-8'))['canonical']['edges'];backend='semantica';backend_reason='派生内容校验一致'
                else:backend_reason='派生不可用或过期，回退主库：'+state['status'];degradations.append(backend_reason)
            graph_hits=orchestrator.graph_recall(c,eligible,seeds,edges=edges,backend=backend)
            graph_status={'status':'ready','backend':backend,'reason':backend_reason,'seeds':[r['id'] for r in seeds]}
            channels.append('graph')
            if selected_mode=='graph':lexical=[]
        vector=content_quality.filter_vectors(c,vector)
        found=orchestrator.fuse(lexical,vector,graph_hits,eligible)
        # Preserve explicit numbered identifiers across lexical and semantic recall.
        codes=[v for v in re.findall(r'\b[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+\b',q) if any(ch.isdigit() for ch in v) and any(ch.isalpha() for ch in v) and not re.fullmatch(r'[0-9a-fA-F-]{36}',v)]
        if codes:
            def satisfies_codes(r):
                body=(r['title']+' '+encoded(r['data'])+' '+' '.join(e.get('text','') for e in r.get('evidence',[]))).casefold()
                return all(code.casefold() in body for code in codes)
            found=[r for r in found if satisfies_codes(r)]
        selected=found[max(0,offset):max(0,offset)+max(1,min(limit,500))]
        for r in selected:r['source_revision']=rev
        message='；'.join(degradations) or ('' if found else '未找到可引用依据；请登记资料缺口。')
        response={**result,'items':selected,'total':len(found),'excluded':len(items)-len(eligible),'status':'ok' if found else 'unavailable' if selected_mode=='semantic' and degradations else 'no_matches','message':message,'embedding':vector_status,'graph':graph_status,'mode':mode,'ambiguity':ambiguity,'run':{'channels':channels,'route':reason,'selected_mode':selected_mode,'revision':rev,'elapsed_ms':round((time.monotonic()-started)*1000),'degradations':degradations,'answer_model':'未配置；提供检索证据'}}
        token=uuid.uuid4().hex
        with SEARCH_SNAPSHOT_LOCK:
            while len(SEARCH_SNAPSHOTS)>=8:SEARCH_SNAPSHOTS.pop(next(iter(SEARCH_SNAPSHOTS)))
            SEARCH_SNAPSHOTS[token]={'created':time.monotonic(),'signature':signature,'all':found,'response':response}
        return {**response,'snapshot':token}

@app.get('/api/collection')
def collection():
    with connect() as c:
        categories=[dict(r) for r in c.execute('SELECT category,COUNT(*) count FROM sources GROUP BY category ORDER BY category')]
        extraction=[dict(r) for r in c.execute('SELECT extraction,COUNT(*) count FROM sources GROUP BY extraction')]
        chunks=c.execute('SELECT COUNT(*) FROM chunks').fetchone()[0]
        sources=c.execute('SELECT COUNT(*),SUM(pages),SUM(indexed_pages) FROM sources').fetchone()
    return {'categories':categories,'extraction':extraction,'chunks':chunks,'sources':sources[0],'pages':sources[1] or 0,'indexed_pages':sources[2] or 0,'training':'候选导出；来源许可与人工复核通过前不得作为训练就绪数据'}

@app.get('/api/objects/{oid}/evidence')
def evidence(oid:str,page:int=0,offset:int=0):
    get(oid)
    with connect() as c:
        sql='SELECT page,text,file_id FROM chunks WHERE object_id=?';args=[oid]
        if page:sql+=' AND page=?';args.append(page)
        return [dict(r) for r in c.execute(sql+' ORDER BY page,id LIMIT 30 OFFSET ?',args+[max(0,offset)])]

@app.get('/api/index-units')
def index_units(object_id:str='',file_id:str='',offset:int=0,limit:int=30,key:str=''):
    from index_generations import index_path
    path=index_path(ROOT)
    if not path.exists():return {'items':[],'total':0,'message':'新分片索引尚未建立'}
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as c:
        c.row_factory=sqlite3.Row
        conditions=[];args=[]
        for field,value in [('u.object_id',object_id),('u.file_id',file_id),('u.key',key)]:
            if value:conditions.append(field+'=?');args.append(value)
        where=' WHERE '+' AND '.join(conditions) if conditions else ''
        total=c.execute('SELECT COUNT(*) FROM units u'+where,args).fetchone()[0]
        rows=[dict(r) for r in c.execute('SELECT u.*,v.key IS NOT NULL encoded FROM units u LEFT JOIN vectors v ON v.key=u.key'+where+' ORDER BY u.parent,u.start LIMIT ? OFFSET ?',args+[max(1,min(limit,100)),max(0,offset)])]
        encoding=c.execute("SELECT value FROM meta WHERE key='encoding'").fetchone()
    return {'items':rows,'total':total,'encoding':json.loads(encoding[0]) if encoding else None,'location':'start/end 相对父正文块，非未经验证的原文件字节位置'}

@app.get('/api/slices')
def slices(object_id:str='',file_id:str='',offset:int=0,limit:int=30):
    where=[];args=[]
    if object_id:where.append('object_id=?');args.append(object_id)
    if file_id:where.append('file_id=?');args.append(file_id)
    clause=' WHERE '+' AND '.join(where) if where else ''
    with connect() as c:
        total=c.execute('SELECT COUNT(*) FROM chunks'+clause,args).fetchone()[0]
        rows=[dict(r) for r in c.execute('SELECT id,object_id,file_id,page,length(text) characters,substr(text,1,180) preview FROM chunks'+clause+' ORDER BY id LIMIT ? OFFSET ?',args+[max(1,min(limit,100)),max(0,offset)])]
    return {'items':rows,'total':total,'offset':offset,'kind':'原有正文块；不是完整编码覆盖声明'}

@app.get('/api/slices/{cid}')
def slice_detail(cid:int):
    with connect() as c:
        row=c.execute('SELECT * FROM chunks WHERE id=?',(cid,)).fetchone()
        if not row:raise HTTPException(404,'片段不存在')
        result=dict(row)
        file=c.execute('SELECT sha256,name FROM files WHERE id=?',(row['file_id'],)).fetchone()
        result.update({'file':dict(file) if file else None,'characters':len(row['text']),'offset':None,'location_status':'原页码沿用已有解析记录；字符偏移未登记','tokens':None,'encoding_status':'旧索引最多编码前512 tokens；未核实本片编码状态','previous':None,'next':None})
        for name,operator,order in [('previous','<','DESC'),('next','>','ASC')]:
            other=c.execute(f'SELECT MIN(id),COUNT(*) FROM chunks WHERE file_id=? AND page{operator}? AND page>0 GROUP BY page ORDER BY page {order} LIMIT 1',(row['file_id'],row['page'])).fetchone()
            same=c.execute('SELECT COUNT(*) FROM chunks WHERE file_id=? AND page=?',(row['file_id'],row['page'])).fetchone()[0]
            result[name]=other[0] if other and other[1]==1 and same==1 and row['file_id'] and row['page'] else None
        result['location_status']+='；相邻片仅按同文件可靠页码定位，同页多片顺序未登记时禁用'
    return result

@app.get('/api/answer')
def answer(q:str):
    result=search(q=q,limit=5)
    return {'mode':'可引用摘录（非大模型生成）','query':q,'status':result['status'],'answers':[{'object_id':r['id'],'title':r['title'],'text':r['data'].get('definition') or r['data'].get('goal') or r['data'].get('summary'),'source':r['data'].get('source'),'evidence':r['evidence'],'status':r['status']} for r in result['items']],'limitations':'候选资料只提供参考；参数与适用性需按当前任务核实。'}

@app.get('/api/datasets/candidates')
def candidates(kind:str='cards'):
    types={'cards':('term','material','mesh','condition'),'cases':('case',),'tasks':('task',)}
    if kind not in types:raise HTTPException(422,'仅支持 cards / cases / tasks')
    with connect() as c:
        lines=[]
        for row in c.execute('SELECT * FROM objects'):
            if row['type'] not in types[kind]:continue
            item=record(row)
            lines.append(encoded({'schema':'zhiheng-training-candidate/1','object':item,'training_ready':False,'split':None,'family_id':None,'blockers':['来源训练许可待确认','人工复核待完成','来源家族分组待确认']}))
    return Response('\n'.join(lines)+'\n',media_type='application/x-ndjson',headers={'Content-Disposition':f'attachment; filename="{kind}-candidates.jsonl"'})
@app.post('/api/relations')
def relation(body:dict):
    a=get(body.get('source','')); b=get(body.get('target',''))
    if body.get('type') not in RELATIONS or not str(body.get('evidence','')).strip(): raise HTTPException(422,'关系需要合法类型和建立依据')
    if a['id']==b['id']: raise HTTPException(422,'不允许自关联')
    item={'id':str(uuid.uuid4()),'source':a['id'],'target':b['id'],'type':body['type'],'evidence':body['evidence'],'source_version':a['version'],'target_version':b['version']}
    with connect() as c:
        c.execute('INSERT INTO relations VALUES(?,?,?,?,?,?,?)',tuple(item.values())); revision(c)
    return item
@app.get('/api/objects/{oid}/wiki')
def wiki_detail(oid:str):
    obj=get(oid)
    with connect() as c:
        relations=[dict(r) for r in c.execute('SELECT * FROM relations WHERE source=? OR target=?',(oid,oid))]
        candidates=[dict(r) for r in c.execute('SELECT * FROM relation_candidates WHERE source=? OR target=?',(oid,oid))]
        versions={r['id']:r['version'] for r in c.execute('SELECT id,version FROM objects')}
        for r in candidates:
            r['stale']=versions.get(r['source'])!=r['source_version'] or versions.get(r['target'])!=r['target_version']
            p=c.execute('SELECT metadata FROM candidate_provenance WHERE id=?',(r['id'],)).fetchone()
            if p:
                metadata=json.loads(p[0]);chunk=c.execute('SELECT text FROM chunks WHERE id=?',(metadata['chunk_id'],)).fetchone()
                r['stale']=r['stale'] or not chunk or hashlib.sha256(chunk[0].encode()).hexdigest()!=metadata['parent_hash'];r['provenance']=metadata
        for r in relations:
            r['stale']=versions.get(r['source'])!=r['source_version'] or versions.get(r['target'])!=r['target_version']
    return {'object':obj,'outgoing':[r for r in relations if r['source']==oid],'incoming':[r for r in relations if r['target']==oid],'candidates':candidates}

@app.post('/api/objects/{oid}/discover-relations')
def discover_relations(oid:str):
    get(oid)
    with LOCK,connect() as c:
        items=[record(r) for r in c.execute('SELECT * FROM objects')]
        return wiki.discover(c,items,oid)

@app.post('/api/relations/reconcile-explicit')
def reconcile_explicit():
    with LOCK,connect() as c:
        items=[record(r) for r in c.execute('SELECT * FROM objects')]
        before=c.execute('SELECT COUNT(*) FROM objects o WHERE NOT EXISTS(SELECT 1 FROM relations r WHERE r.source=o.id OR r.target=o.id)').fetchone()[0]
        accepted=[];missing=[]
        for item in items:
            if not any(item['data'].get(k) for k in ('model_ids','card_ids','task_id','run_ids')):continue
            result=wiki.discover(c,items,item['id'],sentences=False);missing.extend({'object_id':item['id'],**r} for r in result['missing_targets'])
            for cid in result['candidate_ids']:
                candidate=c.execute('SELECT status FROM relation_candidates WHERE id=?',(cid,)).fetchone()
                if candidate[0]=='pending':accepted.append(wiki.audit(c,cid,'accept',now()))
        after=c.execute('SELECT COUNT(*) FROM objects o WHERE NOT EXISTS(SELECT 1 FROM relations r WHERE r.source=o.id OR r.target=o.id)').fetchone()[0]
    return {'accepted':accepted,'missing_targets':missing,'isolated_before':before,'isolated_after':after,'method':'仅结构化字段中的精确对象 ID；每条均可在 Wiki 候选记录撤销','engineering_approval':False}

@app.post('/api/relation-candidates/review')
def review_relations(body:dict):
    ids=body.get('ids',[])
    if not isinstance(ids,list) or not 1<=len(ids)<=100:raise HTTPException(422,'需要1至100个候选 ID')
    try:
        with LOCK,connect() as c:return [wiki.audit(c,cid,body.get('action'),now()) for cid in dict.fromkeys(ids)]
    except ValueError as exc:raise HTTPException(409,str(exc))

@app.get('/api/objects-lookup')
def object_lookup(q:str='',type:str='',limit:int=50,offset:int=0):
    with connect() as c:
        rows=[record(r) for r in c.execute('SELECT * FROM objects ORDER BY title,id')]
    q=q.strip().casefold()
    matches=[r for r in rows if (not type or r['type']==type) and (not q or q==r['id'].casefold() or q in r['title'].casefold() or q in str(r['data'].get('aliases','')).casefold())]
    matches.sort(key=lambda r:(r['id'].casefold()!=q,r['title'].casefold()!=q))
    return {'items':matches[max(0,offset):max(0,offset)+max(1,min(limit,100))],'total':len(matches)}

GRAPH_SNAPSHOTS={}
def graph_snapshot(backend,snapshot=''):
    import time
    if backend not in ('authority','semantica','diff'):raise HTTPException(422,'未知图谱后端')
    if snapshot:
        value=GRAPH_SNAPSHOTS.get(snapshot)
        if not value or value['backend']!=backend or time.monotonic()-value['created']>3600:raise HTTPException(409,'图谱快照过期，请刷新当前范围')
        return value
    from . import derived_graph
    with connect() as c:rev,nodes,edges=derived_graph.read_source(c,record)
    state=None;derived=None
    if backend in ('semantica','diff'):
        state=derived_graph.state(ROOT,rev,nodes,edges)
        if state.get('artifact') and state['status']!='failed':derived=json.loads((ROOT/state['artifact']).read_text('utf-8'))['canonical']
        if backend=='semantica':
            if not state.get('artifact') or state['status']=='failed':raise HTTPException(409,'派生图不可用；请明确选择主库或检查派生状态')
            artifact=json.loads((ROOT/state['artifact']).read_text('utf-8'))['canonical']
            # Canonical artifacts may have no payload. Never borrow current data.
            historical=[]
            with connect() as c:
                for n in artifact['nodes']:
                    row=c.execute('SELECT snapshot FROM versions WHERE id=? AND version=?',(n['id'],n['version'])).fetchone()
                    old=json.loads(row[0]) if row else {}
                    if old.get('hash')!=n['hash']:old={}
                    historical.append({**old,**n,'data':old.get('data',{}),'status':old.get('status','历史字段未保存')})
            nodes=historical;edges=artifact['edges'];rev=state['revision']
    token=uuid.uuid4().hex
    value={'nodes':nodes,'edges':edges,'backend':backend,'revision':rev,'consistency':state,'derived':derived,'snapshot':token,'created':time.monotonic()}
    while len(GRAPH_SNAPSHOTS)>=12:GRAPH_SNAPSHOTS.pop(next(iter(GRAPH_SNAPSHOTS)))
    GRAPH_SNAPSHOTS[token]=value
    return value

@app.get('/api/graph-diff-item')
def graph_diff_item(snapshot:str,kind:str,id:str):
    g=graph_snapshot('diff',snapshot)
    if kind not in ('nodes','edges'):raise HTTPException(422,'未知差异类型')
    current=next((x for x in g[kind] if x['id']==id),None)
    derived=next((x for x in (g['derived'] or {}).get(kind,[]) if x['id']==id),None)
    return {'current':current,'derived':derived,'snapshot':snapshot,'authority_revision':g['revision'],'derived_revision':(g['consistency'] or {}).get('revision')}

@app.get('/api/graph-node/{oid}')
def graph_node(oid:str,backend:str='authority',snapshot:str='',offset:int=0,limit:int=30):
    g=graph_snapshot(backend,snapshot);byid={n['id']:n for n in g['nodes']}
    if oid not in byid:raise HTTPException(404,'此快照不存在该对象')
    rel=sorted((e for e in g['edges'] if oid in (e['source'],e['target'])),key=lambda e:e['id'])
    page=rel[max(0,offset):max(0,offset)+max(1,min(limit,100))]
    return {'node':byid[oid],'relations':page,'neighbors':{k:byid.get(k) for e in page for k in (e['source'],e['target'])},'total':len(rel),'outgoing':sum(e['source']==oid for e in rel),'incoming':sum(e['target']==oid for e in rel),'backend':backend,'revision':g['revision'],'snapshot':g['snapshot']}

@app.get('/api/graph')
def graph(focus:str='',hops:int=1,type:str='',limit:int=200,offset:int=0,backend:str='authority',overview:bool=False,snapshot:str='',include:str='',full:bool=False):
    from .graph_workspace import select,aggregate,complete
    g=graph_snapshot(backend,snapshot);nodes=g['nodes'];edges=g['edges']
    result=complete(nodes,edges) if full else aggregate(nodes,edges) if overview and not focus and not type else select(nodes,edges,focus,hops,type,limit,offset)
    if include and not full and not result.get('aggregate'):
        keep={n['id'] for n in result['nodes']}|set(include.split(',')[:5000])
        result['nodes']=[n for n in nodes if n['id'] in keep]
        versions={n['id']:n['version'] for n in result['nodes']}
        result['edges']=[{**e,'stale':versions.get(e['source'])!=e['source_version'] or versions.get(e['target'])!=e['target_version']} for e in edges if e['source'] in keep and e['target'] in keep]
    return {**result,'backend':backend,'snapshot':g['snapshot'],'revision':g['revision'],'consistency':g['consistency']}

@app.post('/api/packages')
def package(body:dict):
    ids=body.get('object_ids',[])
    if not isinstance(ids,list) or len(ids)>100: raise HTTPException(422,'最多选择100个对象')
    objects=[get(i) for i in dict.fromkeys(ids)]
    gaps=[]
    for kind in ('task','model','material','condition','mesh','workflow','skill','tool','validation'):
        if not any(o['type']==kind for o in objects): gaps.append('缺少'+TEMPLATES[kind]['label'])
    for o in objects:
        for f in ('source','scope','units'):
            if not o['data'].get(f): gaps.append(o['title']+'：'+dict((x['key'],x['label']) for x in TEMPLATES[o['type']]['fields'])[f]+'待确认')
        if o['status']!='reviewed': gaps.append(o['title']+'：未完成独立复核')
    with connect() as c:
        files=[dict(r) for r in c.execute('SELECT id,object_id,name,sha256,size FROM files') if r['object_id'] in ids]
        rev=int(c.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0])
        related=[dict(r) for r in c.execute('SELECT * FROM relations') if r['source'] in ids and r['target'] in ids]
    result={'schema':'zhiheng-task-package/1','id':str(uuid.uuid4()),'created':now(),'revision':rev,'title':body.get('title','任务知识包'),'objects':objects,'files':files,'relations':related,'gaps':gaps,'executable':False,'reason':'当前为知识框架；执行授权与完整适用性审核尚未实现。','agent_connected':False}
    with connect() as c: c.execute('INSERT INTO packages VALUES(?,?)',(result['id'],encoded(result)))
    return result
@app.get('/api/packages')
def packages():
    with connect() as c: return [json.loads(r[0]) for r in c.execute('SELECT payload FROM packages')]
@app.post('/api/import')
def import_object(body:dict):
    # Imports are always new candidates, never trusted review records.
    return save({**body,'status':'candidate'})
@app.get('/api/export')
def export():
    with connect() as c:
        return {'schema':'zhiheng-export/1','objects':[record(r) for r in c.execute('SELECT * FROM objects')],'relations':[dict(r) for r in c.execute('SELECT * FROM relations')],'templates':list(TEMPLATES.values())}
@app.post('/api/objects/{oid}/files')
async def attach(oid:str,file:UploadFile=File(...)):
    get(oid)
    name=Path((file.filename or 'asset').replace('\\','/')).name
    suffix=Path(name).suffix.lower()
    if suffix not in {'.pdf','.step','.stp','.iges','.igs','.brep','.bdf','.nas','.dat','.op2','.f06','.stl','.obj','.png','.jpg','.json','.txt','.csv','.log'}: raise HTTPException(422,'暂不支持此文件类型')
    raw=await file.read(150*1024*1024+1)
    if len(raw)>150*1024*1024: raise HTTPException(413,'单文件限制150 MB')
    sha=hashlib.sha256(raw).hexdigest(); path=ROOT/'assets'/(sha+suffix); path.parent.mkdir(exist_ok=True)
    if not path.exists(): path.write_bytes(raw)
    with connect() as c:
        old=c.execute('SELECT * FROM files WHERE object_id=? AND sha256=? AND name=?',(oid,sha,name)).fetchone()
        if old: return dict(old)
        fid=str(uuid.uuid4()); c.execute('INSERT INTO files VALUES(?,?,?,?,?,?)',(fid,oid,name,sha,len(raw),str(path.relative_to(ROOT)))); revision(c)
    return {'id':fid,'name':name,'sha256':sha,'size':len(raw)}
@app.get('/api/objects/{oid}/files')
def files(oid:str):
    get(oid)
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT DISTINCT f.* FROM files f WHERE object_id=? OR object_id IN (SELECT target FROM relations WHERE source=? AND type='来源于')",(oid,oid))]
def asset(fid):
    with connect() as c: row=c.execute('SELECT * FROM files WHERE id=?',(fid,)).fetchone()
    if not row: raise HTTPException(404,'文件未登记')
    path=(ROOT/row['path']).resolve()
    if not path.is_relative_to(ROOT/'assets') or not path.is_file(): raise HTTPException(404,'受管文件不可用')
    if hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']: raise HTTPException(409,'文件校验失败')
    return row,path
@app.get('/api/model-assets/{fid}/file')
def file_content(fid:str):
    row,path=asset(fid)
    disposition='attachment' if path.suffix.lower() in ('.html','.htm','.svg') else 'inline'
    return FileResponse(path,filename=row['name'],content_disposition_type=disposition,headers={'X-Content-Type-Options':'nosniff'})
@app.get('/api/model-assets/{fid}/mesh')
def mesh(fid:str):
    row,path=asset(fid)
    if path.suffix.lower() not in ('.stl','.obj','.bdf','.nas','.dat'): raise HTTPException(422,'此格式尚未接入预览解析器；可打开原件')
    try:
        if path.suffix.lower() in ('.bdf','.nas','.dat'):
            from pyNastran.bdf.bdf import BDF
            model=BDF(debug=False); model.read_bdf(str(path),xref=True)
            ids=sorted(model.nodes); index={n:i for i,n in enumerate(ids)}; points=[model.nodes[n].get_position().tolist() for n in ids]
            tris=[]; edges=[]; unsupported=0
            for e in model.elements.values():
                ns=[index[n] for n in e.node_ids if n is not None]
                if e.type in ('CTRIA3','CTRIA6'): tris.extend(ns[:3])
                elif e.type in ('CQUAD4','CQUAD8'): tris.extend([ns[0],ns[1],ns[2],ns[0],ns[2],ns[3]])
                elif e.type in ('CBAR','CBEAM','CROD','CONROD'): edges.extend(ns[:2])
                else: unsupported+=1
            warnings=[f'{unsupported} 个未支持单元未显示；此预览不用于网格质量验收。'] if unsupported else ['仅展示几何；载荷与结果未作验证。']
            if not tris and not edges: raise ValueError('没有支持的壳或线单元；实体网格预览尚未接入')
            return {'positions':[v for p in points for v in p],'triangles':tris,'edges':edges,'node_count':len(points),'element_count':len(model.elements),'units':'单位待确认','warnings':warnings}
        import meshio
        m=meshio.read(str(path)); triangles=[]
        for block in m.cells:
            if block.type=='triangle': triangles.extend(block.data.flatten().tolist())
            elif block.type=='quad':
                for a,b,c,d in block.data.tolist(): triangles.extend([a,b,c,a,c,d])
        if not triangles: raise ValueError('文件中没有支持的三角形或四边形表面')
        return {'positions':m.points.flatten().tolist(),'triangles':triangles,'edges':[],'node_count':len(m.points),'element_count':len(triangles)//3,'units':'单位待确认','warnings':['表面预览，不代表有限元模型或求解结果。']}
    except Exception as exc: raise HTTPException(422,'模型解析失败：'+str(exc)[:350])
@app.get('/api/backup')
def backup():
    out=ROOT/('backup-'+str(uuid.uuid4())+'.zip')
    with LOCK,connect() as source:
        temp=ROOT/'backup-snapshot.sqlite3'
        with closing(sqlite3.connect(temp)) as dest: source.backup(dest)
        with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
            z.write(temp,'knowledge.sqlite3')
            for f in (ROOT/'assets').rglob('*') if (ROOT/'assets').exists() else []:
                if f.is_file():z.write(f,f.relative_to(ROOT).as_posix())
            z.writestr('manifest.json',encoded({'schema':'zhiheng-backup/1','created':now()}))
        temp.unlink()
    return FileResponse(out,media_type='application/zip',filename='zhiheng-backup.zip',background=BackgroundTask(out.unlink,missing_ok=True))
SEMANTIC_BUILD_LOCK=threading.Lock()
@app.get('/api/semantica/consistency')
def semantic_consistency():
    from . import derived_graph
    with connect() as c:rev,nodes,edges=derived_graph.read_source(c,record)
    result=derived_graph.state(ROOT,rev,nodes,edges)
    if SEMANTIC_BUILD_LOCK.locked():result={**result,'status':'building'}
    return result

@app.post('/api/semantica/rebuild')
def semantica_rebuild():
    from . import derived_graph
    if not SEMANTIC_BUILD_LOCK.acquire(False):raise HTTPException(409,'正在构建')
    try:
        runtime=Path(sys.executable).parent/'semantic-runtime' if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[2]/'semantic-dist/semantic-worker'
        worker=runtime/'semantic-worker.exe'
        if not worker.exists():raise HTTPException(503,'Semantica 运行组件未安装')
        with connect() as c:rev,nodes,edges=derived_graph.read_source(c,record)
        manifest=derived_graph.build(ROOT,worker,rev,nodes,edges)
        derived_graph.publish(ROOT,manifest)
        return semantic_consistency_after_build()
    except (RuntimeError,ValueError,KeyError,subprocess.TimeoutExpired) as exc:
        (ROOT/'graph-build-error.json').write_text(encoded({'message':str(exc),'time':now()}),'utf-8')
        raise HTTPException(503,str(exc))
    finally:SEMANTIC_BUILD_LOCK.release()

def semantic_consistency_after_build():
    from . import derived_graph
    with connect() as c:rev,nodes,edges=derived_graph.read_source(c,record)
    return derived_graph.state(ROOT,rev,nodes,edges)

@app.post('/api/restore')
async def restore(file:UploadFile=File(...)):
    raw=await file.read(300*1024*1024+1)
    if len(raw)>300*1024*1024: raise HTTPException(413,'备份超过300 MB，请使用离线恢复流程')
    try:
        z=zipfile.ZipFile(io.BytesIO(raw))
        names=z.namelist()
        if len(names)!=len(set(names)) or 'knowledge.sqlite3' not in names or 'manifest.json' not in names: raise ValueError('备份清单不完整或含重复项')
        if sum(i.file_size for i in z.infolist())>600*1024*1024: raise ValueError('解压后超过600 MB限制')
        for n in names:
            if n not in ('knowledge.sqlite3','manifest.json') and not re.fullmatch(r'assets/(?:[\w\u3400-\u9fff-]+/)?[a-f0-9]{64}\.[a-z0-9]+',n): raise ValueError('不允许的备份路径')
        if json.loads(z.read('manifest.json')).get('schema')!='zhiheng-backup/1': raise ValueError('备份格式不匹配')
        target=ROOT.parent/'restored-spaces'/str(uuid.uuid4());target.mkdir(parents=True)
        z.extractall(target)
        with closing(sqlite3.connect(target/'knowledge.sqlite3')) as c:
            if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise ValueError('数据库完整性检查失败')
            for path,sha in c.execute('SELECT path,sha256 FROM files'):
                p=(target/path).resolve()
                if not p.is_relative_to(target/'assets') or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=sha: raise ValueError('原件路径或校验值不匹配')
        return {'status':'verified','path':str(target),'active_space_changed':False}
    except (ValueError,zipfile.BadZipFile,KeyError,sqlite3.Error) as exc: raise HTTPException(422,'恢复校验失败：'+str(exc))
app.mount('/static',StaticFiles(directory=STATIC),name='static')
@app.get('/')
def index(): return FileResponse(STATIC/'index.html')
