"""Read real delivery state, rebuild derived graph and resume the local index."""
import json,time,urllib.request,urllib.parse,hashlib
from pathlib import Path
root=Path(__file__).resolve().parents[1];target=root/'release/知衡仿真知识库';data=target/'data'
expected=int((root/'evidence/final-app.pid').read_text())
for _ in range(120):
 runtime=json.loads((data/'runtime.json').read_text('utf-8'))
 if runtime['pid']==expected:break
 time.sleep(.5)
assert runtime['pid']==expected,runtime
def api(path,body=None):
 req=urllib.request.Request(runtime['url']+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=180) as response:return json.load(response)
health=api('/api/health');assert Path(health['data_root'])==data and health['total']==6978
index=api('/api/embedding/build',{});graph=api('/api/semantica/rebuild',{});assert graph['status']=='passed' and graph['nodes']==6978
queries=[]
for query in ('什么是飞机机身','机身框静强度仿真','飞机承力结构在载荷作用下的变形'):
 started=time.time();result=api('/api/search?'+urllib.parse.urlencode({'q':query,'limit':5}))
 queries.append({'query':query,'seconds':round(time.time()-started,3),'total':result['total'],'graph':result['graph'],'top':[{'id':r['id'],'title':r['title'],'channels':r['retrieval_channels'],'related':len(r.get('related',[])),'evidence':r['evidence']} for r in result['items']]})
 assert result['items'],query
assert queries[0]['top'][0]['title']=='机身',queries[0]
current=api('/api/embedding/status');before=json.loads((root/'evidence/index-before-handoff.json').read_text('utf-8-sig'))
assert current['indexed']>before['indexed'] and current['error']=='',current
report={'status':'passed','runtime':runtime,'exe_sha256':hashlib.sha256((target/'知衡仿真知识库.exe').read_bytes()).hexdigest(),'counts':health['counts'],'graph':graph,'index':current,'queries':queries,'all_vectors_complete':current['status']=='ready','engineering_validation':False}
(root/'evidence/hybrid-delivery.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'status':'passed','runtime':runtime,'index':current,'queries':[{'q':r['query'],'top':r['top'][0]['title'],'seconds':r['seconds']} for r in queries]},ensure_ascii=False))
