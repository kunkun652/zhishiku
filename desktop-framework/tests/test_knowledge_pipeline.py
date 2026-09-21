"""Focused contracts, real SQLite/FTS5, explicit fake external engines.

Not a Windows EXE, actual Semantica, BGE-M3, or Ollama acceptance test.
Run: python -m unittest discover -s desktop-framework/tests -p test_knowledge_pipeline.py -v
"""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from app import retrieval, content_quality, pipeline_parsers
from app.pipeline_store import Pipeline, dump, key
from app.pipeline_extraction import PATTERNS, REVISION
from app.pipeline_agent import HybridRetriever, EvidenceAgent
from app.pipeline_api import install
from app.pipeline_runtime import llm_config, Ollama, SemanticaWorker


class UnavailableEmbedding:
    def status(self): return {'status': 'unavailable', 'indexed': 0, 'message': 'test deliberately has no BGE-M3'}
    def call(self, *_): raise RuntimeError('test deliberately has no BGE-M3')


class ContractBackend:
    """Existing main.py persistence/validation contract, not a replacement app."""
    def __init__(self, root):
        self.ROOT = Path(root)
        self.LOCK = threading.RLock()
        self.SEMANTIC_BUILD_LOCK = threading.Lock()
        self.EMBEDDINGS = UnavailableEmbedding()
        self.app = FastAPI()
        with self.connect() as c:
            c.execute('PRAGMA journal_mode=WAL')
            c.executescript('''
            CREATE TABLE objects(id TEXT PRIMARY KEY,type TEXT,title TEXT,version INTEGER,status TEXT,payload TEXT,hash TEXT,updated TEXT);
            CREATE TABLE versions(id TEXT,version INTEGER,snapshot TEXT,PRIMARY KEY(id,version));
            CREATE TABLE relations(id TEXT PRIMARY KEY,source TEXT,target TEXT,type TEXT,evidence TEXT,source_version INTEGER,target_version INTEGER);
            CREATE TABLE files(id TEXT PRIMARY KEY,object_id TEXT,name TEXT,sha256 TEXT,size INTEGER,path TEXT);
            CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);
            INSERT INTO meta VALUES('revision','0');
            ''')
            retrieval.init(c)
    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.ROOT / 'knowledge.sqlite3', timeout=20)
        c.row_factory = sqlite3.Row
        try:
            with c: yield c
        finally: c.close()
    @staticmethod
    def now(): return datetime.now(timezone.utc).isoformat()
    encoded = staticmethod(dump)
    digest = staticmethod(key)
    @staticmethod
    def revision(c): c.execute("UPDATE meta SET value=CAST(value AS INTEGER)+1 WHERE key='revision'")
    @staticmethod
    def record(row):
        if row is None: raise KeyError('object missing')
        r = dict(row); r['data'] = json.loads(r.pop('payload')); return r
    @staticmethod
    def validate(body):
        common = {'summary','source','category','rights','scope','analysis_type','units','limitations','verification','original_record'}
        fields = {'document': {'author','revision','locator','license','extraction_status'},
                  'material': {'designation','state','temperature','direction','solver_card','properties'},
                  'mesh': {'geometry','element_type','method','quality','convergence'},
                  'term': {'definition','aliases','dimension','confusions'},
                  'condition': {'level','core','conditional','upstream','mesh','material','loads','constraints'}}
        kind, title, data = body['type'], body['title'].strip(), body.get('data', {})
        if kind not in fields or not title or set(data) - fields[kind] - common: raise ValueError('invalid template')
        for k, v in data.items():
            if k != 'properties' and not isinstance(v, str): raise ValueError('template field must be text')
        return kind, title, data
    def asset(self, fid):
        with self.connect() as c: row = c.execute('SELECT * FROM files WHERE id=?', (fid,)).fetchone()
        if row is None: raise KeyError('file missing')
        path = (self.ROOT / row['path']).resolve()
        if not path.is_relative_to(self.ROOT / 'assets') or not path.is_file(): raise ValueError('invalid managed path')
        if hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']: raise ValueError('file hash mismatch')
        return row, path
    def search(self, q, mode='hybrid', limit=10, **filters):
        with self.connect() as c:
            items = [self.record(r) for r in c.execute("SELECT * FROM objects WHERE status NOT IN ('retired','conflict')")]
            for field in ('type','status'):
                if filters.get(field): items = [r for r in items if r[field] == filters[field]]
            found = retrieval.retrieve(c, items, q, limit=limit)
            for r in found['items']: r['retrieval_channels'] = ['关键词']
            rev = int(c.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0])
        return {**found, 'run': {'revision':rev,'channels':['keyword'],'degradations':['fixture: vector and graph not exercised']},
                'embedding':self.EMBEDDINGS.status(),'graph':{'status':'not_requested'}}


class FixtureWorker:
    """Deterministic test double; NEVER evidence of actual Semantica execution."""
    def status(self): return {'status':'ready','semantica_version':'TEST-FIXTURE-NOT-SEMANTICA'}
    def run(self, payload, **_):
        if payload.get('operation') == 'graph':
            from app.derived_graph import normalize
            return {'canonical':normalize(payload['nodes'],payload['edges']), 'semantica_version':self.status()['semantica_version']}
        candidates = []
        for s in payload['segments']:
            for label, pattern in PATTERNS.items():
                for match in re.finditer(pattern, s['text']):
                    item = {'key':key([s['key'],label,match.span()]),'kind':'entity','label':label,'title':match.group(),
                            'evidence':{'segment_key':s['key'],'start':match.start(),'end':match.end(),'quote':match.group(),'source_type':'TEST_FIXTURE','confidence':None}}
                    if label == 'ASSERTION':
                        f = match.groupdict(); item['assertion'] = {**f,'value':float(f['value']),'scope':'unspecified'}
                        item['title'] = f['subject'] + ' · ' + f['property']
                    candidates.append(item)
        return {'adapter':REVISION,'mode':payload['mode'],'semantica_version':self.status()['semantica_version'],
                'candidates':candidates,'scope':'TEST_FIXTURE','rejected':0}


class FixtureModel:
    def __init__(self, malformed=False): self.calls=0; self.malformed=malformed
    def status(self): return {'status':'ready','model':'TEST-FIXTURE-NOT-LLM'}
    def generate(self, query, evidence):
        self.calls += 1
        e = evidence[0]
        return {'claims':[{'text':'测试中的原文摘录。','citations':[{'id':'FORGED' if self.malformed else e['id'],'quote':e['quote']}]}],
                'gaps':[],'model':'TEST-FIXTURE-NOT-LLM'}


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.b=ContractBackend(self.temp.name)
        self.worker=FixtureWorker(); self.p=Pipeline(self.b,self.worker)
    def tearDown(self): self.p.close(); self.temp.cleanup()
    def ingest(self, text='机翼采用 CTETRA 单元。', filename='sample.txt'):
        f=self.p.upload(text.encode(),filename)
        j=self.p.start(f['id'],synchronous=True)
        self.assertEqual(j['state'],'awaiting_review',j)
        return f,j,self.p.list_candidates(j['id'])['items']
    def count(self, table):
        with self.b.connect() as c: return c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
    def test_upload_idempotent_and_sanitized(self):
        a=self.p.upload(b'hello','../../a.txt'); b=self.p.upload(b'hello','a.txt')
        self.assertEqual(a['id'],b['id']); self.assertEqual(a['name'],'a.txt'); self.assertEqual(self.count('files'),1)
    def test_unsupported_upload_rejected(self):
        with self.assertRaises(ValueError): self.p.upload(b'bad','file.exe')
    def test_real_fts_index_is_written(self):
        self.ingest()
        with self.b.connect() as c:
            self.assertGreater(c.execute("SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH 'ctetra'").fetchone()[0],0)
    def test_only_staging_before_review(self):
        _,_,rows=self.ingest(); self.assertTrue(rows); self.assertEqual(self.count('objects'),1)
        self.assertEqual(self.count('relations'),0)
    def test_idempotent_jobs_and_chunks(self):
        f,j,rows=self.ingest(); counts=[self.count(t) for t in ['chunks','pipeline_candidates']]
        other=self.p.start(f['id'],synchronous=True)
        self.assertEqual(other['id'],j['id']); self.assertEqual(counts,[self.count(t) for t in ['chunks','pipeline_candidates']])
    def test_accept_audited_not_engineering_approved(self):
        _,_,rows=self.ingest(); r=self.p.review([rows[0]['id']],'accept','test reviewer')
        self.assertFalse(r['engineering_approval']); self.assertEqual(self.count('relations'),1)
        with self.b.connect() as c:
            self.assertEqual(c.execute('SELECT status FROM objects WHERE id=?',(r['items'][0]['object_id'],)).fetchone()[0],'candidate')
        self.assertEqual(self.count('pipeline_reviews'),1)
    def test_double_accept_is_noop(self):
        _,_,rows=self.ingest(); cid=rows[0]['id']; self.p.review([cid],'accept','reviewer')
        self.assertEqual(self.p.review([cid],'accept','reviewer')['items'],[])
        self.assertEqual(self.count('pipeline_reviews'),1)
    def test_atomic_batch_unknown_candidate(self):
        _,_,rows=self.ingest()
        with self.assertRaises(KeyError): self.p.review([rows[0]['id'],'missing'],'accept','reviewer')
        self.assertEqual(self.count('objects'),1)
    def test_require_reviewer(self):
        _,_,rows=self.ingest()
        with self.assertRaises(ValueError): self.p.review([rows[0]['id']],'accept','')
    def test_changed_source_refuses_review(self):
        f,_,rows=self.ingest(); _,path=self.b.asset(f['id']); path.write_text('changed')
        with self.assertRaises(ValueError): self.p.review([rows[0]['id']],'accept','reviewer')
        self.assertEqual(self.count('objects'),1)
    def test_changed_chunk_refuses_review(self):
        _,_,rows=self.ingest()
        with self.b.connect() as c: c.execute("UPDATE chunks SET text='changed'")
        with self.assertRaises(ValueError): self.p.review([rows[0]['id']],'accept','reviewer')
    def test_revoke_versions_and_retires(self):
        _,_,rows=self.ingest(); cid=rows[0]['id']; oid=self.p.review([cid],'accept','r')['items'][0]['object_id']
        self.p.review([cid],'revoke','r','source correction')
        with self.b.connect() as c:
            r=c.execute('SELECT version,status FROM objects WHERE id=?',(oid,)).fetchone()
            self.assertEqual(tuple(r),(2,'retired'))
    def test_revoke_refuses_changed_object(self):
        _,_,rows=self.ingest(); cid=rows[0]['id']; oid=self.p.review([cid],'accept','r')['items'][0]['object_id']
        with self.b.connect() as c: c.execute("UPDATE objects SET hash='changed' WHERE id=?",(oid,))
        with self.assertRaises(ValueError): self.p.review([cid],'revoke','r','correction')
    def test_equal_units_not_conflict(self):
        self.ingest('机翼的载荷为5000 N。机翼的载荷为5 kN。')
        self.assertEqual(self.count('pipeline_conflicts'),0)
    def test_scope_difference_requires_note_not_auto_resolution(self):
        _,_,rows=self.ingest('机翼的载荷为5000 N。机翼的载荷为8000 N。')
        assertions=[r for r in rows if r['payload'].get('assertion')]
        self.assertEqual(len(assertions),2); self.assertEqual(self.count('pipeline_conflicts'),1)
        with self.assertRaises(ValueError): self.p.review([assertions[0]['id']],'accept','r')
        self.p.review([assertions[0]['id']],'accept','r',conflict_note='不同工况，保留两份原文待工程核查')
        with self.b.connect() as c: self.assertEqual(c.execute('SELECT status FROM pipeline_conflicts').fetchone()[0],'acknowledged')
    def test_wrong_dimension_cannot_be_overridden(self):
        _,_,rows=self.ingest('机翼的载荷为70 GPa。')
        assertion=next(r for r in rows if r['payload'].get('assertion'))
        with self.assertRaises(ValueError): self.p.review([assertion['id']],'accept','r',conflict_note='override')
    def test_worker_failure_is_failed_not_success(self):
        f=self.p.upload(b'CTETRA','a.txt')
        with patch.object(self.worker,'run',side_effect=RuntimeError('deliberate failure')):
            j=self.p.start(f['id'],synchronous=True)
        self.assertEqual(j['state'],'failed'); self.assertIn('deliberate failure',j['error'])
    def test_malformed_worker_span_is_rejected(self):
        f=self.p.upload(b'CTETRA','a.txt'); original=self.worker.run
        def corrupt(body):
            out=original(body); out['candidates'][0]['evidence']['quote']='FORGED'; return out
        with patch.object(self.worker,'run',side_effect=corrupt): j=self.p.start(f['id'],synchronous=True)
        self.assertEqual(j['state'],'failed'); self.assertEqual(self.count('pipeline_candidates'),0)
    def test_real_fts_evidence_pack(self):
        self.ingest(); pack=HybridRetriever(self.b).retrieve('CTETRA')
        self.assertEqual(pack['status'],'ready'); self.assertTrue(pack['evidence'][0]['file_hash'])
        self.assertEqual(pack['channels']['used'],['keyword'])
    def test_noise_not_citable(self):
        self.ingest()
        with self.b.connect() as c:
            r=c.execute('SELECT * FROM chunks').fetchone()
            c.execute('INSERT INTO chunk_quality VALUES(?,?,?,?,?,?)',(r['id'],'noise','test','test',pipeline_parsers.sha(r['text']),self.b.now()))
        self.assertEqual(HybridRetriever(self.b).retrieve('CTETRA')['status'],'no_evidence')
    def test_no_evidence_does_not_call_model(self):
        model=FixtureModel(); r=EvidenceAgent(self.b,model=model).answer('unfindable')
        self.assertEqual(r['status'],'no_evidence'); self.assertEqual(model.calls,0)
    def test_missing_model_evidence_only(self):
        self.ingest()
        with patch.dict(os.environ,{'ZH_LLM_MODEL':''}): r=EvidenceAgent(self.b).answer('CTETRA')
        self.assertEqual(r['status'],'model_unavailable'); self.assertTrue(r['evidence_pack']['evidence'])
    def test_valid_citation_model_fixture(self):
        self.ingest(); r=EvidenceAgent(self.b,model=FixtureModel()).answer('CTETRA')
        self.assertEqual(r['status'],'answered',r); self.assertEqual(self.count('pipeline_agent_runs'),1)
        self.assertFalse(r['solver_executed'])
    def test_forged_citation_model_fixture_rejected(self):
        self.ingest(); r=EvidenceAgent(self.b,model=FixtureModel(True)).answer('CTETRA')
        self.assertNotEqual(r['status'],'answered'); self.assertEqual(r['claims'],[])
    def test_invalid_filters_rejected(self):
        for filters in [{'sql':'DROP TABLE objects'},{'status':'retired'}]:
            with self.assertRaises(ValueError): HybridRetriever(self.b).retrieve('x',filters)
    def test_api_no_arbitrary_path_and_no_fake_model(self):
        install(self.b,worker=self.worker,model=FixtureModel())
        with TestClient(self.b.app) as client:
            self.assertEqual(client.post('/api/pipeline/jobs',json={'path':'D:/secret.txt'}).status_code,422)
            self.assertEqual(client.post('/api/agent/ask',json={'query':'x'}).json()['status'],'no_evidence')
            self.assertEqual(client.get('/api/pipeline/status').json()['components']['semantica']['status'],'not_checked')
    def test_api_upload_and_retrieve(self):
        install(self.b,worker=self.worker)
        with TestClient(self.b.app) as client:
            f=client.post('/api/pipeline/upload',files={'file':('readme.txt',b'CTETRA','text/plain')}).json()
            self.p.start(f['id'],synchronous=True)
            response=client.post('/api/retrieve',json={'query':'CTETRA'})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['status'],'ready')
    def test_api_missing_candidate_not_internal_error(self):
        install(self.b,worker=self.worker)
        with TestClient(self.b.app) as client:
            self.assertEqual(client.post('/api/pipeline/review',json={'ids':['missing'],'action':'accept','reviewer':'r'}).status_code,404)


class ParserAndRuntimeTests(unittest.TestCase):
    def test_text_no_silent_truncation(self):
        text='abcdefghij'*1000; result=pipeline_parsers.parse(text.encode(),'a.txt')
        chars=set()
        for s in result['segments']: chars.update(range(s['start'],s['end']))
        self.assertEqual(len(chars),len(text))
    def test_empty_or_binary_rejected(self):
        for raw in (b'',b'abc\x00def'):
            with self.assertRaises(ValueError): pipeline_parsers.parse(raw,'a.txt')
    def test_include_is_gap_not_followed(self):
        r=pipeline_parsers.parse(b"SOL 101\nINCLUDE 'C:/secret.bdf'\nCTETRA",'test.bdf')
        self.assertEqual(r['coverage'],'partial'); self.assertTrue(r['gaps'])
        self.assertFalse(r['engineering_parse'])
    def test_docx_has_no_fabricated_page(self):
        from docx import Document
        doc=Document(); doc.add_paragraph('CTETRA'); stream=io.BytesIO(); doc.save(stream)
        r=pipeline_parsers.parse(stream.getvalue(),'a.docx')
        self.assertTrue(all(s['page']==0 for s in r['segments'])); self.assertEqual(r['coverage'],'partial')
    def test_remote_llm_url_rejected(self):
        for url in ['https://api.example.com','http://127.0.0.1:11434/redirect','http://user@127.0.0.1']:
            with patch.dict(os.environ,{'ZH_OLLAMA_URL':url}):
                with self.assertRaises(ValueError): llm_config()
    def test_unconfigured_model_truthful(self):
        with patch.dict(os.environ,{'ZH_LLM_MODEL':'','ZH_OLLAMA_URL':'http://127.0.0.1:11434'}):
            self.assertEqual(Ollama().status()['status'],'not_configured')
    def test_missing_worker_executable_truthful(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ,{'ZH_SEMANTICA_PYTHON':'/definitely/no/python'}):
            self.assertEqual(SemanticaWorker(Path(root)).status()['status'],'unavailable')

if __name__=='__main__': unittest.main()
