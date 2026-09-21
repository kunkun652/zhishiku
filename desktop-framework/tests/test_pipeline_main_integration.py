"""Real production app integration. Only the model runtime is a declared fixture."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SPACE = tempfile.TemporaryDirectory(prefix='zh-pipeline-http-')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
# Importing fixture helpers itself selects an isolated root before importing main.
from test_knowledge_pipeline import FixtureRuntime, TEXT, UnavailableEmbeddings
from fastapi.testclient import TestClient
from app.service import app, core, pipeline

class MainIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pipeline.runtime = FixtureRuntime()
        core.EMBEDDINGS = UnavailableEmbeddings()
        cls.client = TestClient(app)
        cls.job = pipeline.import_bytes(TEXT.encode(), 'main-integration.txt')
        cls.job = pipeline.process(cls.job['id'])
    @classmethod
    def tearDownClass(cls):
        pipeline.close()
        cls.client.close()
        SPACE.cleanup()
    def test_01_shared_database_and_legacy_search(self):
        self.assertEqual(self.job['status'], 'review_pending', self.job['error'])
        health = self.client.get('/api/health')
        self.assertEqual(health.status_code, 200)
        self.assertTrue(health.json()['agent_path_wired'])
        self.assertFalse(health.json()['agent_connected'])
        self.assertEqual(self.client.get('/knowledge-pipeline').status_code, 200)
        result = self.client.get('/api/search', params={'q': '机翼盒段', 'mode': 'keyword'}).json()
        self.assertTrue(result['items'])
    def test_02_real_validation_and_graph(self):
        j = pipeline.review(self.job['id'], [x['id'] for x in self.job['candidates']], [], 'integration-test', 'synthetic reference adoption')
        self.assertEqual(j['status'], 'reviewed')
        result = self.client.get('/api/graph', params={'full': True}).json()
        self.assertTrue(any(x['type'] == '采用材料' for x in result['edges']))
        self.assertEqual(len(result['nodes']), 3)
    def test_03_agent_uses_existing_three_channel_retriever(self):
        with patch.object(core, 'search', wraps=core.search) as search:
            result = self.client.post('/api/agent/ask', json={'query': '机翼盒段'})
            self.assertEqual(result.status_code, 200, result.text)
            answer = result.json()
            self.assertEqual(answer['status'], 'answered', answer)
            self.assertEqual(search.call_args.kwargs['graph_backend'], 'semantica')
            self.assertEqual(search.call_args.kwargs['mode'], 'hybrid')
            self.assertFalse(answer['solver_executed'])
            self.assertTrue(answer['evidence_pack']['retrieval']['degradations'])
            record = self.client.get('/api/agent/runs/' + answer['run_id']).json()
            self.assertEqual(record['evidence_pack']['hash'], answer['evidence_pack']['hash'])
    def test_04_cross_site_writes_blocked(self):
        response = self.client.post('/api/agent/ask', json={'query': '机翼盒段'}, headers={'Origin': 'https://evil.invalid'})
        self.assertEqual(response.status_code, 403)
    def test_05_invalid_api_input_is_not_accepted(self):
        self.assertEqual(self.client.post('/api/retrieve', json={'query': '', 'top_k': 100}).status_code, 422)

if __name__ == '__main__': unittest.main(verbosity=2)
