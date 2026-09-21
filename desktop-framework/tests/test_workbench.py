"""Workbench contracts on synthetic data; HTTP model outputs are explicit fixtures."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from test_knowledge_pipeline import FixtureRuntime, TEXT, UnavailableEmbeddings
from app.service import app, core, pipeline
from app.workbench import ModelSettings, AnswerModel, protect_key


class WorkbenchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.client.headers['Authorization'] = 'Bearer ' + app.state.access.owner_token
        cls.settings = ModelSettings(core.ROOT)
        pipeline.runtime = FixtureRuntime()
        core.EMBEDDINGS = UnavailableEmbeddings()
        cls.job = pipeline.import_bytes(TEXT.encode(), '机翼试验报告.txt')
        with core.connect() as c:
            c.execute("UPDATE sources SET category='结构试验' WHERE file_id=?", (cls.job['file_id'],))
        material = core.save({'type': 'material', 'title': '资料页不应出现的材料卡', 'data': {}})
        model = core.save({'type': 'model', 'title': '资料页不应出现的模型', 'data': {}})
        with core.connect() as c:
            for obj in (material, model):
                c.execute('INSERT INTO files VALUES(?,?,?,?,?,?)', (obj['id'], obj['id'], obj['title']+'.txt', 'fixture', 10, 'assets/fixture.txt'))

    @classmethod
    def tearDownClass(cls):
        pipeline.close()
        cls.client.close()

    def test_01_file_library_excludes_cards_models(self):
        result = self.client.get('/api/library/files').json()
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['items'][0]['name'], '机翼试验报告.txt')
        self.assertEqual(result['categories'], [{'category': '结构试验', 'count': 1}])
        self.assertEqual(self.client.get('/api/library/files?q=试验').json()['total'], 1)
        self.assertEqual(self.client.get('/api/library/files?category=未知').json()['total'], 0)
        self.assertEqual(self.client.get('/api/library/files?offset=40').json()['items'], [])
        self.assertEqual(self.client.get('/api/library/files?limit=1000').status_code, 422)

    def test_02_key_is_encrypted_and_never_returned(self):
        self.assertEqual(protect_key(protect_key('fixture-key'), decrypt=True), 'fixture-key')
        r = self.client.post('/api/workbench/settings', json={'base_url': 'http://127.0.0.1:34567/v1', 'model': 'fixture-model', 'api_key': 'fixture-secret', 'thinking': 'high'})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()['has_api_key'])
        self.assertNotIn('fixture-secret', r.text)
        self.assertNotIn('fixture-secret', self.settings.path.read_text('utf-8'))
        self.client.post('/api/workbench/settings', json={'model': 'fixture-2', 'api_key': ''})
        self.assertTrue(self.client.get('/api/workbench/settings').json()['has_api_key'])

    def test_03_reject_unsafe_or_invalid_settings(self):
        for body in ({'base_url':'http://remote.invalid/v1'}, {'base_url':'https://key:secret@host.invalid/v1'}, {'thinking':'arbitrary'}, {'api_key':'x\ny'}):
            self.assertEqual(self.client.post('/api/workbench/settings', json=body).status_code, 422)
        self.assertEqual(self.client.post('/api/workbench/settings', json={}, headers={'Origin':'https://evil.invalid'}).status_code, 403)

    def test_04_real_http_contract_and_citation_validation(self):
        seen = []
        def handle(request):
            seen.append((str(request.url), json.loads(request.content), dict(request.headers)))
            if len(seen) == 2:
                return httpx.Response(200, json={'choices':[{'message':{'content':json.dumps({'checks':[{'id':'0','support':'supported'}]})}}]})
            return httpx.Response(200, json={'choices':[{'message':{'content':json.dumps({'claims':[{'text':'铝合金弹性模量为70 GPa。','evidence_ids':['E1']}], 'gaps':[]})}}]})
        original = httpx.Client
        with patch('app.workbench.httpx.Client', side_effect=lambda **kw:original(transport=httpx.MockTransport(handle), **kw)):
            result = self.client.post('/api/workbench/ask', json={'query':'铝合金'}).json()
        self.assertEqual(result['status'], 'answered', result)
        self.assertTrue(result['evidence_pack']['evidence'])
        self.assertEqual(seen[0][0], 'http://127.0.0.1:34567/v1/chat/completions')
        self.assertEqual(seen[0][1]['reasoning_effort'], 'high')
        self.assertEqual(seen[0][2]['authorization'], 'Bearer fixture-secret')
        self.assertFalse(result['engineering_approved'])
        self.assertEqual(len(seen), 2)
        self.assertEqual(result['claims'][0]['support'], 'model_checked')
        self.assertTrue(self.client.get('/api/agent/runs/'+result['run_id']).json()['evidence_pack'])

    def test_05_bad_citations_are_not_shown_as_answer(self):
        with patch.object(AnswerModel, 'complete', return_value=(json.dumps({'claims':[{'text':'不存在的结论','evidence_ids':['invented']}], 'gaps':[]}), 'fixture')):
            result=self.client.post('/api/workbench/ask', json={'query':'铝合金'}).json()
        self.assertEqual(result['claims'], [])
        self.assertEqual(result['status'], 'model_unavailable_or_rejected')

    def test_06_settings_test_and_key_clear(self):
        with patch.object(AnswerModel, 'complete', return_value=('连接成功','fixture')):
            self.assertEqual(self.client.post('/api/workbench/test-model').json()['status'], 'connected')
        self.client.post('/api/workbench/settings',json={'clear_key':True})
        self.assertFalse(self.client.get('/api/workbench/settings').json()['has_api_key'])

    def test_07_removed_ui_entry_redirects_and_cae_catalog(self):
        self.assertEqual(self.client.get('/knowledge-pipeline',follow_redirects=False).headers['location'], '/#home')
        html = self.client.get('/').text
        self.assertNotIn('知识加工与问答', html)
        catalog=self.client.get('/api/workbench/capabilities').json()
        self.assertEqual(len(catalog['skills']),2)
        self.assertEqual(len(catalog['tools']),68)
        self.assertTrue(all(t['source'] and t['sha256'] for t in catalog['tools']))

    def test_08_background_processing_is_not_human_review(self):
        j = pipeline.manage(self.job['id'])
        pipeline.manage_pending()
        for future in list(pipeline.futures.values()):
            future.result(timeout=5)
        pipeline.manage_pending()
        self.assertEqual(pipeline.job(j['id'])['status'], 'reviewed')
        with core.connect() as c:
            reviewers=[r[0] for r in c.execute('SELECT reviewer FROM kp_reviews')]
            status=[r[0] for r in c.execute("SELECT o.status FROM objects o JOIN kp_candidates k ON k.object_id=o.id WHERE k.kind='entity'")]
        self.assertTrue(reviewers and all(x=='AI / 来源校验' for x in reviewers))
        self.assertTrue(status and all(x=='candidate' for x in status))

    def test_09_unconfigured_background_retains_original(self):
        pipeline.runtime.configured=False
        j=pipeline.manage(pipeline.import_bytes(b'fixture source waiting for model', 'waiting.txt')['id'])
        pipeline.manage_pending()
        state=self.client.get('/api/assistant/jobs').json()['items']
        self.assertEqual(next(x for x in state if x['job_id']==j['id'])['status'],'waiting_model')
        self.assertTrue(core.asset(j['file_id'])[1].exists())
        pipeline.runtime.configured=True

if __name__ == '__main__':
    unittest.main(verbosity=2)
