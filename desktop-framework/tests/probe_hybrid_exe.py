"""Packaged EXE acceptance with real local embeddings in a synthetic data space."""
import argparse,hashlib,json,os,subprocess,time,urllib.request
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--exe',required=True);p.add_argument('--out',required=True);args=p.parse_args()
out=Path(args.out).resolve();out.mkdir(parents=True,exist_ok=True)
exe=Path(args.exe).resolve();data=out/'data'
proc=subprocess.Popen([str(exe),'--server-only'],env={**os.environ,'ZH_DATA_ROOT':str(data)},creationflags=subprocess.CREATE_NO_WINDOW)
try:
 for _ in range(240):
  if (data/'runtime.json').exists():break
  if proc.poll() is not None:raise RuntimeError('Target EXE exited')
  time.sleep(.5)
 runtime=json.loads((data/'runtime.json').read_text('utf-8'))
 def api(path,body=None):
  request=urllib.request.Request(runtime['url']+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'})
  with urllib.request.urlopen(request,timeout=180) as response:return json.load(response)
 assert api('/api/health')['total']==0
 def add(title,kind,body):return api('/api/objects',{'title':title,'type':kind,'data':body})
 target=add('Wing box deformation under loading','case',{'summary':'A linear elastic study calculates displacements of an aircraft wing box when external forces are applied.','analysis_type':'静力','source':'合成测试资料，不是工程案例'})
 model=add('测试翼盒模型','model',{'source':'合成测试夹具'})
 add('Cooking noodle soup','document',{'summary':'A recipe for boiling noodles and adding vegetables.'})
 api('/api/relations',{'source':target['id'],'target':model['id'],'type':'使用模型','evidence':'合成夹具明确关联；仅用于软件验证'})
 graph=api('/api/semantica/rebuild',{});assert graph['status']=='passed'
 api('/api/embedding/build',{})
 for _ in range(240):
  status=api('/api/embedding/status')
  if status['status']!='building':break
  time.sleep(1)
 assert status['status']=='ready',status
 query='机翼盒段在外载荷作用下的位移'
 lexical=api('/api/search?'+urllib.parse.urlencode({'q':query,'mode':'keyword'}))
 semantic=api('/api/search?'+urllib.parse.urlencode({'q':query,'mode':'semantic'}))
 hybrid=api('/api/search?'+urllib.parse.urlencode({'q':query,'mode':'hybrid'}))
 assert target['id'] not in [r['id'] for r in lexical['items']],lexical
 assert semantic['items'][0]['id']==target['id'],semantic
 assert hybrid['items'][0]['id']==target['id'],hybrid
 assert any(r['id']==model['id'] for r in hybrid['items'][0]['related']),hybrid
 evidence={'status':'passed','runtime':runtime,'exe_sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),'embedding':status,'query':query,'keyword_ids':[r['id'] for r in lexical['items']],'semantic':semantic,'hybrid':hybrid,'engineering_validation':False}
 (out/'result.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'status':'passed','result':str(out/'result.json'),'embedding':status},ensure_ascii=False),flush=True)
finally:
 proc.terminate();proc.wait(timeout=20)
