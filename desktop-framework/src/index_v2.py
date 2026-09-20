"""Isolated resumable token-complete index. Old vectors are never overwritten."""
import json,time,sqlite3,hashlib,os
from token_chunks import split,RULE

def make_engine(base_class,encoding):
 class TokenEngine(base_class):
  def __init__(self,root,model):
   super().__init__(root,model,'vectors-v2.sqlite3',{**encoding,'chunk_rule':RULE})
   with self.db() as c:
    c.executescript('CREATE TABLE IF NOT EXISTS units(key TEXT PRIMARY KEY,parent TEXT,object_id TEXT,file_id TEXT,file_hash TEXT,page INTEGER,start INTEGER,end INTEGER,text TEXT,tokens INTEGER,overlap_chars INTEGER,content_hash TEXT,parent_hash TEXT,rule TEXT,object_hash TEXT);')
   self.tokenizer_hash=hashlib.sha256((self.model_path/'tokenizer.json').read_bytes()).hexdigest()
   with self.db() as c:
    old=c.execute("SELECT value FROM meta WHERE key='tokenizer_hash'").fetchone()
    if old and old[0]!=self.tokenizer_hash:raise ValueError('Tokenizer内容变化，禁止混合已有索引')
    c.execute("INSERT OR IGNORE INTO meta VALUES('tokenizer_hash',?)",(self.tokenizer_hash,))
   self.pending_units={} 
   self.stop_requested=False;self.foreground=0;self.parents_processed=0;self.pilot_limit=None
  def splitter(self):
   if not hasattr(self,'split_tokenizer'):
    from transformers import AutoTokenizer
    self.split_tokenizer=AutoTokenizer.from_pretrained(self.model_path,local_files_only=True)
   return self.split_tokenizer
  def rows(self):
   tokenizer=self.splitter();count=0
   with self.source() as source:
    source.execute('BEGIN')
    self.parents_total=source.execute('SELECT COUNT(*) FROM objects').fetchone()[0]+source.execute('SELECT COUNT(*) FROM chunks').fetchone()[0]
    self.source_revision=source.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0]
    queries=[("SELECT 'o:'||id parent,id object_id,hash object_hash,'' file_id,0 page,title||char(10)||payload text,'' file_hash FROM objects ORDER BY id",), ("SELECT 'c:'||c.id parent,c.object_id,o.hash object_hash,c.file_id,c.page,c.text,f.sha256 file_hash FROM chunks c JOIN objects o ON o.id=c.object_id LEFT JOIN files f ON f.id=c.file_id ORDER BY c.id",)]
    for (sql,) in queries:
     for row in source.execute(sql):
      if self.stop_requested:return
      self.parents_processed+=1
      parent_hash=hashlib.sha256(row['text'].encode()).hexdigest()
      for unit in split(row['text'],tokenizer):
       key=f"v2:{row['parent']}:{unit['start']}:{unit['end']}:{unit['content_hash'][:16]}"
       self.pending_units[key]=(key,row['parent'],row['object_id'],row['file_id'],row['file_hash'],row['page'],unit['start'],unit['end'],unit['text'],unit['tokens'],unit['overlap_chars'],unit['content_hash'],parent_hash,RULE,row['object_hash'])
       yield (key,row['object_id'],row['object_hash'],unit['content_hash'],row['file_id'],row['page'],unit['text'])
       count+=1
       if self.pilot_limit and count>=self.pilot_limit:return
  def build(self):
   self.error='';seen=set();self.parents_processed=0
   try:
    with self.db() as c:known={r[0]:(r[1],r[2],r[3],r[4]) for r in c.execute('SELECT v.key,v.object_hash,v.text_hash,u.file_hash,u.parent_hash FROM vectors v LEFT JOIN units u ON u.key=v.key')}
    batch=[]
    def flush():
     while self.foreground:time.sleep(.05)
     vec=self.encode([r[-1] for r in batch])
     with self.db() as c:
      c.executemany('INSERT OR REPLACE INTO units VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',[self.pending_units.pop(r[0]) for r in batch])
      c.executemany('INSERT OR REPLACE INTO vectors VALUES(?,?,?,?,?,?,?,?)',[(*r,v.astype('<f2').tobytes()) for r,v in zip(batch,vec)])
      c.execute("INSERT OR REPLACE INTO meta VALUES('progress',?)",(str(len(seen)),))
      c.execute("INSERT OR REPLACE INTO meta VALUES('parents_progress',?)",(json.dumps({'processed':self.parents_processed,'total':self.parents_total}),))
     self.processed+=len(batch);batch.clear();time.sleep(.03)
    for r in self.rows():
     seen.add(r[0])
     if known.get(r[0])==(r[2],r[3],self.pending_units[r[0]][4],self.pending_units[r[0]][12]):self.pending_units.pop(r[0],None);continue
     batch.append(r)
     if len(batch)>=24:flush()
    if batch:flush()
    with self.source() as c:current=c.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0]
    with self.db() as c:
     if not self.stop_requested and not self.pilot_limit and current==self.source_revision:
      c.executemany('DELETE FROM vectors WHERE key=?',[(k,) for k in known.keys()-seen])
      c.execute('DELETE FROM units WHERE key NOT IN (SELECT key FROM vectors)')
      count=c.execute('SELECT COUNT(*) FROM vectors').fetchone()[0]
      paired=c.execute('SELECT COUNT(*) FROM vectors v JOIN units u ON u.key=v.key WHERE u.tokens<=512 AND length(v.vector)=2048 AND u.content_hash=v.text_hash AND u.object_hash=v.object_hash').fetchone()[0]
      if count!=len(seen) or paired!=count:raise ValueError('编码单元、向量维度或内容哈希校验失败，禁止切换')
      c.execute("INSERT OR REPLACE INTO meta VALUES('revision',?)",(current,))
      c.execute("INSERT OR REPLACE INTO meta VALUES('complete','1')")
     else:c.execute("INSERT OR REPLACE INTO meta VALUES('complete','0')")
   except Exception as exc:self.error=str(exc)
   finally:self.building=False;self.cache=None
  def status(self):
   with self.db() as c:
    count=c.execute('SELECT COUNT(*) FROM vectors').fetchone()[0];complete=c.execute("SELECT value FROM meta WHERE key='complete'").fetchone();revision=c.execute("SELECT value FROM meta WHERE key='revision'").fetchone()
   with self.source() as c:current=c.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0]
   with self.db() as c:progress=c.execute("SELECT value FROM meta WHERE key='parents_progress'").fetchone()
   ready=bool(complete and complete[0]=='1' and revision and revision[0]==current)
   return {'status':'building' if self.building else 'failed' if self.error else 'ready' if ready else 'partial' if count else 'not_built','parents_progress':json.loads(progress[0]) if progress else None,'indexed':count,'total':count if ready else None,'complete':ready,'error':self.error,'encoding':self.encoding,'tokenizer_hash':self.tokenizer_hash,'revision':revision[0] if revision else None,'truncation':'禁止静默截断；完整正文按实际 tokenizer 分片；字符位置相对父正文块'}
  def search(self,q,eligible,limit=100):
   self.foreground+=1
   try:
    # Query length is rejected explicitly instead of silently truncated.
    result=super().search(q,eligible,limit);valid=[]
    with self.db() as db,self.source() as source:
     for hit in result:
      unit=db.execute('SELECT parent,parent_hash,start,end,tokens FROM units WHERE key=?',(hit['key'],)).fetchone()
      if not unit:continue
      if unit[0].startswith('c:'):
       row=source.execute('SELECT text FROM chunks WHERE id=?',(int(unit[0][2:]),)).fetchone()
       if not row or hashlib.sha256(row[0].encode()).hexdigest()!=unit[1]:continue
      hit.update({'unit_id':hit['key'],'parent_id':unit[0],'start':unit[2],'end':unit[3],'tokens':unit[4],'index_version':RULE});valid.append(hit)
    return valid
   finally:self.foreground-=1
 return TokenEngine
