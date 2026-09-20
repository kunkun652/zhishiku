import io,json,os,sys,tempfile,unittest,zipfile
from pathlib import Path
TEST_SPACE=tempfile.TemporaryDirectory(prefix='zhiheng-tests-')
os.environ['ZH_DATA_ROOT']=TEST_SPACE.name
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fastapi.testclient import TestClient
from app.main import app,ROOT,connect
client=TestClient(app)

class FrameworkTests(unittest.TestCase):
    def create(self,kind='term',title='试验术语',data=None):
        r=client.post('/api/objects',json={'type':kind,'title':title,'data':data or {}})
        self.assertEqual(r.status_code,200,r.text);return r.json()
    def test_01_empty_database_and_templates(self):
        self.assertEqual(client.get('/api/health').json()['total'],0)
        templates=client.get('/api/templates').json()['templates'];self.assertEqual(len(templates),16)
        for t in templates:
            v=client.get('/api/templates/'+t['type']).json()
            self.assertTrue(all(x=='' or x==[] for x in v['data'].values()))
    def test_02_all_templates_roundtrip(self):
        for t in client.get('/api/templates').json()['templates']:
            body=client.get('/api/templates/'+t['type']).json();body['title']='测试 '+t['label']
            r=client.post('/api/import',json=body);self.assertEqual(r.status_code,200,r.text)
            self.assertEqual(client.get('/api/objects/'+r.json()['id']).json()['data'],body['data'])
    def test_03_chinese_alias_full_record_and_punctuation(self):
        self.create(title='杨氏模量',data={'aliases':'Young modulus,弹性模量','definition':'材料刚度定义完整正文'})
        mat=self.create('material','中文金属测试',{'summary':'Young modulus','properties':[{'name':'E','value':None,'unit':'','source':''}]})
        result=client.get('/api/search',params={'q':'弹性模量'}).json()
        self.assertIn(mat['id'],[r['id'] for r in result['items']])
        self.assertEqual(client.get('/api/search',params={'q':'" OR * - % _'}).status_code,200)
        self.assertEqual(client.get('/api/search',params={'q':'完全不存在的正文'}).json()['status'],'no_matches')
    def test_04_hard_filter_and_unknown(self):
        modal=self.create('case','模态过滤测试',{'analysis_type':'模态'})
        unknown=self.create('case','未知过滤测试')
        r=client.get('/api/search',params={'type':'case','analysis_type':'静力'}).json()
        self.assertNotIn(modal['id'],[x['id'] for x in r['items']]);self.assertIn(unknown['id'],[x['id'] for x in r['items']])
    def test_05_version_optimistic_lock(self):
        a=self.create();old=a.copy();a['title']='新版名称'
        b=client.put('/api/objects/'+a['id'],json=a);self.assertEqual(b.status_code,200)
        self.assertEqual(b.json()['version'],2)
        self.assertEqual(client.put('/api/objects/'+a['id'],json=old).status_code,409)
        self.assertEqual(client.get('/api/objects/'+a['id'],params={'version':1}).json()['title'],old['title'])
        self.assertNotEqual(b.json()['hash'],old['hash'])
    def test_06_reject_invalid_and_review_forgery(self):
        for body in [{'type':'material','title':'非法材料','data':{'solver_card':'PSHELL'}},{'type':'material','title':'非法参数','data':{'properties':[{'name':'E','value':2}]}},{'type':'term','title':'伪复核','status':'reviewed','data':{}},{'type':'model','title':'错误映射','data':{'regions':[{}]}},{'type':'term','title':'字段越界','data':{'invented':3}}]:
            self.assertEqual(client.post('/api/objects',json=body).status_code,422)
        imported=client.post('/api/import',json={'type':'term','title':'导入复核伪造','status':'reviewed','data':{}}).json()
        self.assertEqual(imported['status'],'candidate')
    def test_07_relations_hops_stale(self):
        a,b,c=self.create(title='甲'),self.create(title='乙'),self.create(title='丙')
        for src,dst in [(a,b),(b,c)]:
            self.assertEqual(client.post('/api/relations',json={'source':src['id'],'target':dst['id'],'type':'参考案例','evidence':'测试依据'}).status_code,200)
        one=client.get('/api/graph',params={'focus':a['id'],'hops':1}).json()
        two=client.get('/api/graph',params={'focus':a['id'],'hops':2}).json()
        self.assertEqual(len(one['nodes']),2);self.assertEqual(len(two['nodes']),3)
        a['title']='甲新版';client.put('/api/objects/'+a['id'],json=a)
        self.assertTrue(client.get('/api/graph',params={'focus':a['id']}).json()['edges'][0]['stale'])
        self.assertEqual(client.post('/api/relations',json={'source':a['id'],'target':b['id'],'type':'来源于'}).status_code,422)
    def test_08_package_snapshot_immutable_and_blocked(self):
        a=self.create('task','不可执行任务')
        package=client.post('/api/packages',json={'object_ids':[a['id']]}).json()
        self.assertFalse(package['executable']);self.assertGreater(len(package['gaps']),0)
        a['title']='任务新版';client.put('/api/objects/'+a['id'],json=a)
        saved=next(p for p in client.get('/api/packages').json() if p['id']==package['id'])
        self.assertEqual(saved['objects'][0]['version'],1)
    def test_09_file_hash_dedup_and_tamper(self):
        a=self.create('model','模型测试')
        r=client.post('/api/objects/'+a['id']+'/files',files={'file':('../hello.txt',b'test evidence','text/plain')})
        self.assertEqual(r.status_code,200,r.text);fid=r.json()['id']
        again=client.post('/api/objects/'+a['id']+'/files',files={'file':('../hello.txt',b'test evidence','text/plain')}).json()
        self.assertEqual(fid,again['id']);self.assertEqual(client.get('/api/model-assets/'+fid+'/file').content,b'test evidence')
        files=client.get('/api/objects/'+a['id']+'/files').json();path=ROOT/files[0]['path'];path.write_bytes(b'tampered')
        self.assertEqual(client.get('/api/model-assets/'+fid+'/file').status_code,409);path.write_bytes(b'test evidence')
        self.assertEqual(client.post('/api/objects/'+a['id']+'/files',files={'file':('run.exe',b'bad')}).status_code,422)
    def test_10_backup_restore_and_traversal(self):
        backup=client.get('/api/backup');self.assertEqual(backup.status_code,200)
        r=client.post('/api/restore',files={'file':('backup.zip',backup.content,'application/zip')})
        self.assertEqual(r.status_code,200,r.text);self.assertFalse(r.json()['active_space_changed'])
        raw=io.BytesIO()
        with zipfile.ZipFile(raw,'w') as z:
            z.writestr('knowledge.sqlite3',b'');z.writestr('manifest.json','{}');z.writestr('../escape.txt','bad')
        self.assertEqual(client.post('/api/restore',files={'file':('bad.zip',raw.getvalue())}).status_code,422)
    def test_11_cross_origin_writes(self):
        self.assertEqual(client.post('/api/packages',json={},headers={'Origin':'https://evil.invalid'}).status_code,403)
        self.assertEqual(client.get('/api/health',headers={'Host':'evil.invalid'}).status_code,400)
    def test_12_stl_preview(self):
        a=self.create('model','STL preview test')
        stl=b'solid t\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\nendsolid t\n'
        fid=client.post('/api/objects/'+a['id']+'/files',files={'file':('triangle.stl',stl)}).json()['id']
        r=client.get('/api/model-assets/'+fid+'/mesh');self.assertEqual(r.status_code,200,r.text);self.assertEqual(len(r.json()['triangles']),3)
    def test_13_bdf_preview(self):
        a=self.create('model','BDF preview test')
        bdf=b'CEND\nBEGIN BULK\nGRID,1,,0.,0.,0.\nGRID,2,,1.,0.,0.\nGRID,3,,0.,1.,0.\nCTRIA3,1,1,1,2,3\nPSHELL,1,1,.1\nMAT1,1,1.E7,,.3\nENDDATA\n'
        fid=client.post('/api/objects/'+a['id']+'/files',files={'file':('triangle.bdf',bdf)}).json()['id']
        r=client.get('/api/model-assets/'+fid+'/mesh');self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['element_count'],1)

if __name__=='__main__': unittest.main(verbosity=2)
