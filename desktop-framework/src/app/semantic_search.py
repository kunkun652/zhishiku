"""Optional local embedding worker and provenance-checked Semantica expansion."""
import atexit,json,os,subprocess,sys,threading,time,urllib.request,uuid
from pathlib import Path

class Embeddings:
 def __init__(self,root):
  self.root=root;self.process=None;self.url=None;self.lock=threading.Lock();atexit.register(self.close)
 def close(self):
  if self.process and self.process.poll() is None:
   self.process.terminate();self.process.wait(timeout=15)
 def command(self):
  base=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[2]
  worker=base/'embedding-runtime/embedding-worker.exe';model=base/'embedding-model'
  if worker.exists() and model.exists():return [str(worker),'--data',str(self.root),'--model',str(model)]
  if not getattr(sys,'frozen',False) and os.environ.get('ZH_EMBEDDING_PYTHON'):
   return [os.environ['ZH_EMBEDDING_PYTHON'],str(base/'src/embedding_worker.py'),'--data',str(self.root),'--model',os.environ['ZH_EMBEDDING_MODEL']]
  return None
 def call(self,path,body=None):
  with self.lock:
   if not self.process or self.process.poll() is not None:
    cmd=self.command()
    if not cmd:raise RuntimeError('本地 embedding 组件未安装')
    self.token=uuid.uuid4().hex
    cmd+=['--parent',str(os.getpid()),'--token',self.token]
    runtime=self.root/'embedding-runtime.json'
    runtime.unlink(missing_ok=True)
    with (self.root/'embedding-worker.log').open('ab') as log:
     self.process=subprocess.Popen(cmd,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    for _ in range(120):
     if runtime.exists():
      state=json.loads(runtime.read_text('utf-8'))
      if state.get('token')==self.token:self.url=state['url'];break
     if self.process.poll() is not None:raise RuntimeError('Embedding 组件启动失败，请查看本地日志')
     time.sleep(.25)
    else:raise RuntimeError('Embedding 组件启动超时')
  request=urllib.request.Request(self.url+path,data=json.dumps(body or {}).encode(),headers={'Content-Type':'application/json'})
  with urllib.request.urlopen(request,timeout=30) as response:return json.load(response)
 def status(self):
  if not self.command():return {'status':'unavailable','message':'本地 embedding 组件未安装','indexed':0}
  try:return self.call('/status')
  except Exception as exc:return {'status':'failed','message':str(exc),'indexed':0}

def allowed(item,kind,analysis,status,category,designation=''):
 data=item['data']
 if kind and item['type']!=kind or status and item['status']!=status or category and data.get('category')!=category:return False
 if not status and item['status'] in ('retired','conflict'):return False
 # Reject explicit mismatches; existing unknown analysis scopes remain pending.
 import re
 scope=data.get('analysis_type','').strip()
 if analysis and scope and analysis not in re.split(r'[,，;；/\s]+',scope):return False
 if designation and data.get('designation','').strip().casefold()!=designation.strip().casefold():return False
 return True

def combine(lexical,vector,items):
 byid={r['id']:r for r in items};merged={}
 for rank,r in enumerate(lexical):merged[r['id']]={**r,'fusion_score':1/(60+rank+1)+(0.02 if r.get('score',0)>=60 else 0),'retrieval_channels':['关键词']}
 ranked={}
 for hit in vector:
  oid=hit['object_id']
  if oid not in byid or hit['object_hash']!=byid[oid]['hash']:continue
  ranked.setdefault(oid,[]).append(hit)
 for rank,(oid,hits) in enumerate(ranked.items()):
  r=merged.setdefault(oid,{**byid[oid],'fusion_score':0,'retrieval_channels':[],'evidence':[],'applicability':'语义相关；工程适用性待确认','match_reason':'向量语义匹配'})
  r['fusion_score']+=1/(60+rank+1);r['retrieval_channels'].append('语义向量');r['semantic_score']=hits[0]['score']
  for hit in hits[:3]:
   if hit['file_id'] and not any(e.get('unit_id')==hit.get('unit_id',hit.get('key')) and e.get('unit_id') for e in r['evidence']):
    parent=str(hit.get('parent_id') or hit.get('key') or '')
    r['evidence'].append({'file_id':hit['file_id'],'page':hit['page'],'text':hit['text'],'chunk_id':int(parent[2:]) if parent.startswith('c:') and parent[2:].isdigit() else None,'unit_id':hit.get('unit_id',hit.get('key')),'parent_id':hit.get('parent_id'),'start':hit.get('start'),'end':hit.get('end'),'url':f"/api/model-assets/{hit['file_id']}/file#page={hit['page']}"})
 return sorted(merged.values(),key=lambda r:r['fusion_score'],reverse=True)

def expand(root,c,results,items,revision):
 path=root/'graph-derived.json';state=root/'semantica-status.json'
 if not path.exists() or not state.exists():return {'status':'not_built','message':'图谱尚未构建'}
 try:
  status=json.loads(state.read_text('utf-8'))
  if status.get('status')!='passed' or status.get('revision')!=revision:return {'status':'stale','message':'图谱已过期，请重建；本次不扩展旧关系'}
  graph=json.loads(path.read_text('utf-8'))
 except (ValueError,OSError):return {'status':'failed','message':'派生图读取失败'}
 current={r['id']:r for r in items};nodes={r['id']:r for r in graph['entities']}
 # Recheck current authority; a derived edge alone never establishes applicability.
 authority={(r['source'],r['target'],r['type'],r['evidence']):dict(r) for r in c.execute('SELECT * FROM relations')}
 links={}
 for edge in graph['relationships']:
  a,b=edge['source'],edge['target'];props=edge.get('properties',{});evidence=props.get('evidence','')
  row=authority.get((a,b,edge['type'],evidence))
  if not row or not evidence or props.get('stale') or a not in current or b not in current:continue
  if row['source_version']!=current[a]['version'] or row['target_version']!=current[b]['version']:continue
  if any(nodes.get(oid,{}).get('properties',{}).get('hash')!=current[oid]['hash'] for oid in (a,b)):continue
  for source,target in ((a,b),(b,a)):
   obj=current[target]
   if obj['status'] in ('retired','conflict'):continue
   links.setdefault(source,[]).append({'id':target,'title':obj['title'],'type':obj['type'],'status':obj['status'],'version':obj['version'],'relation':edge['type'],'direction':'出向' if source==a else '入向','evidence':evidence,'source':obj['data'].get('source',''),'applicability':'关联资料，不代表适用于当前任务'})
 for item in results:
  item['related']=links.get(item['id'],[])[:12]
  for related in item['related']:
   files=c.execute('SELECT id,name FROM files WHERE object_id=? LIMIT 3',(related['id'],)).fetchall()
   related['files']=[{'name':r['name'],'url':f"/api/model-assets/{r['id']}/file"} for r in files]
 return {'status':'ready','engine':status.get('engine'),'revision':revision}
