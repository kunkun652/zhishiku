import os,sys,tempfile,unittest,copy
from unittest.mock import patch
from pathlib import Path
space=tempfile.TemporaryDirectory();os.environ['ZH_DATA_ROOT']=space.name
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fastapi.testclient import TestClient
from app.main import app,connect,EMBEDDINGS
from app.derived_graph import normalize,compare
from app.graph_workspace import select
client=TestClient(app)

class UpgradeTests(unittest.TestCase):
 def add(self,title,data=None):return client.post('/api/objects',json={'type':'case','title':title,'data':data or {}}).json()
 def test_graph_limit_focus_boundary_and_isolation(self):
  nodes=[{'id':str(i),'type':'term','version':1} for i in range(601)]
  edges=[{'id':str(i),'source':'0','target':str(i),'type':'来源于','evidence':'引用','source_version':1,'target_version':1} for i in range(1,600)]
  g=select(nodes,edges,focus='599')
  self.assertIn('599',[n['id'] for n in g['nodes']]);self.assertEqual(g['isolated_nodes'],1)
  self.assertGreater(g['boundary_edges'],0)
  self.assertEqual(select(nodes,edges)['total_nodes'],601)
 def test_content_diff(self):
  a={'nodes':[{'id':'a','version':1},{'id':'b','version':1}],'edges':[{'id':'r','source':'a','target':'b','evidence':'依据','source_version':1}]}
  for field,value in [('evidence','changed'),('source_version',2),('source','b')]:
   b=copy.deepcopy(a);b['edges'][0][field]=value;self.assertEqual(compare(a,b)['edges']['changed'],['r'])
  b=copy.deepcopy(a);b['edges']=[];self.assertEqual(compare(a,b)['edges']['missing'],['r'])
  b=copy.deepcopy(a);b['edges'].append({**b['edges'][0],'id':'extra'});self.assertEqual(compare(a,b)['edges']['extra'],['extra'])
 def test_candidate_audit_and_revoke(self):
  b=self.add('引用目标');a=self.add('明确字段',{'model_ids':b['id']})
  p=client.post('/api/objects/'+a['id']+'/discover-relations').json();cid=p['candidate_ids'][0]
  for action,status in [('reject','rejected'),('undo','pending'),('accept','accepted'),('undo','pending')]:
   response=client.post('/api/relation-candidates/review',json={'ids':[cid],'action':action});self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.json()[0]['status'],status)
  self.assertFalse(client.get('/api/objects/'+a['id']+'/wiki').json()['outgoing'])
  with connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM relation_events WHERE candidate_id=?',(cid,)).fetchone()[0],4)
 def test_candidate_staleness_and_ambiguity(self):
  b=self.add('重复名称');self.add('重复名称');a=self.add('引用',{'model_ids':b['id']})
  cid=client.post('/api/objects/'+a['id']+'/discover-relations').json()['candidate_ids'][0]
  b['title']='更新';client.put('/api/objects/'+b['id'],json=b)
  self.assertEqual(client.post('/api/relation-candidates/review',json={'ids':[cid],'action':'accept'}).status_code,409)
  self.add('重复名称');self.assertEqual(client.get('/api/objects-lookup',params={'q':'重复名称'}).json()['total'],2)
 def test_slice_full_text_and_missing_offset(self):
  a=self.add('长文')
  with connect() as c:c.execute('INSERT INTO chunks VALUES(?,?,?,?,?)',(1,a['id'],'file',17,'长文'*2000+'尾部事实'))
  r=client.get('/api/slices/1').json();self.assertTrue(r['text'].endswith('尾部事实'));self.assertIsNone(r['offset']);self.assertEqual(r['page'],17)
 def test_explicit_code_does_not_become_semantic_similarity(self):
  a=self.add('其他编号')
  with patch.object(EMBEDDINGS,'status',return_value={'status':'ready','indexed':1}),patch.object(EMBEDDINGS,'call',return_value=[{'object_id':a['id'],'object_hash':a['hash'],'score':.99,'file_id':'','page':0,'text':'相似但没有指定编号'}]):
   r=client.get('/api/search',params={'q':'ZH-MISSING-9871','mode':'hybrid'}).json()
  self.assertFalse(r['items'])
 def test_snapshot_rejects_changed_query_and_removed_current_record(self):
  a=self.add('快照唯一名称')
  result=client.get('/api/search',params={'q':a['title'],'mode':'keyword'}).json()
  params={'q':a['title'],'mode':'keyword','snapshot':result['snapshot']}
  self.assertEqual(client.get('/api/search',params={**params,'q':'另一个问题'}).status_code,409)
  a['status']='retired';client.put('/api/objects/'+a['id'],json=a)
  self.assertFalse(client.get('/api/search',params=params).json()['items'])
 def test_sentence_candidate_remains_pending_and_source_change_expires(self):
  target=client.post('/api/objects',json={'type':'material','title':'试验材料甲','data':{}}).json()
  source=self.add('句式来源')
  with connect() as c:c.execute('INSERT INTO chunks VALUES(?,?,?,?,?)',(999,source['id'],'missing-file',7,'该构型不采用试验材料甲。'))
  result=client.post('/api/objects/'+source['id']+'/discover-relations').json();self.assertEqual(len(result['candidate_ids']),1)
  wiki=client.get('/api/objects/'+source['id']+'/wiki').json();self.assertFalse(wiki['outgoing']);self.assertEqual(wiki['candidates'][0]['status'],'pending')
  self.assertIn('不采用',wiki['candidates'][0]['provenance']['quote'])
  with connect() as c:c.execute("UPDATE chunks SET text='来源已修订' WHERE id=999")
  self.assertTrue(client.get('/api/objects/'+source['id']+'/wiki').json()['candidates'][0]['stale'])
  self.assertEqual(client.post('/api/relation-candidates/review',json={'ids':result['candidate_ids'],'action':'accept'}).status_code,409)

if __name__=='__main__':unittest.main(verbosity=2)
