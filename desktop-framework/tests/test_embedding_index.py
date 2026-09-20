"""Index consistency tests; deterministic vectors are test fixtures, not model evidence."""
import json,sqlite3,sys,tempfile,unittest
from pathlib import Path
import numpy as np
from contextlib import closing
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from embedding_worker import Engine,ENCODING

class IndexTests(unittest.TestCase):
 def setUp(self):
  self.space=tempfile.TemporaryDirectory();self.root=Path(self.space.name)
  with closing(sqlite3.connect(self.root/'knowledge.sqlite3')) as c, c:
   c.executescript("CREATE TABLE objects(id TEXT,type TEXT,title TEXT,payload TEXT,hash TEXT);CREATE TABLE chunks(id INTEGER,object_id TEXT,file_id TEXT,page INTEGER,text TEXT);CREATE TABLE meta(key TEXT,value TEXT);INSERT INTO meta VALUES('revision','1');INSERT INTO objects VALUES('a','document','Test','{}','h1');INSERT INTO chunks VALUES(1,'a','f1',8,'page text');")
  self.engine=Engine(self.root,self.root/'model');self.calls=0
  def encode(texts):
   self.calls+=len(texts);v=np.zeros((len(texts),1024),dtype=np.float32);v[:,0]=1;return v
  self.engine.encode=encode
 def tearDown(self):self.space.cleanup()
 def test_resume_and_page_change(self):
  self.engine.build();self.assertEqual(self.calls,2);self.assertEqual(self.engine.status()['status'],'ready')
  self.engine.build();self.assertEqual(self.calls,2)
  with closing(sqlite3.connect(self.root/'knowledge.sqlite3')) as c, c:c.execute("UPDATE chunks SET text='changed' WHERE id=1")
  hits=self.engine.search('q',{'a':'h1'})
  self.assertNotIn('c:1',[r['key'] for r in hits])
  self.engine.build();self.assertIn('c:1',[r['key'] for r in self.engine.search('q',{'a':'h1'})])
 def test_model_signature_refusal(self):
  with self.engine.db() as c:c.execute("UPDATE meta SET value='another model' WHERE key='encoding'")
  with self.assertRaises(ValueError):Engine(self.root,self.root/'model')
 def test_changed_object_rejects_old_embeddings(self):
  self.engine.build()
  self.assertEqual(self.engine.search('q',{'a':'h2'}),[])
  with closing(sqlite3.connect(self.root/'knowledge.sqlite3')) as c, c:c.execute("UPDATE meta SET value='2' WHERE key='revision'")
  self.assertEqual(self.engine.status()['status'],'stale')
if __name__=='__main__':unittest.main(verbosity=2)
