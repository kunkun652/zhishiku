import json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
space=tempfile.TemporaryDirectory();os.environ['ZH_DATA_ROOT']=space.name
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fastapi.testclient import TestClient
from app.main import app,connect,ROOT,EMBEDDINGS
from app.semantic_search import combine
client=TestClient(app)

class SemanticTests(unittest.TestCase):
 def add(self,title,kind='case',data=None):return client.post('/api/objects',json={'type':kind,'title':title,'data':data or {}}).json()
 def test_vector_recall_filters_and_evidence(self):
  a=self.add('翼盒响应',data={'analysis_type':'静力'})
  b=self.add('振型计算',data={'analysis_type':'模态'})
  hits=[{'object_id':a['id'],'object_hash':a['hash'],'score':.8,'file_id':'source','page':17,'text':'合成原文依据'}, {'object_id':b['id'],'object_hash':b['hash'],'score':.9,'file_id':'','page':0,'text':''}]
  with patch.object(EMBEDDINGS,'status',return_value={'status':'ready','indexed':2}),patch.object(EMBEDDINGS,'call',return_value=hits):
   r=client.get('/api/search',params={'q':'外载作用下如何变形','mode':'semantic','analysis_type':'静力'}).json()
  self.assertEqual([x['id'] for x in r['items']],[a['id']]);self.assertEqual(r['items'][0]['evidence'][0]['page'],17)
 def test_hash_change_rejects_old_vectors(self):
  a=self.add('旧向量对象')
  self.assertEqual(combine([], [{'object_id':a['id'],'object_hash':'outdated','score':1}], [a]),[])
 def test_exact_term_keeps_priority(self):
  a=self.add('精确术语','term');b=self.add('宽泛相关文章','document')
  lexical=[{**a,'score':80,'evidence':[]},{**b,'score':2,'evidence':[]}]
  hits=[{'object_id':b['id'],'object_hash':b['hash'],'score':.8,'file_id':'','page':0,'text':''}]
  self.assertEqual(combine(lexical,hits,[a,b])[0]['id'],a['id'])
 def test_precise_material(self):
  a=self.add('材料样本A','material',{'designation':'7075-T6'})
  self.add('材料样本B','material',{'designation':'2024-T3'})
  r=client.get('/api/search',params={'designation':'7075-T6','mode':'keyword'}).json()
  self.assertEqual([x['id'] for x in r['items']],[a['id']])
 def test_graph_authority_fallback_and_stale_edge(self):
  a=self.add('图谱种子专用');b=self.add('图谱关联模型','model',{'source':'原件第17页'})
  client.post('/api/relations',json={'source':a['id'],'target':b['id'],'type':'使用模型','evidence':'原件第17页明确登记'})
  r=client.get('/api/search',params={'q':a['id'],'mode':'graph'}).json()
  self.assertEqual(r['items'][0]['id'],b['id'])
  self.assertEqual(r['items'][0]['relation_paths'][0][0]['evidence'],'原件第17页明确登记')
  self.assertEqual(r['graph']['backend'],'authority')
  keyword=client.get('/api/search',params={'q':a['title'],'mode':'keyword'}).json()
  self.assertEqual(keyword['run']['channels'],['keyword'])
  b['title']='更新端点';client.put('/api/objects/'+b['id'],json=b)
  r=client.get('/api/search',params={'q':a['id'],'mode':'graph'}).json()
  self.assertFalse(r['items'])
 def test_failure_is_not_no_evidence(self):
  with patch.object(EMBEDDINGS,'status',return_value={'status':'failed','indexed':0,'message':'测试服务失败'}):
   r=client.get('/api/search',params={'q':'不存在','mode':'semantic'}).json()
  self.assertEqual(r['status'],'unavailable')
if __name__=='__main__':unittest.main(verbosity=2)
