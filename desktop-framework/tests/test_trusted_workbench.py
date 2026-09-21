"""Security, outbound data gates, source reader and outbox regression fixtures."""
import json
import unittest
from unittest.mock import patch
from unittest.mock import Mock
import httpx
from fastapi.testclient import TestClient
from test_knowledge_pipeline import FixtureRuntime, TEXT, UnavailableEmbeddings
from app.service import app, core, pipeline
from app.workbench import ModelSettings, AnswerModel
from app.change_queue import enqueue


class TrustedWorkbenchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.client.headers['Authorization'] = 'Bearer '+app.state.access.owner_token
        cls.anonymous = TestClient(app)
        pipeline.runtime = FixtureRuntime()
        core.EMBEDDINGS = UnavailableEmbeddings()
        cls.job = pipeline.import_bytes(TEXT.encode(), '测试来源.txt')
        cls.file_id = cls.job['file_id']
        cls.file_hash = core.asset(cls.file_id)[0]['sha256']
        cls.settings = ModelSettings(core.ROOT)

    @classmethod
    def tearDownClass(cls):
        cls.client.close();cls.anonymous.close();pipeline.close()

    def test_01_anonymous_reads_and_writes_denied(self):
        for path in ('/api/health','/api/library/files','/api/model-assets/'+self.file_id+'/file'):
            self.assertEqual(self.anonymous.get(path).status_code,401)
        self.assertEqual(self.anonymous.post('/api/workbench/settings',json={}).status_code,401)
        self.assertEqual(self.anonymous.get('/api/ping').status_code,200)

    def test_02_one_use_bootstrap_cookie_and_bad_bearer(self):
        with TestClient(app) as client:
            token=app.state.access.bootstrap
            r=client.post('/api/session',json={'token':token})
            self.assertEqual(r.status_code,200)
            self.assertIn('HttpOnly',r.headers['set-cookie'])
            self.assertIn('SameSite=strict',r.headers['set-cookie'])
            self.assertEqual(client.get('/api/library/files').status_code,200)
            self.assertEqual(client.post('/api/session',json={'token':token}).status_code,401)
            self.assertEqual(client.get('/api/library/files',headers={'Authorization':'Bearer invalid'}).status_code,401)

    def test_03_scoped_agent_cannot_approve_or_change_policy(self):
        for role in ('reader','processor'):
            value=self.client.post('/api/security/agent-token',json={'role':role}).json()
            headers={'Authorization':'Bearer '+value['token']}
            self.assertEqual(self.anonymous.get('/api/library/files',headers=headers).status_code,200)
            for endpoint in ('/api/workbench/settings','/api/security/agent-token','/api/import',
                             '/api/pipeline/jobs/'+self.job['id']+'/review','/api/library/files/'+self.file_id+'/policy'):
                self.assertEqual(self.anonymous.post(endpoint,json={},headers=headers).status_code,403)
            self.client.delete('/api/security/agent-token/'+value['id'])
            self.assertEqual(self.anonymous.get('/api/library/files',headers=headers).status_code,401)

    def test_04_cross_origin_reads_also_denied(self):
        self.assertEqual(self.client.get('/api/library/files',headers={'Origin':'https://evil.invalid'}).status_code,403)

    def test_05_full_text_search_and_source_reading(self):
        self.assertEqual(self.client.get('/api/library/files',params={'q':'弹性模量'}).json()['total'],1)
        r=self.client.get('/api/library/files/'+self.file_id+'/read').json()
        self.assertEqual(r['blocks'][0]['text'],TEXT)
        self.assertEqual(r['file_hash'],self.file_hash)
        self.assertFalse(r['outbound_allowed'])
        self.assertEqual(self.client.get('/api/library/files',params={'q':'" OR *'}).status_code,200)

    def test_06_remote_default_deny_even_when_key_exists(self):
        self.settings.save({'base_url':'https://fixture.invalid/v1','model':'fixture','api_key':'fixture'})
        with patch('app.workbench.httpx.Client') as transport:
            r=self.client.post('/api/workbench/ask',json={'query':'铝合金'}).json()
            self.assertEqual(r['claims'],[])
            transport.assert_not_called()

    def test_07_file_consent_required_and_revision_bound(self):
        self.settings.save({'allow_remote':True})
        with patch('app.workbench.httpx.Client') as transport:
            self.client.post('/api/workbench/ask',json={'query':'铝合金'})
            transport.assert_not_called()
        endpoint='/api/library/files/'+self.file_id+'/policy'
        self.assertEqual(self.client.post(endpoint,json={'allowed':True,'file_hash':'wrong'}).status_code,409)
        self.assertEqual(self.client.post(endpoint,json={'allowed':True,'file_hash':self.file_hash}).status_code,200)
        self.assertTrue(app.state.data_policy.permitted(self.file_id,self.file_hash))
        self.assertFalse(app.state.data_policy.permitted(self.file_id,'future-version'))
        self.client.post(endpoint,json={'allowed':False,'file_hash':self.file_hash})

    def test_08_supported_id_but_unsupported_claim_is_withheld(self):
        self.settings.save({'base_url':'http://127.0.0.1:9999/v1','model':'fixture'})
        replies=[(json.dumps({'claims':[{'text':'错误工况下的结论','evidence_ids':['E1']}],'gaps':[]}), 'fixture'),
                 (json.dumps({'checks':[{'id':'0','support':'contradicted'}]}),'fixture')]
        with patch.object(AnswerModel,'complete',side_effect=replies):
            r=self.client.post('/api/workbench/ask',json={'query':'铝合金'}).json()
        self.assertEqual(r['claims'],[])
        self.assertEqual(r['status'],'insufficient_evidence')
        self.assertTrue(r['gaps'])

    def test_09_config_destination_change_revokes_remote_consent(self):
        self.settings.save({'base_url':'https://first.invalid/v1','allow_remote':True})
        self.settings.save({'base_url':'https://second.invalid/v1'})
        self.assertFalse(self.settings.public()['allow_remote'])

    def test_10_change_outbox_transaction_and_idempotent_enqueue(self):
        with core.connect() as c:
            before=c.execute('SELECT count(*) FROM kb_changes').fetchone()[0]
        try:
            with core.connect() as c:
                c.execute("UPDATE objects SET title='rollback' WHERE id=?",(self.job['owner_id'],))
                raise RuntimeError('rollback')
        except RuntimeError:
            pass
        with core.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM kb_changes').fetchone()[0],before)
        enqueue(core)
        with core.connect() as c:
            n=c.execute('SELECT count(*) FROM kp_index_requests').fetchone()[0]
        enqueue(core)
        with core.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM kp_index_requests').fetchone()[0],n)

    def test_11_outbound_payload_has_no_unrelated_object_metadata(self):
        self.settings.save({'base_url':'https://fixture.invalid/v1','allow_remote':True})
        self.client.post('/api/library/files/'+self.file_id+'/policy',json={'allowed':True,'file_hash':self.file_hash})
        seen=[]
        def handle(request):
            body=json.loads(request.content);seen.append(body)
            value={'claims':[{'text':'有出处的回答','evidence_ids':['E1']}],'gaps':[]} if len(seen)==1 else {'checks':[{'id':'0','support':'supported'}]}
            return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(value)}}]})
        original=httpx.Client
        with patch('app.workbench.httpx.Client',side_effect=lambda **kw:original(transport=httpx.MockTransport(handle),**kw)):
            r=self.client.post('/api/workbench/ask',json={'query':'铝合金'}).json()
        self.assertEqual(r['status'],'answered',r)
        payload=json.loads(seen[0]['messages'][1]['content'])
        self.assertNotIn('objects',payload)
        self.assertEqual(set(payload['evidence'][0]),{'id','quote','page','attribute'})
        with core.connect() as c:
            self.assertTrue(c.execute('SELECT 1 FROM answer_dependencies WHERE run_id=?',(r['run_id'],)).fetchone())

    def test_12_publication_requires_graph_and_vectors(self):
        worker=Mock()
        worker.call.side_effect=lambda path: {'status':'ready','revision':'1'}
        with patch.object(core,'EMBEDDINGS',worker), patch.object(core,'semantic_consistency_after_build',return_value={'status':'stale'}), patch.object(core,'semantica_rebuild',return_value={'status':'unavailable'}):
            result=pipeline.refresh_indexes()
        self.assertEqual(result['status'],'blocked')
        self.assertNotIn('/v2/activate',[x.args[0] for x in worker.call.call_args_list])

    def test_13_history_retains_snapshot_but_marks_changed_source_stale(self):
        self.settings.save({'base_url':'http://127.0.0.1:9999/v1'})
        with patch.object(AnswerModel,'complete',side_effect=ValueError('fixture unavailable')):
            r=self.client.post('/api/workbench/ask',json={'query':'铝合金'}).json()
        endpoint='/api/agent/runs/'+r['run_id']
        before=self.client.get(endpoint).json()
        self.assertEqual(before['source_state'],'current')
        with core.connect() as c:
            original=c.execute('SELECT hash FROM objects WHERE id=?',(self.job['owner_id'],)).fetchone()[0]
            c.execute('UPDATE objects SET hash=? WHERE id=?',('changed-fixture',self.job['owner_id']))
        try:
            after=self.client.get(endpoint).json()
            self.assertEqual(after['source_state'],'stale')
            self.assertEqual(before['evidence_pack'],after['evidence_pack'])
        finally:
            with core.connect() as c:c.execute('UPDATE objects SET hash=? WHERE id=?',(original,self.job['owner_id']))


if __name__=='__main__':unittest.main(verbosity=2)
