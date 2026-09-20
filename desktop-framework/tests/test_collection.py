import os,sys,tempfile,unittest
from pathlib import Path
space=tempfile.TemporaryDirectory();os.environ['ZH_DATA_ROOT']=space.name
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fastapi.testclient import TestClient
from app.main import app,connect
from app.retrieval import tokens
c=TestClient(app)
class CollectionTests(unittest.TestCase):
 def add(self,t,title,data):return c.post('/api/objects',json={'type':t,'title':title,'data':data}).json()
 def test_natural_definition_and_preserve_qualifiers(self):
  a=self.add('term','机身',{'definition':'飞机的主体','aliases':'Fuselage;飞机机身'})
  b=self.add('term','机身框',{'aliases':'Fuselage Frame','definition':'环向构件'})
  case=self.add('case','机身框静强度仿真',{'analysis_type':'静强度'})
  r=c.get('/api/search',params={'q':'什么是飞机机身'}).json();self.assertIn(a['id'],[x['id'] for x in r['items']])
  r=c.get('/api/search',params={'q':'机身框静强度仿真'}).json();self.assertIn(case['id'],[x['id'] for x in r['items']]);self.assertNotIn(b['id'],[x['id'] for x in r['items']])
 def test_page_evidence_and_category(self):
  a=self.add('document','无关键词标题',{'category':'测试分类'})
  with connect() as db:
   text='测试原文：复合材料机翼剪切响应。'
   rid=db.execute('INSERT INTO chunks(object_id,file_id,page,text) VALUES(?,?,?,?)',(a['id'],'test-file',17,text)).lastrowid
   db.execute('INSERT INTO chunks_fts(rowid,tokens) VALUES(?,?)',(rid,tokens(text)))
  r=c.get('/api/search',params={'q':'复合材料机翼剪切响应','category':'测试分类'}).json()
  self.assertEqual(r['items'][0]['evidence'][0]['page'],17)
  self.assertEqual(c.get('/api/search',params={'q':'复合材料机翼剪切响应','category':'其他'}).json()['total'],0)
 def test_empty_negative_and_export(self):
  self.assertEqual(c.get('/api/search',params={'q':'zxq不存在84729'}).json()['status'],'no_matches')
  self.add('term','导出条目',{'definition':'完整字段','source':'测试来源'})
  r=c.get('/api/datasets/candidates');self.assertEqual(r.status_code,200);self.assertIn('"training_ready": false',r.text)
 def test_concurrent_read_during_import(self):
  with connect() as db:
   db.execute("INSERT OR REPLACE INTO meta VALUES('test-lock','1')")
   self.assertEqual(c.get('/api/health').status_code,200)
if __name__=='__main__':unittest.main(verbosity=2)
