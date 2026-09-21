"""Local BGE-M3 encoder and resumable derived index. No remote inference."""
import argparse, hashlib, json, os, sqlite3, threading, time
from pathlib import Path
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import numpy as np

ENCODING = {'model':'BAAI/bge-m3','revision':'5617a9f61b028005a4858fdac845db406aefb181','pooling':'cls','normalize':True,'max_length':512,'dimension':1024}

def digest(text): return hashlib.sha256(text.encode('utf-8')).hexdigest()

class Engine:
 def __init__(self, root, model_path, index_name="vectors.sqlite3", encoding=None):
  self.root=Path(root).resolve();self.model_path=Path(model_path);self.path=self.root/index_name;self.encoding=encoding or ENCODING
  self.lock=threading.RLock();self.model=None;self.cache=None;self.building=False;self.error='';self.processed=0
  self.signature=json.dumps(self.encoding,sort_keys=True)
  with self.db() as c:
   c.executescript('CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT); CREATE TABLE IF NOT EXISTS vectors(key TEXT PRIMARY KEY,object_id TEXT,object_hash TEXT,text_hash TEXT,file_id TEXT,page INTEGER,text TEXT,vector BLOB);')
   old=c.execute("SELECT value FROM meta WHERE key='encoding'").fetchone()
   if old and old[0]!=self.signature: raise ValueError('模型或编码配置变化：请使用新的向量索引数据空间')
   c.execute("INSERT OR IGNORE INTO meta VALUES('encoding',?)",(self.signature,))
 @contextmanager
 def db(self):
  c=sqlite3.connect(self.path,timeout=30)
  try:
   with c:yield c
  finally:c.close()
 @contextmanager
 def source(self):
  c=sqlite3.connect((self.root/'knowledge.sqlite3').as_uri()+'?mode=ro',uri=True,timeout=30);c.row_factory=sqlite3.Row
  try:yield c
  finally:c.close()
 def encode(self,texts):
  with self.lock:
   if self.model is None:
    import torch
    from transformers import AutoTokenizer, AutoModel
    manifest=json.loads((self.model_path/'revision.json').read_text())
    if any(manifest[k]!=ENCODING[k] for k in ('model','revision')): raise ValueError('模型版本与索引不一致')
    self.torch=torch;self.device='cuda' if torch.cuda.is_available() else 'cpu'
    torch.set_num_threads(4)
    self.tokenizer=AutoTokenizer.from_pretrained(self.model_path,local_files_only=True)
    self.model=AutoModel.from_pretrained(self.model_path,local_files_only=True).to(self.device).eval()
    if self.device=='cuda':self.model.half()
   if self.encoding.get('chunk_rule') and any(len(self.tokenizer(t,truncation=False)['input_ids'])>512 for t in texts):raise ValueError('编码文本超过512 tokens，禁止静默截断')
   data=self.tokenizer(texts,padding=True,truncation=not bool(self.encoding.get('chunk_rule')),max_length=ENCODING['max_length'] if not self.encoding.get('chunk_rule') else None,return_tensors='pt').to(self.device)
   with self.torch.inference_mode():
    vec=self.model(**data).last_hidden_state[:,0].float()
    vec=self.torch.nn.functional.normalize(vec,p=2,dim=1)
   return vec.cpu().numpy()
 def status(self):
  with self.db() as c:
   count=c.execute('SELECT COUNT(*) FROM vectors').fetchone()[0]
   objects=c.execute("SELECT COUNT(*) FROM vectors WHERE key LIKE 'o:%'").fetchone()[0]
   built=c.execute("SELECT value FROM meta WHERE key='revision'").fetchone()
  with self.source() as c:
   total=c.execute('SELECT COUNT(*) FROM objects').fetchone()[0]+c.execute('SELECT COUNT(*) FROM chunks').fetchone()[0]
   revision=c.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0]
  return {'status':'building' if self.building else 'failed' if self.error else 'not_built' if not count else 'partial' if count<total or not built else 'stale' if built[0]!=revision else 'ready','indexed':count,'objects':objects,'total':total,'coverage':round(count/max(total,1),4),'error':self.error,'encoding':ENCODING,'device':getattr(self,'device','not_loaded'),'truncation':'每个原有片段最多512 token；原文保留完整'}
 def rows(self):
  with self.source() as c:
   for r in c.execute('SELECT * FROM objects ORDER BY CASE WHEN type IN (\'term\',\'material\',\'condition\',\'mesh\',\'case\') THEN 0 ELSE 1 END,id'):
    text=r['title']+'\n'+r['payload']
    yield ('o:'+r['id'],r['id'],r['hash'],digest(text),'',0,text)
   for r in c.execute('SELECT c.*,o.hash object_hash FROM chunks c JOIN objects o ON o.id=c.object_id ORDER BY c.id'):
    yield ('c:'+str(r['id']),r['object_id'],r['object_hash'],digest(r['text']),r['file_id'],r['page'],r['text'])
 def build(self):
  self.error=''
  try:
   with self.source() as c:revision=c.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0]
   with self.db() as c:known={r[0]:(r[1],r[2]) for r in c.execute('SELECT key,object_hash,text_hash FROM vectors')}
   batch=[];seen=set()
   def flush():
    vectors=self.encode([r[-1] for r in batch])
    with self.db() as c:
     c.executemany('INSERT OR REPLACE INTO vectors VALUES(?,?,?,?,?,?,?,?)',[(*r,v.astype('<f2').tobytes()) for r,v in zip(batch,vectors)])
    with self.lock:self.cache=None
    self.processed+=len(batch);batch.clear()
   for row in self.rows():
    seen.add(row[0])
    if known.get(row[0])==(row[2],row[3]):continue
    batch.append(row)
    if len(batch)>=24:flush()
   if batch:flush()
   with self.db() as c:
    c.executemany('DELETE FROM vectors WHERE key=?',[(key,) for key in known.keys()-seen])
    c.execute("INSERT OR REPLACE INTO meta VALUES('revision',?)",(revision,))
   with self.lock:self.cache=None
  except Exception as exc:self.error=str(exc)
  finally:self.building=False
 def search(self,q,eligible,limit=100):
  vector=self.encode([q])[0]
  with self.lock:
   if self.cache is None:
    with self.db() as c:rows=c.execute('SELECT key,object_id,object_hash,text_hash,vector FROM vectors').fetchall()
    meta=[r[:4] for r in rows]
    matrix=np.stack([np.frombuffer(r[4],dtype='<f2') for r in rows]) if rows else np.empty((0,1024),dtype=np.float16)
    self.cache=(meta,matrix)
   meta,matrix=self.cache
  indices=np.array([i for i,r in enumerate(meta) if eligible.get(r[1])==r[2]],dtype=np.int64)
  if not len(indices):return []
  best=[]
  for start in range(0,len(indices),8192):
   ix=indices[start:start+8192];scores=matrix[ix].astype(np.float32)@vector
   top=np.argsort(scores)[-limit:]
   best.extend((float(scores[j]),int(ix[j])) for j in top if scores[j]>=.45)
  best=sorted(best,reverse=True)[:limit]
  results=[]
  with self.db() as c, self.source() as source:
   for score,i in best:
    key,oid,oh,th=meta[i]
    if key.startswith('c:'):
     current=source.execute('SELECT text,file_id,page,object_id FROM chunks WHERE id=?',(int(key[2:]),)).fetchone()
     if not current or digest(current['text'])!=th or current['object_id']!=oid:continue
    row=c.execute('SELECT file_id,page,text FROM vectors WHERE key=?',(key,)).fetchone()
    if row:results.append({'key':key,'object_id':oid,'object_hash':oh,'score':score,'file_id':row[0],'page':row[1],'text':row[2][:1800]})
  return results

def main():
 p=argparse.ArgumentParser();p.add_argument('--data',required=True);p.add_argument('--model',required=True);p.add_argument('--parent',type=int);p.add_argument('--token',default='');args=p.parse_args()
 if args.parent and os.name=='nt':
  def parent_watch():
   import ctypes
   kernel=ctypes.WinDLL('kernel32',use_last_error=True)
   kernel.OpenProcess.restype=ctypes.c_void_p
   kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_uint32]
   kernel.CloseHandle.argtypes=[ctypes.c_void_p]
   handle=kernel.OpenProcess(0x100000,False,args.parent)
   if handle:
    kernel.WaitForSingleObject(handle,0xffffffff);kernel.CloseHandle(handle)
   os._exit(0)
  threading.Thread(target=parent_watch,daemon=True).start()
 engine=Engine(args.data,args.model)
 from index_v2 import make_engine
 from index_generations import Generations
 generations=Generations(Path(args.data),args.model,make_engine(Engine,ENCODING))
 def active():
  manifest=Path(args.data)/'active-index.json'
  if manifest.exists() and json.loads(manifest.read_text('utf-8')).get('version')==2:return generations.active()
  return engine
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*args):pass
  def do_POST(self):
   try:
    if self.headers.get('Origin'):raise ValueError('只接受本机程序调用')
    if args.token and self.headers.get('Authorization')!='Bearer '+args.token:raise ValueError('Invalid worker credential')
    body=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))) or '{}')
    if self.path=='/status':result=active().status()
    elif self.path=='/v2/status':result=generations.candidate().status()
    elif self.path=='/v2/build':
     if engine.building:raise ValueError('旧索引正在构建；请等待完成后启动新索引')
     # Serialize choosing a build target with publication: the target must not
     # become active between prepare() and setting its building flag.
     with generations.lock:
      v2=generations.prepare()
      with v2.lock:
       if not v2.building:
        v2.stop_requested=False;v2.pilot_limit=body.get('pilot_limit');v2.building=True;threading.Thread(target=v2.build,daemon=True).start()
     result=v2.status()
    elif self.path=='/v2/stop':
     v2=generations.candidate();v2.stop_requested=True;result=v2.status()
    elif self.path=='/v2/activate':
     result=generations.activate()
    elif self.path=='/build':
     with engine.lock:
      if not engine.building:
       engine.building=True;threading.Thread(target=engine.build,daemon=True).start()
     result=engine.status()
    elif self.path=='/search':
     v2=generations.candidate();v2.foreground+=1
     try:result=active().search(body['query'],body['eligible'])
     finally:v2.foreground-=1
    else:raise ValueError('Unknown endpoint')
    data=json.dumps(result,ensure_ascii=False).encode();self.send_response(200)
   except Exception as exc:data=json.dumps({'error':str(exc)}).encode();self.send_response(500)
   self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
 server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
 (Path(args.data)/'embedding-runtime.json').write_text(json.dumps({'pid':os.getpid(),'token':args.token,'url':'http://127.0.0.1:'+str(server.server_port)}),encoding='utf-8')
 server.serve_forever()
if __name__=='__main__':main()

