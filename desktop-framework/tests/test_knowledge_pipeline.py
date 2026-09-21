"""Production SQLite/FTS5/retrieval contracts; model calls are explicit fixtures.
Run this file in its own process. It forces temporary data roots, never business data.
This does NOT certify real Semantica, Ollama, BGE-M3, or the Windows EXE.
"""
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

SPACE = tempfile.TemporaryDirectory(prefix='zh-pipeline-tests-')
os.environ['ZH_DATA_ROOT'] = SPACE.name
os.environ.pop('ZH_EMBEDDING_PYTHON', None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from app import main as core
from app.knowledge_pipeline.pipeline import Pipeline
from app.knowledge_pipeline.evidence import EvidenceService
from app.knowledge_pipeline.contracts import validate_extraction, validate_answer
from app.knowledge_pipeline.parsers import parse

SEED = Path(SPACE.name) / 'empty.sqlite3'
with core.connect() as source, sqlite3.connect(SEED) as destination:
    source.backup(destination)
TEXT = '机翼盒段采用铝合金。铝合金的弹性模量为70 GPa。'


def sample(text=TEXT):
    value = '72' if '72' in text else '70'
    return {'entities': [
        {'key': 'wing', 'kind': 'model', 'name': '机翼盒段', 'quote': '机翼盒段采用铝合金', 'attributes': []},
        {'key': 'alloy', 'kind': 'material', 'name': '铝合金', 'quote': f'铝合金的弹性模量为{value} GPa',
         'attributes': [{'name': '弹性模量', 'value': value, 'unit': 'GPa', 'context': '', 'quote': f'弹性模量为{value} GPa'}]}],
        'relations': [{'source': 'wing', 'target': 'alloy', 'kind': '采用材料', 'quote': '机翼盒段采用铝合金'}]}


class FixtureRuntime:
    """A deterministic fixture, never described as a real model result."""
    def __init__(self):
        self.calls = []
        self.fail = None
        self.bad_citation = False
        self.on_answer = None
        self.empty = False
        self.configured = True
    def status(self):
        return {'configured': self.configured, 'model': 'TEST_FIXTURE', 'last_probe': {'status': 'not_probed'}}
    def call(self, action, body):
        self.calls.append(action)
        if action == self.fail:
            raise RuntimeError('explicit fixture failure')
        if action == 'extract':
            data = {'entities': [], 'relations': []} if self.empty else sample(body['text'])
            return {**data, 'model': 'TEST_FIXTURE', 'model_digest': 'fixture-digest', 'graph_hash': 'fixture-only', 'semantica_version': 'fixture-only'}
        if action == 'conflicts':
            groups = {}
            for fact in body['facts']:
                groups.setdefault(fact['id'], set()).add(fact['value'])
            return {'conflicts': [{'entity_id': key, 'conflicting_values': sorted(values), 'sources': []} for key, values in groups.items() if len(values) > 1], 'semantica_version': 'fixture-only'}
        if action == 'answer':
            if self.on_answer:
                self.on_answer()
            return {'claims': [{'text': '机翼盒段采用铝合金；仅供资料参考。', 'evidence_ids': ['invented' if self.bad_citation else body['evidence_pack']['evidence'][0]['id']]}],
                    'gaps': [], 'model': 'TEST_FIXTURE', 'semantica_version': 'fixture-only'}
        if action == 'probe':
            return {'status': 'ready', 'model': 'TEST_FIXTURE', 'semantica_version': 'fixture-only'}
        raise ValueError(action)


class UnavailableEmbeddings:
    def call(self, *args):
        raise RuntimeError('test: actual embedding model not installed')
    def status(self):
        return {'status': 'unavailable', 'indexed': 0}
    def close(self):
        pass


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='zh-pipeline-case-')
        core.ROOT = Path(self.temp.name)
        core.DB = core.ROOT / 'knowledge.sqlite3'
        shutil.copy2(SEED, core.DB)
        core.EMBEDDINGS = UnavailableEmbeddings()
        self.runtime = FixtureRuntime()
        self.pipeline = Pipeline(core, self.runtime)
    def tearDown(self):
        self.pipeline.close()
        self.temp.cleanup()
    def count(self, table):
        with core.connect() as c:
            return c.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
    def revision(self):
        with core.connect() as c:
            return c.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0]
    def prepared(self, text=TEXT):
        j = self.pipeline.import_bytes(text.encode(), 'wing.txt')
        j = self.pipeline.process(j['id'])
        self.assertEqual(j['status'], 'review_pending', j['error'])
        return j
    def adopted(self):
        j = self.prepared()
        return self.pipeline.review(j['id'], [c['id'] for c in j['candidates']], [], 'fixture reviewer', 'fixture source check')
    def test_01_upload_dedup_is_revision_idempotent(self):
        a = self.pipeline.import_bytes(TEXT.encode(), '../wing.txt')
        revision = self.revision()
        b = self.pipeline.import_bytes(TEXT.encode(), 'renamed.txt')
        self.assertEqual(a['id'], b['id'])
        self.assertEqual(self.revision(), revision)
        self.assertEqual((self.count('files'), self.count('objects'), self.count('kp_jobs')), (1, 1, 1))
    def test_02_raw_text_enters_actual_fts(self):
        self.pipeline.import_bytes(TEXT.encode(), 'wing.txt')
        with core.connect() as c:
            self.assertGreater(c.execute("SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH ?", ('"铝合"',)).fetchone()[0], 0)
    def test_03_extraction_is_review_gated(self):
        j = self.prepared()
        self.assertEqual(self.count('objects'), 1)
        self.assertEqual(self.count('relations'), 0)
        self.assertEqual(len(j['candidates']), 3)
        self.assertIsNone(j['candidates'][0]['payload']['confidence'])
    def test_04_atomic_review_connects_authority_graph(self):
        j = self.adopted()
        self.assertEqual(j['status'], 'reviewed')
        self.assertEqual((self.count('objects'), self.count('relations'), self.count('kp_facts')), (3, 3, 1))
        self.assertGreater(self.count('kp_index_requests'), 0)
        with core.connect() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM objects WHERE status='reviewed'").fetchone()[0], 0)
            material = core.record(c.execute("SELECT * FROM objects WHERE type='material'").fetchone())
            self.assertEqual(material['data']['properties'][0]['value'], 70)
    def test_05_relation_without_endpoints_rolls_back(self):
        j = self.prepared()
        edge = next(c for c in j['candidates'] if c['kind'] == 'relation')
        with self.assertRaises(ValueError):
            self.pipeline.review(j['id'], [edge['id']], [], 'r', 'checked')
        self.assertEqual(self.count('objects'), 1)
        self.assertEqual(self.count('kp_reviews'), 0)
    def test_06_repeat_review_rejected(self):
        j = self.adopted()
        with self.assertRaises(ValueError):
            self.pipeline.review(j['id'], [j['candidates'][0]['id']], [], 'r', 'again')
    def test_07_reviewer_and_note_required(self):
        j = self.prepared()
        with self.assertRaises(ValueError):
            self.pipeline.review(j['id'], [j['candidates'][0]['id']], [], '', '')
    def test_08_conflicts_not_silently_resolved(self):
        self.adopted()
        j = self.prepared(TEXT.replace('70', '72'))
        bad = next(c for c in j['candidates'] if c['conflicts'])
        with self.assertRaises(ValueError):
            self.pipeline.review(j['id'], [bad['id']], [], 'r', 'check')
        j = self.pipeline.review(j['id'], [bad['id']], [], 'r', 'retain as conflict', True)
        oid = next(c['object_id'] for c in j['candidates'] if c['id'] == bad['id'])
        with core.connect() as c:
            self.assertEqual(c.execute('SELECT status FROM objects WHERE id=?', (oid,)).fetchone()[0], 'conflict')
    def test_09_source_tamper_blocks_review(self):
        j = self.prepared()
        _, path = core.asset(j['file_id'])
        path.write_bytes(b'tampered')
        with self.assertRaises(Exception):
            self.pipeline.review(j['id'], [c['id'] for c in j['candidates']], [], 'r', 'check')
        self.assertEqual(self.count('objects'), 1)
    def test_10_chunk_tamper_blocks_review(self):
        j = self.prepared()
        with core.connect() as c:
            c.execute("UPDATE chunks SET text='changed'")
        with self.assertRaises(ValueError):
            self.pipeline.review(j['id'], [c['id'] for c in j['candidates']], [], 'r', 'check')
    def test_11_changed_owner_has_new_processing_version(self):
        a = self.pipeline.import_bytes(TEXT.encode(), 'wing.txt')
        with core.connect() as c:
            c.execute("UPDATE objects SET hash='new-hash' WHERE id=?", (a['owner_id'],))
        b = self.pipeline.submit_file(a['file_id'])
        self.assertNotEqual(a['id'], b['id'])
    def test_12_extraction_failure_and_retry(self):
        j = self.pipeline.import_bytes(TEXT.encode(), 'wing.txt')
        self.runtime.fail = 'extract'
        j = self.pipeline.process(j['id'])
        self.assertEqual(j['status'], 'failed')
        self.assertEqual(self.count('files'), 1)
        self.assertEqual(self.count('kp_candidates'), 0)
        self.runtime.fail = None
        self.assertEqual(self.pipeline.process(j['id'])['status'], 'review_pending')
    def test_13_retry_reuses_segment_checkpoint(self):
        j = self.pipeline.import_bytes(TEXT.encode(), 'wing.txt')
        self.runtime.fail = 'conflicts'
        self.pipeline.process(j['id'])
        self.runtime.fail = None
        j = self.pipeline.process(j['id'])
        self.assertEqual(j['status'], 'review_pending')
        self.assertEqual(self.runtime.calls.count('extract'), 1)
    def test_14_no_fake_index_readiness(self):
        self.adopted()
        state = self.pipeline.refresh_indexes()
        self.assertEqual(state['status'], 'blocked')
        self.assertEqual(state['embedding']['status'], 'unavailable')
        self.assertEqual(state['graph']['status'], 'unavailable')
    def test_15_production_retriever_returns_source_hashes(self):
        self.adopted()
        pack = EvidenceService(self.pipeline).retrieve('铝合金')
        self.assertTrue(pack['evidence'])
        self.assertTrue(all(e['file_hash'] for e in pack['evidence']))
        self.assertIn('keyword', pack['retrieval']['channels'])
        self.assertNotEqual(pack['embedding']['status'], 'ready')
    def test_16_agent_is_readonly_and_recorded(self):
        self.adopted()
        count = self.count('objects')
        result = EvidenceService(self.pipeline).ask('机翼盒段')
        self.assertEqual(result['status'], 'answered', result['gaps'])
        self.assertFalse(result['solver_executed'])
        self.assertEqual(self.count('objects'), count)
        self.assertEqual(self.count('kp_agent_runs'), 1)
    def test_17_agent_rejects_invented_citation(self):
        self.adopted()
        self.runtime.bad_citation = True
        result = EvidenceService(self.pipeline).ask('机翼盒段')
        self.assertEqual(result['status'], 'model_unavailable_or_rejected')
        self.assertEqual(result['claims'], [])
    def test_18_no_evidence_no_model_call(self):
        result = EvidenceService(self.pipeline).ask('不存在的资料')
        self.assertEqual(result['status'], 'insufficient_evidence')
        self.assertNotIn('answer', self.runtime.calls)
    def test_19_revision_change_during_generation(self):
        self.adopted()
        def update():
            with core.connect() as c: core.revision(c)
        self.runtime.on_answer = update
        self.assertEqual(EvidenceService(self.pipeline).ask('机翼盒段')['status'], 'model_unavailable_or_rejected')
    def test_20_file_tamper_during_generation(self):
        j = self.adopted()
        _, path = core.asset(j['file_id'])
        self.runtime.on_answer = lambda: path.write_bytes(b'changed during generation')
        self.assertEqual(EvidenceService(self.pipeline).ask('机翼盒段')['status'], 'model_unavailable_or_rejected')
    def test_21_noise_exclusion_blocks_review_and_answer(self):
        j = self.prepared()
        # Keep real filter_vectors/get/classify functions, replacing only the predicate.
        with patch.object(core.content_quality, 'eligible', return_value=False):
            with self.assertRaises(ValueError):
                self.pipeline.review(j['id'], [x['id'] for x in j['candidates']], [], 'r', 'check')
            self.assertEqual(EvidenceService(self.pipeline).ask('机翼盒段')['status'], 'insufficient_evidence')
    def test_22_changed_endpoint_blocks_old_relation(self):
        j = self.prepared()
        ids = [x['id'] for x in j['candidates'] if x['kind'] == 'entity']
        j = self.pipeline.review(j['id'], ids, [], 'r', 'partial review')
        oid = next(x['object_id'] for x in j['candidates'] if x['kind'] == 'entity')
        with core.connect() as c: c.execute("UPDATE objects SET hash='changed',version=2 WHERE id=?", (oid,))
        ids = [x['id'] for x in j['candidates'] if x['kind'] == 'relation']
        with self.assertRaises(ValueError): self.pipeline.review(j['id'], ids, [], 'r', 'check')
    def test_23_conflict_filter_rejected(self):
        with self.assertRaises(ValueError): EvidenceService(self.pipeline).retrieve('x', filters={'status': 'conflict'})
    def test_24_topk_validated(self):
        for k in (0, 21, True, '10'):
            with self.assertRaises(ValueError): EvidenceService(self.pipeline).retrieve('x', top_k=k)
    def test_25_unconfigured_runtime_does_not_queue(self):
        j = self.pipeline.import_bytes(TEXT.encode(), 'wing.txt')
        self.runtime.configured = False
        with self.assertRaises(RuntimeError): self.pipeline.queue(j['id'])
        self.assertEqual(self.pipeline.job(j['id'])['status'], 'parsed')
    def test_26_empty_extraction_is_explicit(self):
        j = self.pipeline.import_bytes(TEXT.encode(), 'wing.txt')
        self.runtime.empty = True
        self.assertEqual(self.pipeline.process(j['id'])['status'], 'no_candidates')
        self.assertEqual(self.count('objects'), 1)
    def test_27_reject_foreign_candidate(self):
        j = self.prepared()
        with self.assertRaises(ValueError): self.pipeline.review(j['id'], ['foreign'], [], 'r', 'check')
        self.assertEqual(self.count('kp_reviews'), 0)


class ContractTests(unittest.TestCase):
    def test_28_good_extraction(self):
        self.assertEqual(len(validate_extraction(sample(), TEXT)['entities']), 2)
    def test_29_invented_quote(self):
        data = sample(); data['entities'][0]['quote'] = 'invented'
        with self.assertRaises(ValueError): validate_extraction(data, TEXT)
    def test_30_invented_material_name(self):
        data = sample(); data['entities'][1]['name'] = 'AL7075'
        with self.assertRaises(ValueError): validate_extraction(data, TEXT)
    def test_31_numeric_substring(self):
        data = sample(); data['entities'][1]['attributes'][0]['value'] = '7'
        with self.assertRaises(ValueError): validate_extraction(data, TEXT)
    def test_32_wrong_unit(self):
        data = sample(); data['entities'][1]['attributes'][0]['unit'] = 'Pa'
        with self.assertRaises(ValueError): validate_extraction(data, TEXT)
    def test_33_dangling_relation(self):
        data = sample(); data['relations'][0]['target'] = 'missing'
        with self.assertRaises(ValueError): validate_extraction(data, TEXT)
    def test_34_answer_needs_citation(self):
        with self.assertRaises(ValueError): validate_answer({'claims': [{'text': 'fact', 'evidence_ids': []}], 'gaps': []}, {'E1'})
    def test_35_bdf_include_blocked(self):
        with self.assertRaises(ValueError): parse(b"INCLUDE 'C:/secret/file.bdf'", 'x.bdf')
    def test_36_docx_positions_are_not_pages(self):
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, 'w') as z:
            z.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>机翼报告</w:t></w:r></w:p></w:body></w:document>')
        result = parse(raw.getvalue(), 'x.docx')
        self.assertEqual(result['segments'][0]['page'], 0)
        self.assertEqual(result['segments'][0]['text'], '机翼报告')
    def test_37_long_text_tail_preserved(self):
        raw = ('a' * 4000 + '末尾证据').encode()
        self.assertEqual(''.join(s['text'] for s in parse(raw, 'long.txt')['segments']), raw.decode())
    def test_38_invalid_inputs_rejected(self):
        for raw, name in ((b'', 'empty.txt'), (b'abc', 'run.exe')):
            with self.assertRaises(ValueError): parse(raw, name)


if __name__ == '__main__':
    unittest.main(verbosity=2)
