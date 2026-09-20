"""Real tokenizer with deterministic vector fixtures for update/resume invariants."""
import unittest,tempfile,sqlite3,sys
from pathlib import Path
import numpy as np
from contextlib import closing
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from embedding_worker import Engine,ENCODING
from index_v2 import make_engine

class TokenIndexTests(unittest.TestCase):
 def test_tail_resume_parent_update_delete_and_old_index_retained(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);old=root/'vectors.sqlite3';old.write_bytes(b'old-index-preserved')
   with closing(sqlite3.connect(root/'knowledge.sqlite3')) as c,c:
    c.executescript("CREATE TABLE objects(id TEXT,type TEXT,title TEXT,payload TEXT,hash TEXT);CREATE TABLE chunks(id INTEGER,object_id TEXT,file_id TEXT,page INTEGER,text TEXT);CREATE TABLE files(id TEXT,sha256 TEXT);CREATE TABLE meta(key TEXT,value TEXT);INSERT INTO meta VALUES('revision','1');INSERT INTO objects VALUES('a','document','完整卡片','{}','h');INSERT INTO files VALUES('f','file-hash');")
    c.execute('INSERT INTO chunks VALUES(?,?,?,?,?)',(1,'a','f',9,'中文段落。\n'*600+'尾部唯一事实'))
   engine=make_engine(Engine,ENCODING)(root,Path(r'D:\zhishiku\runtime\embedding-model'));calls=[]
   def encode(texts):
    calls.extend(texts);v=np.zeros((len(texts),1024),dtype=np.float32);v[:,0]=1;return v
   engine.encode=encode;engine.build();self.assertEqual(engine.error,'');self.assertTrue(engine.status()['complete'])
   self.assertTrue(any('尾部唯一事实' in text for text in calls));n=len(calls);engine.build();self.assertEqual(len(calls),n)
   with closing(sqlite3.connect(root/'knowledge.sqlite3')) as c,c:c.execute("UPDATE chunks SET text=text||'追加来源事实'")
   self.assertFalse(any(hit['file_id']=='f' for hit in engine.search('查询',{'a':'h'})))
   engine.build();self.assertEqual(engine.error,'');self.assertTrue(any(hit['file_id']=='f' for hit in engine.search('查询',{'a':'h'})))
   with closing(sqlite3.connect(root/'knowledge.sqlite3')) as c,c:c.execute('DELETE FROM chunks')
   engine.build();self.assertEqual(engine.error,'')
   with engine.db() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM vectors WHERE file_id='f'").fetchone()[0],0)
   self.assertEqual(old.read_bytes(),b'old-index-preserved')

if __name__=='__main__':unittest.main(verbosity=2)
