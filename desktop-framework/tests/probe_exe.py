"""Run only against the isolated EXE acceptance data space."""
import json,sys
from pathlib import Path
import httpx
root=Path(__file__).resolve().parents[1]
runtime=json.loads((root/'evidence/runtime-test-data/runtime.json').read_text('utf-8'))
c=httpx.Client(base_url=runtime['url'],timeout=120)
checks=[]
def checked(name,r,expected=200):
    assert r.status_code==expected,(name,r.status_code,r.text[:1000]);checks.append(name);return r.json()
def create(kind,title,data={}):return checked('create '+kind,c.post('/api/objects',json={'type':kind,'title':title,'data':data}))
health=checked('packaged health',c.get('/api/health'))
assert 'runtime-test-data' in health['data_root']
checked('packaged templates',c.get('/api/templates'))
model=create('model','验收用三角形模型（非业务资料）',{'source':'自动验收夹具','format':'BDF'})
case=create('case','验收用流程记录（非工程案例）',{'source':'自动验收夹具'})
checked('relation creation',c.post('/api/relations',json={'source':case['id'],'target':model['id'],'type':'使用模型','evidence':'隔离验收夹具关系'}))
bdf=b'CEND\nBEGIN BULK\nGRID,1,,0.,0.,0.\nGRID,2,,1.,0.,0.\nGRID,3,,0.,1.,0.\nCTRIA3,1,1,1,2,3\nPSHELL,1,1,.1\nMAT1,1,1.E7,,.3\nENDDATA\n'
f=checked('attach bdf',c.post('/api/objects/'+model['id']+'/files',files={'file':('test.bdf',bdf)}))
mesh=checked('packaged BDF parser',c.get('/api/model-assets/'+f['id']+'/mesh'));assert mesh['element_count']==1
stl=b'solid t\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\nendsolid t\n'
sf=checked('attach stl',c.post('/api/objects/'+model['id']+'/files',files={'file':('test.stl',stl)}))
checked('packaged STL parser',c.get('/api/model-assets/'+sf['id']+'/mesh'))
assert checked('packaged search',c.get('/api/search',params={'q':'验收用三角形'}))['total']==1
graph=checked('packaged graph',c.get('/api/graph'));assert len(graph['edges'])>=1
p=checked('packaged task snapshot',c.post('/api/packages',json={'object_ids':[model['id'],case['id']]}));assert p['executable'] is False
backup=c.get('/api/backup');assert backup.status_code==200;checks.append('packaged backup')
checked('packaged restore',c.post('/api/restore',files={'file':('backup.zip',backup.content)}))
result={'status':'passed','runtime':runtime,'checks':checks,'model':model['id'],'file':f['id'],'case':case['id'],'business_data_imported':False}
(root/'evidence/packaged-api-checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
