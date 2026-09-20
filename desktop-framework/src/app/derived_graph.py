"""Versioned Semantica artifacts published through a single atomic manifest."""
import hashlib,json,os,subprocess,uuid
from datetime import datetime,timezone

def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()

def normalize(nodes,edges):
    return {'nodes':sorted([{'id':n['id'],'type':n['type'],'title':n['title'],'version':n['version'],'hash':n['hash']} for n in nodes],key=lambda n:n['id']), 'edges':sorted([{k:e[k] for k in ('id','source','target','type','evidence','source_version','target_version')} for e in edges],key=lambda e:e['id'])}

def read_source(c,record):
    c.execute('BEGIN')
    revision=int(c.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0])
    nodes=[record(r) for r in c.execute('SELECT * FROM objects')]
    edges=[dict(r) for r in c.execute('SELECT * FROM relations')]
    return revision,nodes,edges

def compare(expected,actual):
    result={}
    for kind in ('nodes','edges'):
        a={r['id']:r for r in expected.get(kind,[])};b={r['id']:r for r in actual.get(kind,[])}
        result[kind]={'missing':sorted(a.keys()-b.keys()),'extra':sorted(b.keys()-a.keys()),'changed':sorted(k for k in a.keys()&b.keys() if a[k]!=b[k])}
    ids={n['id'] for n in actual.get('nodes',[])}
    result['dangling']=[e['id'] for e in actual.get('edges',[]) if e['source'] not in ids or e['target'] not in ids]
    result['equal']=not result['dangling'] and not any(v for kind in ('nodes','edges') for v in result[kind].values())
    return result

def state(root,revision,nodes,edges):
    manifest=root/'graph-manifest.json'
    if not manifest.exists():return {'status':'not_built','message':'现有旧派生图缺少内容校验 manifest，需要重建','backend':'authority'}
    try:
        m=json.loads(manifest.read_text('utf-8'));p=root/m['artifact']
        if (root/'graph-build-error.json').exists():return {**m,'status':'failed','backend':'authority','last_build_error':json.loads((root/'graph-build-error.json').read_text('utf-8'))}
        if p.parent!=root:raise ValueError('非法产物路径')
        artifact=json.loads(p.read_text('utf-8'));actual=artifact['canonical']
        if digest(actual)!=m['content_hash']:raise ValueError('派生产物内容哈希不符')
        diff=compare(normalize(nodes,edges),actual)
        return {**m,'status':'consistent' if diff['equal'] and revision==m['revision'] else 'stale','diff':diff,'backend':'semantica' if diff['equal'] and revision==m['revision'] else 'authority'}
    except (OSError,ValueError,KeyError) as exc:return {'status':'failed','message':str(exc),'backend':'authority'}

def build(root,worker,revision,nodes,edges):
    token=uuid.uuid4().hex;source=root/('graph-input-'+token+'.json');output=root/('graph-artifact-'+token+'.json')
    source.write_text(canonical({'nodes':nodes,'edges':edges}),'utf-8')
    try:
        result=subprocess.run([str(worker),str(source),str(output)],capture_output=True,timeout=120,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        (root/'semantica-worker.log').write_bytes(result.stdout+b'\n'+result.stderr)
        if result.returncode:raise RuntimeError('Semantica 构建失败，上一份产物保留')
        artifact=json.loads(output.read_text('utf-8'));expected=normalize(nodes,edges)
        diff=compare(expected,artifact['canonical'])
        if not diff['equal'] or digest(expected)!=digest(artifact['canonical']):raise RuntimeError('派生图字段校验失败')
        manifest={'schema':'zhiheng-derived/2','build_version':'2','revision':revision,'semantica_version':artifact['semantica_version'],'time':datetime.now(timezone.utc).isoformat(),'nodes':len(nodes),'edges':len(edges),'content_hash':digest(expected),'artifact':output.name}
        return manifest
    finally:source.unlink(missing_ok=True)

def publish(root,manifest):
    temp=root/('manifest-'+uuid.uuid4().hex+'.tmp');temp.write_text(canonical(manifest),'utf-8');os.replace(temp,root/'graph-manifest.json');(root/'graph-build-error.json').unlink(missing_ok=True)
