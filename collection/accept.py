"""Live EXE acceptance: hashes, retrieval, citations, negative query and mesh parsing."""
import json,sqlite3,hashlib,time
from pathlib import Path
import httpx
BASE=Path(__file__).parent;APP=BASE.parent/'desktop-framework/release/知衡仿真知识库';DATA=APP/'data'
runtime=json.loads((DATA/'runtime.json').read_text('utf-8'))
assert Path(runtime['exe']).resolve()==(APP/'知衡仿真知识库.exe').resolve(),runtime
c=httpx.Client(base_url=runtime['url'],timeout=180,trust_env=False)
checks=[]
def get(path,**params):
 r=c.get(path,params=params);r.raise_for_status();return r.json()
health=get('/api/health');stats=get('/api/collection')
assert health['total']>1000 and health['counts'].get('term',0)>=98
queries={}
for q,kind in [('什么是飞机机身','term'),('机翼是什么意思','term'),('机身框静强度仿真','case'),('机身框的静强度仿真','case'),('fuselage frame static strength',''),('wingbox','model')]:
 t=time.perf_counter();r=get('/api/search',q=q,type=kind,limit=5)
 assert r['total']>0,(q,r)
 queries[q]={'total':r['total'],'seconds':round(time.perf_counter()-t,3),'top':[{'id':x['id'],'title':x['title']} for x in r['items']]};checks.append(q)
assert queries['什么是飞机机身']['top'][0]['title']=='机身'
assert queries['机翼是什么意思']['top'][0]['title']=='机翼'
assert get('/api/search',q='zxq完全不存在的部件84729')['total']==0;checks.append('negative query')
citations=get('/api/search',q='fuselage',type='document',limit=20)
refs=[e for r in citations['items'] for e in r['evidence']]
assert refs,'no page evidence'
r=c.get(refs[0]['url'].split('#')[0]);r.raise_for_status();assert r.content;checks.append('source original accessible')
card=get('/api/answer',q='什么是飞机机身');assert card['answers'][0]['text'];checks.append('citable definition')
export=c.get('/api/datasets/candidates',params={'kind':'cards'});export.raise_for_status()
assert all(json.loads(l)['training_ready'] is False for l in export.text.splitlines() if l);checks.append('training gate')
db=sqlite3.connect(DATA/'knowledge.sqlite3');db.row_factory=sqlite3.Row
assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok';checks.append('sqlite integrity')
hash_errors=[];hash_count=0;total_bytes=0
for f in db.execute('SELECT DISTINCT path,sha256,size FROM files'):
 p=(DATA/f['path']).resolve();assert p.is_relative_to(DATA/'assets')
 h=hashlib.sha256()
 with p.open('rb') as stream:
  for b in iter(lambda:stream.read(1024*1024),b''):h.update(b)
 if h.hexdigest()!=f['sha256'] or p.stat().st_size!=f['size']:hash_errors.append(str(p))
 hash_count+=1;total_bytes+=f['size']
assert not hash_errors,hash_errors;checks.append('all managed hashes')
wing=db.execute("SELECT * FROM files WHERE name='wingbox.bdf' LIMIT 1").fetchone()
assert wing
mesh=get('/api/model-assets/'+wing['id']+'/mesh');assert mesh['node_count']>100 and len(mesh['triangles'])>100;checks.append('real wingbox mesh parser')
frame=db.execute("SELECT * FROM files WHERE name='frame.STEP' LIMIT 1").fetchone();assert frame
result={'runtime':runtime,'exe_sha256':hashlib.sha256((APP/'知衡仿真知识库.exe').read_bytes()).hexdigest(),'health':health,'collection':stats,'queries':queries,'checks':checks,'managed_files_verified':hash_count,'managed_bytes':total_bytes,'hash_errors':hash_errors,'wingbox':dict(wing),'frame':dict(frame),'mesh':{k:mesh[k] for k in ['node_count','element_count','units']},'engineering_approval':False,'visual_acceptance':'separate browser check'}
(BASE/'acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'checks':len(checks),'files':hash_count,'counts':health['counts'],'queries':queries},ensure_ascii=False))
