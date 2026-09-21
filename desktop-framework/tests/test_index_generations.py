"""Generation publication and recovery with deterministic vectors, not model quality."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from contextlib import closing
from test_token_index import Engine, ENCODING, make_engine, np
from index_generations import Generations, index_path


class GenerationTests(unittest.TestCase):
    def test_copy_on_write_resume_publish_and_metadata_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve()
            with closing(sqlite3.connect(root/'knowledge.sqlite3')) as c,c:
                c.executescript("CREATE TABLE objects(id TEXT,type TEXT,title TEXT,payload TEXT,hash TEXT);CREATE TABLE chunks(id INTEGER,object_id TEXT,file_id TEXT,page INTEGER,text TEXT);CREATE TABLE files(id TEXT,sha256 TEXT);CREATE TABLE meta(key TEXT,value TEXT);INSERT INTO meta VALUES('revision','1');INSERT INTO objects VALUES('a','document','报告','{}','h1');INSERT INTO chunks VALUES(1,'a','f',1,'unchanged body');INSERT INTO files VALUES('f','f1');")
            calls=[]
            base=make_engine(Engine,ENCODING)
            class FakeEngine(base):
                def encode(self,texts):
                    calls.extend(texts);v=np.zeros((len(texts),1024),dtype=np.float32);v[:,0]=1;return v
            g=Generations(root,Path(r'D:\zhishiku\runtime\embedding-model'),FakeEngine)
            g.active().build();g.activate();original=index_path(root);before=original.read_bytes()
            with closing(sqlite3.connect(root/'knowledge.sqlite3')) as c,c:
                c.execute("UPDATE objects SET title='更名报告',hash='h2'")
                c.execute("UPDATE meta SET value='2'")
            pending=g.prepare();self.assertNotEqual(pending.path,original)
            self.assertEqual(index_path(root),original)
            with self.assertRaises(ValueError):g.activate()
            calls.clear();pending.build();self.assertEqual(pending.error,'')
            self.assertNotIn('unchanged body',calls)
            self.assertEqual(original.read_bytes(),before)
            restarted=Generations(root,g.model,FakeEngine)
            self.assertEqual(restarted.candidate().path,pending.path)
            restarted.activate();self.assertEqual(index_path(root),pending.path)
            self.assertFalse((root/'pending-index.json').exists())
            self.assertEqual(original.read_bytes(),before)
            # Simulate a crash just after atomic active-pointer replacement.
            (root/'pending-index.json').write_text(json.dumps({'file':pending.path.name}),'utf-8')
            self.assertNotEqual(restarted.prepare().path,pending.path)
            self.assertEqual(index_path(root),pending.path)

    def test_manifest_cannot_escape_data_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'active-index.json').write_text(json.dumps({'file':'../elsewhere.sqlite3'}))
            with self.assertRaises(ValueError):index_path(root)


if __name__=='__main__':unittest.main(verbosity=2)
