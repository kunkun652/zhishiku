import os,sys,tempfile,unittest,json,hashlib,sqlite3
from pathlib import Path
space=tempfile.TemporaryDirectory();os.environ['ZH_DATA_ROOT']=space.name
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fastapi.testclient import TestClient
from app.main import app,connect,ROOT
from app import content_quality,derived_graph
client=TestClient(app)

class WorkspaceTests(unittest.TestCase):
 def add(self,title='对象'):return client.post('/api/objects',json={'type':'document','title':title,'data':{}}).json()
 def test_neighbor_same_file_page_not_id(self):
  o=self.add()
  with connect() as c:
   c.executemany('INSERT INTO chunks VALUES(?,?,?,?,?)',[(101,o['id'],'a',3,'第三页'),(102,o['id'],'b',2,'别的文件'),(103,o['id'],'a',1,'第一页'),(104,o['id'],'a',2,'第二页')])
  r=client.get('/api/source-slices/104').json();self.assertEqual((r['previous'],r['next']),(103,101))
  with connect() as c:c.execute('INSERT INTO chunks VALUES(?,?,?,?,?)',(105,o['id'],'a',2,'同页片内未知'))
  r=client.get('/api/source-slices/104').json();self.assertIsNone(r['previous']);self.assertIsNone(r['next'])
 def test_quality_restores_keyword_and_vector_without_text_edit(self):
  o=self.add('质量规则测试')
  with connect() as c:
   from app.retrieval import tokens
   c.execute('INSERT INTO chunks VALUES(?,?,?,?,?)',(201,o['id'],'q',1,'版权所有独特检索'))
   c.execute('INSERT INTO chunks_fts(rowid,tokens) VALUES(?,?)',(201,tokens('版权所有独特检索')))
   rev=c.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0]
  for status,expected in [('noise',False),('body',True)]:
   response=client.post('/api/source-slices/201/quality',json={'status':status,'reason':'测试纠正'});self.assertEqual(response.status_code,200)
   result=client.get('/api/search',params={'q':'独特检索','mode':'keyword'}).json();self.assertEqual(bool(result['items']),expected)
   with connect() as c:
    self.assertEqual(bool(content_quality.filter_vectors(c,[{'key':'v2:c:201:0:8','file_id':'q'}])),expected)
    self.assertEqual(c.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0],rev)
    self.assertEqual(c.execute('SELECT text FROM chunks WHERE id=201').fetchone()[0],'版权所有独特检索')
  for text in ['E=70000 MPa','kg/m³','σ = F/A','铝合金 2700 kg/m³','12.5 MPa']:
   self.assertEqual(content_quality.classify(text)[0],'body')
 def test_graph_600_relations_pagination_and_snapshot(self):
  o=self.add('大关系集')
  with connect() as c:
   for i in range(601):
    oid='rel-target-'+str(i);payload='{}';c.execute('INSERT INTO objects VALUES(?,?,?,?,?,?,?,?)',(oid,'term',oid,1,'candidate',payload,'h','t'))
    c.execute('INSERT INTO relations VALUES(?,?,?,?,?,?,?)',('edge-'+str(i),o['id'],oid,'来源于','依据 '+str(i),1,1))
  g=client.get('/api/graph',params={'limit':5}).json();snap=g['snapshot']
  ids=[]
  for offset in range(0,601,100):
   r=client.get('/api/graph-node/'+o['id'],params={'snapshot':snap,'offset':offset,'limit':100}).json();self.assertEqual(r['total'],601);ids.extend(x['id'] for x in r['relations'])
  self.assertEqual(len(set(ids)),601)
  o['title']='修改后';client.put('/api/objects/'+o['id'],json=o)
  self.assertEqual(client.get('/api/graph-node/'+o['id'],params={'snapshot':snap}).json()['node']['title'],'大关系集')
  self.assertEqual(client.get('/api/graph-node/'+o['id'],params={'snapshot':snap,'backend':'semantica'}).status_code,409)
 def test_full_graph_has_no_500_or_5000_node_cap(self):
  from app.main import GRAPH_SNAPSHOTS
  import time
  nodes=[{'id':str(i),'type':'term','title':'对象 '+str(i),'version':1,'status':'candidate','data':{'summary':'完整原信息'}} for i in range(6001)]
  edges=[{'id':'cross-boundary','source':'0','target':'6000','source_version':1,'target_version':0,'type':'引用','evidence':'登记依据'},
         {'id':'missing','source':'0','target':'absent','source_version':1,'target_version':1}]
  GRAPH_SNAPSHOTS['full-test']={'nodes':nodes,'edges':edges,'backend':'authority','snapshot':'full-test','revision':1,'consistency':None,'created':time.monotonic()}
  g=client.get('/api/graph',params={'full':True,'snapshot':'full-test','limit':1,'focus':'0','type':'document'}).json()
  self.assertEqual(len(g['nodes']),6001);self.assertEqual(len(g['edges']),1)
  self.assertEqual(g['invalid_edges'],1);self.assertEqual(g['remaining_nodes'],0);self.assertFalse(g['truncated'])
  self.assertTrue(g['edges'][0]['stale']);self.assertNotIn('data',g['nodes'][0])
  detail=client.get('/api/graph-node/6000',params={'snapshot':g['snapshot']}).json()
  self.assertEqual(detail['node']['data']['summary'],'完整原信息')
 def test_derived_never_borrows_current_payload(self):
  o=self.add('历史标题');o['data']['summary']='旧摘要';o=client.put('/api/objects/'+o['id'],json=o).json()
  canonical=derived_graph.normalize([o],[]);artifact={'canonical':canonical};name='graph-artifact-test.json';(ROOT/name).write_text(json.dumps(artifact),'utf-8')
  (ROOT/'graph-manifest.json').write_text(json.dumps({'artifact':name,'revision':0,'content_hash':derived_graph.digest(canonical)}),'utf-8')
  o['data']['summary']='新摘要';client.put('/api/objects/'+o['id'],json=o)
  g=client.get('/api/graph',params={'backend':'semantica'}).json();self.assertEqual(g['nodes'][0]['data']['summary'],'旧摘要')
  r=client.get('/api/graph-node/'+o['id'],params={'backend':'semantica','snapshot':g['snapshot']}).json();self.assertEqual(r['node']['data']['summary'],'旧摘要')
 def test_file_and_body_search(self):
  o=self.add('检索文件')
  with connect() as c:
   c.execute('INSERT INTO files VALUES(?,?,?,?,?,?)',('filename-test',o['id'],'测试资料.pdf','sha',4,'assets/test.pdf'))
   c.execute('INSERT INTO chunks VALUES(?,?,?,?,?)',(301,o['id'],'filename-test',7,'局部精确正文测试'))
  for q in ['测试资料.pdf','局部精确正文']:
   r=client.get('/api/source-slices',params={'q':q}).json();self.assertEqual(r['total'],1,r)
 def test_partial_encoding_and_stale_units_do_not_duplicate_slice(self):
  o=self.add('编码覆盖边界')
  with connect() as c:c.execute('INSERT INTO chunks VALUES(?,?,?,?,?)',(401,o['id'],'encoding-file',1,'abcdef'))
  with sqlite3.connect(ROOT/'vectors-v2.sqlite3') as c:
   c.executescript('CREATE TABLE IF NOT EXISTS units(key TEXT PRIMARY KEY,parent TEXT,parent_hash TEXT,start INTEGER,end INTEGER);CREATE TABLE IF NOT EXISTS vectors(key TEXT PRIMARY KEY);CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT);')
   c.executemany('INSERT INTO units VALUES(?,?,?,?,?)',[('old','c:401','stale',0,6),('current','c:401',hashlib.sha256(b'abcdef').hexdigest(),0,3)])
   c.executemany('INSERT INTO vectors VALUES(?)',[('old',),('current',)])
  r=client.get('/api/source-slices',params={'file_id':'encoding-file'}).json()
  self.assertEqual(r['total'],1,r);self.assertEqual(r['items'][0]['encoding_status'],'pending')
  with sqlite3.connect(ROOT/'vectors-v2.sqlite3') as c:c.execute("UPDATE units SET end=6 WHERE key='current'")
  r=client.get('/api/source-slices',params={'file_id':'encoding-file'}).json();self.assertEqual(r['items'][0]['encoding_status'],'encoded')
 def test_pdf_order_uses_verified_text_offsets(self):
  import fitz
  o=self.add('PDF 原文顺序');path=ROOT/'assets/order.pdf';path.parent.mkdir(exist_ok=True)
  with fitz.open() as doc:
   page=doc.new_page();page.insert_text((40,40),'Alpha structure\nBeta coefficient\nGamma stiffness');doc.save(path)
  with fitz.open(path) as doc:text=doc[0].get_text(sort=True).strip()
  cut=text.index('Beta')
  with connect() as c:
   c.execute('INSERT INTO files VALUES(?,?,?,?,?,?)',('ordered-pdf',o['id'],'order.pdf',hashlib.sha256(path.read_bytes()).hexdigest(),path.stat().st_size,'assets/order.pdf'))
   c.executemany('INSERT INTO chunks VALUES(?,?,?,?,?)',[(502,o['id'],'ordered-pdf',1,text[:cut]),(501,o['id'],'ordered-pdf',1,text[cut:])])
  a=client.get('/api/source-slices/502').json();b=client.get('/api/source-slices/501').json()
  self.assertEqual(a['next'],501);self.assertEqual(b['previous'],502);self.assertEqual(b['source_start'],cut)

if __name__=='__main__':unittest.main(verbosity=2)
