"""Explicit ID references only; candidate acceptance is not engineering approval."""
import json,re,uuid,hashlib

def init(c):
    c.executescript('''CREATE TABLE IF NOT EXISTS relation_candidates(id TEXT PRIMARY KEY,source TEXT,target TEXT,type TEXT,evidence TEXT,source_version INTEGER,target_version INTEGER,status TEXT,method TEXT,relation_id TEXT);
    CREATE TABLE IF NOT EXISTS relation_events(id TEXT PRIMARY KEY,candidate_id TEXT,action TEXT,snapshot TEXT,created TEXT);
    CREATE TABLE IF NOT EXISTS candidate_provenance(id TEXT PRIMARY KEY,metadata TEXT);
    CREATE TABLE IF NOT EXISTS relation_provenance(relation_id TEXT PRIMARY KEY,method TEXT,locator TEXT,file_hash TEXT,status TEXT);''')

def discover(c,objects,oid,sentences=True):
    byid={o['id']:o for o in objects};source=byid[oid];proposals=[];missing=[]
    mappings={'model_ids':'使用模型','task_id':'来源于','run_ids':'运行记录','card_ids':None}
    for field,relation in mappings.items():
        raw=source['data'].get(field,'')
        for target in dict.fromkeys(re.split(r'[,，;；\s]+',raw.strip())):
            if not target:continue
            if target not in byid:missing.append({'field':field,'target':target});continue
            if target==oid:continue
            other=byid[target];kind=relation or {'material':'采用材料','condition':'采用工况','mesh':'采用网格策略'}.get(other['type'],'来源于')
            if c.execute('SELECT 1 FROM relations WHERE source=? AND target=? AND type=?',(oid,target,kind)).fetchone():continue
            evidence=f"字段 {field} 明确引用对象 ID {target}"
            cid=str(uuid.uuid5(uuid.NAMESPACE_URL,f"{oid}:{source['version']}:{field}:{target}:{other['version']}"))
            c.execute('INSERT OR IGNORE INTO relation_candidates VALUES(?,?,?,?,?,?,?,?,?,?)',(cid,oid,target,kind,evidence,source['version'],other['version'],'pending','explicit-id-v1',None))
            proposals.append(cid)
    if sentences:
        targets={}
        for other in objects:
            if other['id']!=oid and 3<=len(other['title'])<=60:targets.setdefault(other['title'],[]).append(other)
        pattern=re.compile(r'(采用|使用|来源于|参考)\s*(?:材料|模型|工况)?\s*('+ '|'.join(re.escape(t) for t in sorted(targets,key=len,reverse=True))+')') if targets else None
        chunks=c.execute('SELECT * FROM chunks WHERE object_id=? ORDER BY id LIMIT 100',(oid,)).fetchall()
        for chunk in chunks:
            if pattern is None:break
            for match in pattern.finditer(chunk['text']):
                a=max(0,chunk['text'].rfind('。',0,match.start())+1);b=chunk['text'].find('。',match.end());b=len(chunk['text']) if b<0 else b+1
                quote=chunk['text'][a:b];kind={'采用':'来源于','使用':'来源于','来源于':'来源于','参考':'参考案例'}[match[1]]
                for target in targets[match[2]]:
                    kind=({'material':'采用材料','model':'使用模型','condition':'采用工况','mesh':'采用网格策略'}.get(target['type'],'来源于') if match[1] in ('采用','使用') else '参考案例' if match[1]=='参考' and target['type']=='case' else '来源于')
                    cid=str(uuid.uuid5(uuid.NAMESPACE_URL,f"sentence:{oid}:{source['version']}:{chunk['id']}:{match.start()}:{target['id']}:{target['version']}"))
                    evidence=f"原文第 {chunk['page']} 页，正文块 {chunk['id']}，字符 {a}:{b}：{quote}"
                    c.execute('INSERT OR IGNORE INTO relation_candidates VALUES(?,?,?,?,?,?,?,?,?,?)',(cid,oid,target['id'],kind,evidence,source['version'],target['version'],'pending','explicit-sentence-v1',None))
                    file=c.execute('SELECT sha256 FROM files WHERE id=?',(chunk['file_id'],)).fetchone()
                    metadata={'chunk_id':chunk['id'],'file_id':chunk['file_id'],'file_hash':file[0] if file else None,'page':chunk['page'],'start':a,'end':b,'parent_hash':hashlib.sha256(chunk['text'].encode()).hexdigest(),'quote':quote,'ambiguity':len(targets[match[2]])>1,'review_note':'明确句式候选；仍需核查否定、条件和标题歧义'}
                    c.execute('INSERT OR IGNORE INTO candidate_provenance VALUES(?,?)',(cid,json.dumps(metadata,ensure_ascii=False)));proposals.append(cid)
    return {'candidate_ids':proposals,'missing_targets':missing,'method':'显式 ID 字段及明确句式规则；最多检查前100个正文块；未启用大模型抽取','engineering_approval':False}

def audit(c,cid,action,now):
    row=c.execute('SELECT * FROM relation_candidates WHERE id=?',(cid,)).fetchone()
    if not row:raise ValueError('候选不存在')
    r=dict(row)
    if action not in ('accept','reject','undo'):raise ValueError('只允许 accept / reject / undo')
    if action=='accept':
        provenance=c.execute('SELECT metadata FROM candidate_provenance WHERE id=?',(cid,)).fetchone()
        metadata=json.loads(provenance[0]) if provenance else {}
        if metadata:
            chunk=c.execute('SELECT text FROM chunks WHERE id=?',(metadata['chunk_id'],)).fetchone()
            if not chunk or hashlib.sha256(chunk[0].encode()).hexdigest()!=metadata['parent_hash']:raise ValueError('候选原文已改变，请重新寻找关联')
        for key in ('source','target'):
            node=c.execute('SELECT version FROM objects WHERE id=?',(r[key],)).fetchone()
            if not node or node[0]!=r[key+'_version']:raise ValueError('候选端点已更新，请重新寻找关联')
        if r['status']!='pending':raise ValueError('只能接受待处理候选')
        existing=c.execute('SELECT id FROM relations WHERE source=? AND target=? AND type=? AND evidence=?',(r['source'],r['target'],r['type'],r['evidence'])).fetchone()
        if existing:raise ValueError('该依据关系已登记')
        rid=str(uuid.uuid4())
        c.execute('INSERT INTO relations VALUES(?,?,?,?,?,?,?)',(rid,r['source'],r['target'],r['type'],r['evidence'],r['source_version'],r['target_version']))
        c.execute('INSERT INTO relation_provenance VALUES(?,?,?,?,?)',(rid,r['method'],json.dumps(metadata,ensure_ascii=False) if metadata else r['evidence'],metadata.get('file_hash'),'registered'))
        status='accepted'
    elif action=='reject':
        if r['status']!='pending':raise ValueError('只能拒绝待处理候选')
        rid=r['relation_id'];status='rejected'
    else:
        if r['status'] not in ('accepted','rejected'):raise ValueError('没有可撤销的审核')
        rid=None;status='pending'
        if r['status']=='accepted':
            c.execute('DELETE FROM relations WHERE id=?',(r['relation_id'],))
            c.execute("UPDATE relation_provenance SET status='revoked' WHERE relation_id=?",(r['relation_id'],))
    c.execute('UPDATE relation_candidates SET status=?,relation_id=? WHERE id=?',(status,rid,cid))
    c.execute('INSERT INTO relation_events VALUES(?,?,?,?,?)',(str(uuid.uuid4()),cid,action,json.dumps(r,ensure_ascii=False),now))
    if action=='accept' or action=='undo' and r['status']=='accepted':c.execute("UPDATE meta SET value=CAST(value AS INTEGER)+1 WHERE key='revision'")
    return {'id':cid,'status':status,'relation_id':rid,'engineering_approval':False}
