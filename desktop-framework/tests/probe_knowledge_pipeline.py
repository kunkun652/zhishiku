"""Real-component acceptance probe in a NEW isolated data root, never the business DB.

Requires the full checkout and configured actual Semantica/BGE-M3/Ollama runtimes.
No fake engines. Nonzero exit on missing dependencies, model, citations, or readiness.
Run from repo root: python desktop-framework/tests/probe_knowledge_pipeline.py --out <NEW-DIRECTORY>
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',required=True)
    parser.add_argument('--timeout',type=int,default=600)
    args=parser.parse_args()
    root=Path(args.out).resolve()
    if root.exists(): raise SystemExit('--out must not exist; refusing to use existing data')
    root.mkdir(parents=True)
    os.environ['ZH_DATA_ROOT']=str(root)
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
    report={'schema':'knowledge-real-probe/1','passed':False,'data_root':str(root),'fixture_engines':False}
    backend=None
    try:
        from fastapi.testclient import TestClient
        from app.pipeline_app import app, backend
        with TestClient(app) as client:
            def get(path):
                r=client.get(path); r.raise_for_status(); return r.json()
            def post(path,data):
                r=client.post(path,json=data); r.raise_for_status(); return r.json()
            state=get('/api/pipeline/status?probe=true'); report['components']=state['components']
            assert state['components']['semantica']['status']=='ready', 'actual Semantica unavailable'
            assert state['components']['agent']['status']=='ready', 'actual local model unavailable'
            content='机翼采用 CTETRA 单元，机翼的载荷为5000 N。此文本为隔离验收合成样例，不是实际工程资料。'
            r=client.post('/api/pipeline/upload',files={'file':('acceptance.txt',content.encode(),'text/plain')})
            r.raise_for_status(); file=r.json()
            job=post('/api/pipeline/jobs',{'file_id':file['id'],'mode':'regex'})
            deadline=time.monotonic()+args.timeout
            while job['state'] in ('queued','parsing','extracting') and time.monotonic()<deadline:
                time.sleep(.5); job=get('/api/pipeline/jobs/'+job['id'])
            report['job']=job
            assert job['state']=='awaiting_review', 'extraction failed or timed out'
            candidates=get('/api/pipeline/candidates?job_id='+job['id'])['items']
            assert candidates and any(c['payload'].get('label')=='ELEMENT' for c in candidates)
            post('/api/pipeline/review',{'ids':[c['id'] for c in candidates],'action':'accept','reviewer':'isolated-real-probe','note':'合成样例原文级验收，不是工程复核'})
            post('/api/pipeline/indexes/refresh',{})
            index=get('/api/pipeline/indexes'); deadline=time.monotonic()+args.timeout
            while index['status'] in ('queued','building_graph','starting_vectors','vectors_building') and time.monotonic()<deadline:
                time.sleep(1); index=get('/api/pipeline/indexes')
            report['indexes_before_activation']=index
            assert index['status']=='activation_required', 'actual graph/vector build incomplete'
            activated=post('/api/pipeline/indexes/activate',{}); assert activated['status']=='ready'
            report['indexes']=activated
            answer=post('/api/agent/ask',{'query':'CTETRA','top_k':10}); report['answer']=answer
            assert answer['status']=='answered' and answer['claims'], 'actual model/citations failed'
            assert answer['evidence_pack']['channels']['embedding']['status']=='ready'
            assert answer['evidence_pack']['channels']['graph']['backend']=='semantica'
            assert {'keyword','semantic','graph'} <= set(answer['evidence_pack']['channels']['used'])
            report['passed']=True
    except Exception as exc:
        report['error']=str(exc)
    finally:
        if backend is not None: backend.EMBEDDINGS.close()
        (root/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
        print(json.dumps({'passed':report['passed'],'report':str(root/'result.json'),'error':report.get('error')},ensure_ascii=False))
    return 0 if report['passed'] else 1

if __name__=='__main__': raise SystemExit(main())
