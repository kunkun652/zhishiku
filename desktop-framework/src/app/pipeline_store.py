"""Transactional staging and review in the existing SQLite authority database.

Acceptance means source-level review, never engineering approval. Original assets
are immutable; only registered file IDs are accepted by the processing service.
"""
from __future__ import annotations
import hashlib
import json
import math
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

from . import pipeline_parsers as parsers
from .pipeline_extraction import REVISION
from .pipeline_runtime import SemanticaWorker, Ollama, llm_config


def dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def key(value) -> str:
    return hashlib.sha256(dump(value).encode()).hexdigest()


class Pipeline:
    def __init__(self, backend, worker=None):
        self.b = backend
        self.worker = worker or SemanticaWorker(backend.ROOT)
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='knowledge-ingest')
        self.futures = {}
        self.guard = threading.Lock()
        with self.b.connect() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS pipeline_jobs(
              id TEXT PRIMARY KEY,file_id TEXT NOT NULL,file_hash TEXT NOT NULL,config TEXT NOT NULL,
              state TEXT NOT NULL,detail TEXT NOT NULL,error TEXT NOT NULL,owner_pid INTEGER,
              created TEXT NOT NULL,updated TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS pipeline_segments(
              key TEXT PRIMARY KEY,file_id TEXT NOT NULL,file_hash TEXT NOT NULL,chunk_id INTEGER NOT NULL,
              page INTEGER,locator TEXT NOT NULL,start INTEGER,end INTEGER,text_hash TEXT NOT NULL,parser TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS pipeline_candidates(
              id TEXT PRIMARY KEY,job_id TEXT NOT NULL,payload TEXT NOT NULL,evidence TEXT NOT NULL,
              status TEXT NOT NULL,object_id TEXT,object_hash TEXT,reviewer TEXT,note TEXT,updated TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS pipeline_candidates_job ON pipeline_candidates(job_id,status);
            CREATE INDEX IF NOT EXISTS pipeline_candidates_object ON pipeline_candidates(object_id);
            CREATE TABLE IF NOT EXISTS pipeline_reviews(
              id INTEGER PRIMARY KEY,candidate_id TEXT NOT NULL,action TEXT NOT NULL,
              reviewer TEXT NOT NULL,note TEXT NOT NULL,created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS pipeline_conflicts(
              id TEXT PRIMARY KEY,left_id TEXT NOT NULL,right_id TEXT NOT NULL,kind TEXT NOT NULL,
              detail TEXT NOT NULL,status TEXT NOT NULL,note TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS pipeline_agent_runs(
              id TEXT PRIMARY KEY,query TEXT NOT NULL,result TEXT NOT NULL,created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS pipeline_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            INSERT OR IGNORE INTO pipeline_meta VALUES('schema','1');
            ''')
            for row in c.execute("SELECT id,owner_pid FROM pipeline_jobs WHERE state IN ('queued','parsing','extracting')").fetchall():
                try:
                    if row['owner_pid']:
                        os.kill(row['owner_pid'], 0)
                        continue
                except (OSError, ProcessLookupError):
                    pass
                c.execute("UPDATE pipeline_jobs SET state='interrupted',error='处理进程已结束，可按原文件重试' WHERE id=?", (row['id'],))

    def close(self):
        self.pool.shutdown(wait=False, cancel_futures=True)

    def _put_object(self, c, body, oid=None, old=None):
        kind, title, data = self.b.validate(body)
        oid = oid or str(uuid.uuid4())
        item = {'id': oid, 'type': kind, 'title': title, 'version': old['version'] + 1 if old else 1,
                'status': body.get('status', 'candidate'), 'data': data, 'updated': self.b.now()}
        item['hash'] = self.b.digest({k: v for k, v in item.items() if k != 'updated'})
        c.execute('INSERT OR REPLACE INTO objects VALUES(?,?,?,?,?,?,?,?)',
                  (oid, kind, title, item['version'], item['status'], self.b.encoded(data), item['hash'], item['updated']))
        c.execute('INSERT INTO versions VALUES(?,?,?)', (oid, item['version'], self.b.encoded(item)))
        return item

    def upload(self, raw: bytes, filename: str):
        name = Path(filename.replace('\\', '/')).name
        ext = Path(name).suffix.lower()
        if ext not in parsers.SUPPORTED or not raw or len(raw) > parsers.MAX_BYTES or len(name) > 240:
            raise ValueError('文件格式、名称或大小不符合要求（20 MiB 上限）')
        sha = hashlib.sha256(raw).hexdigest()
        folder = self.b.ROOT / 'assets'
        folder.mkdir(exist_ok=True)
        path = folder / (sha + ext)
        with self.b.LOCK, self.b.connect() as c:
            existing = c.execute('SELECT * FROM files WHERE sha256=? AND lower(name) LIKE ? LIMIT 1', (sha, '%' + ext)).fetchone()
            if existing:
                actual, _ = self.b.asset(existing['id'])
                return {**dict(actual), 'reused': True}
            # Exclusive create: a pre-existing hash path must match, never overwrite it.
            try:
                with path.open('xb') as stream:
                    stream.write(raw)
            except FileExistsError:
                if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                    raise ValueError('受管目录存在同名但哈希不符的文件，拒绝覆盖')
            obj = self._put_object(c, {'type': 'document', 'title': name, 'status': 'candidate',
                                      'data': {'source': name, 'extraction_status': '待处理',
                                               'limitations': '资料尚未完成知识抽取与工程复核'}})
            fid = str(uuid.uuid4())
            c.execute('INSERT INTO files VALUES(?,?,?,?,?,?)',
                      (fid, obj['id'], name, sha, len(raw), str(path.relative_to(self.b.ROOT))))
            self.b.revision(c)
        return {'id': fid, 'object_id': obj['id'], 'name': name, 'sha256': sha, 'size': len(raw), 'reused': False}

    def start(self, fid: str, mode: str = 'regex', synchronous: bool = False):
        if mode not in {'regex', 'llm'}:
            raise ValueError('抽取模式必须为 regex 或 llm')
        file, _ = self.b.asset(fid)
        if file['size'] > parsers.MAX_BYTES:
            raise ValueError('文件超过本轮 20 MiB 处理上限')
        engine = self.worker.status()
        if engine.get('status') != 'ready':
            raise RuntimeError(engine.get('message', 'Semantica 不可用'))
        model = llm_config() if mode == 'llm' else {}
        if mode == 'llm':
            state = Ollama().status()
            if state.get('status') != 'ready':
                raise RuntimeError('本地抽取模型不可用：' + dump(state))
            model['digest'] = state.get('digest')
        config = {'mode': mode, 'llm': model, 'adapter': REVISION, 'parser': parsers.VERSION,
                  'semantica_version': engine['semantica_version']}
        jid = key([fid, file['sha256'], config])
        with self.guard, self.b.connect() as c:
            old = c.execute('SELECT * FROM pipeline_jobs WHERE id=?', (jid,)).fetchone()
            if old and old['state'] not in {'failed', 'interrupted'}:
                return self.job(jid)
            if sum(not f.done() for f in self.futures.values()) >= 4:
                raise RuntimeError('已有 4 个待处理任务，请完成后再提交')
            stamp = self.b.now()
            c.execute('INSERT OR REPLACE INTO pipeline_jobs VALUES(?,?,?,?,?,?,?,?,?,?)',
                      (jid, fid, file['sha256'], dump(config), 'queued', '{}', '', os.getpid(),
                       old['created'] if old else stamp, stamp))
        if synchronous:
            self._process(jid)
        else:
            with self.guard:
                self.futures = {k: f for k, f in self.futures.items() if not f.done()}
                self.futures[jid] = self.pool.submit(self._process, jid)
        return self.job(jid)

    def job(self, jid):
        with self.b.connect() as c:
            row = c.execute('SELECT * FROM pipeline_jobs WHERE id=?', (jid,)).fetchone()
            if not row:
                raise KeyError('任务不存在')
            result = dict(row)
            result['detail'] = json.loads(result['detail'])
            result['config'] = json.loads(result['config'])
            result['counts'] = {r[0]: r[1] for r in c.execute('SELECT status,COUNT(*) FROM pipeline_candidates WHERE job_id=? GROUP BY status', (jid,))}
            return result

    def _state(self, jid, state, detail=None, error=''):
        with self.b.connect() as c:
            c.execute('UPDATE pipeline_jobs SET state=?,detail=?,error=?,updated=? WHERE id=?',
                      (state, dump(detail or {}), error[:2000], self.b.now(), jid))

    def _process(self, jid):
        try:
            job = self.job(jid)
            self._state(jid, 'parsing')
            file, path = self.b.asset(job['file_id'])
            if file['sha256'] != job['file_hash']:
                raise ValueError('任务对应的原件版本已变化')
            parsed = parsers.parse(path.read_bytes(), file['name'])
            from .retrieval import tokens
            with self.b.LOCK, self.b.connect() as c:
                new_chunks = 0
                for segment in parsed['segments']:
                    sid = key([file['id'], file['sha256'], parsed['parser'], segment['page'], segment['locator'],
                               segment['start'], segment['end'], segment['text_hash']])
                    segment['key'] = sid
                    old = c.execute('SELECT chunk_id FROM pipeline_segments WHERE key=?', (sid,)).fetchone()
                    if old:
                        segment['chunk_id'] = old[0]
                        row = c.execute('SELECT text FROM chunks WHERE id=?', (old[0],)).fetchone()
                        if not row or parsers.sha(row[0]) != segment['text_hash']:
                            raise ValueError('已登记片段被修改，请先核查原文与片段版本')
                        continue
                    cid = c.execute('INSERT INTO chunks(object_id,file_id,page,text) VALUES(?,?,?,?)',
                                    (file['object_id'], file['id'], segment['page'], segment['text'])).lastrowid
                    c.execute('INSERT INTO chunks_fts(rowid,tokens) VALUES(?,?)', (cid, tokens(segment['text'])))
                    c.execute('INSERT INTO pipeline_segments VALUES(?,?,?,?,?,?,?,?,?,?)',
                              (sid, file['id'], file['sha256'], cid, segment['page'], segment['locator'],
                               segment['start'], segment['end'], segment['text_hash'], parsed['parser']))
                    segment['chunk_id'] = cid
                    new_chunks += 1
                if new_chunks:
                    self.b.revision(c)
                    c.execute("INSERT OR REPLACE INTO pipeline_meta VALUES('indexes','dirty')")
            self._state(jid, 'extracting', {'segments': len(parsed['segments']), 'gaps': parsed['gaps']})
            output = self.worker.run({'segments': parsed['segments'], **job['config']})
            if (output.get('adapter') != REVISION or output.get('mode') != job['config']['mode']
                    or output.get('semantica_version') != job['config']['semantica_version']):
                raise ValueError('抽取产物与任务声明的组件版本不一致')
            candidates = output.get('candidates')
            if not isinstance(candidates, list) or len(candidates) > 25000:
                raise ValueError('抽取产物不符合候选列表契约')
            segments = {s['key']: s for s in parsed['segments']}
            actual, _ = self.b.asset(file['id'])
            if actual['sha256'] != job['file_hash']:
                raise ValueError('抽取期间原件版本变化')
            with self.b.LOCK, self.b.connect() as c:
                for candidate in candidates:
                    proof = candidate['evidence']
                    segment = segments.get(proof.get('segment_key'))
                    start, end = proof.get('start'), proof.get('end')
                    if (not segment or type(start) is not int or type(end) is not int
                            or not 0 <= start < end <= len(segment['text']) or segment['text'][start:end] != proof.get('quote')):
                        raise ValueError('抽取结果没有可核验的逐字原文位置')
                    if candidate.get('kind') not in {'entity', 'relation'} or not candidate.get('key'):
                        raise ValueError('抽取候选类型或标识不合法')
                    if len(candidate.get('title', '')) > 500 or not candidate.get('title', '').strip():
                        raise ValueError('候选标题为空或过长')
                    # Recheck stored text under the same write transaction.
                    current = c.execute('SELECT text FROM chunks WHERE id=?', (segment['chunk_id'],)).fetchone()
                    if not current or parsers.sha(current[0]) != segment['text_hash']:
                        raise ValueError('抽取期间正文片段已变化')
                    evidence = {**proof, 'file_id': file['id'], 'file_hash': file['sha256'],
                                'source_object_id': file['object_id'], 'chunk_id': segment['chunk_id'],
                                'chunk_hash': segment['text_hash'], 'page': segment['page'] or None,
                                'locator': segment['locator'], 'parent_start': segment['start'] + start,
                                'parent_end': segment['start'] + end, 'confidence': None}
                    cid = key([jid, candidate['key']])
                    payload = {**candidate, 'engine': output['semantica_version'], 'mode': output['mode']}
                    c.execute('INSERT OR IGNORE INTO pipeline_candidates VALUES(?,?,?,?,?,?,?,?,?,?)',
                              (cid, jid, dump(payload), dump(evidence), 'pending', None, None, '', '', self.b.now()))
                self._conflicts(c, jid)
            self._state(jid, 'awaiting_review', {'segments': len(segments), 'candidates': len(candidates),
                        'rejected_extractions': output.get('rejected', 0), 'gaps': parsed['gaps'],
                        'coverage': parsed['coverage'], 'scope': output.get('scope'),
                        'indexes': 'FTS5 原文已入索引；向量/派生图请使用更新索引入口'})
        except Exception as exc:
            self._state(jid, 'failed', error=str(exc))

    def _conflicts(self, c, jid):
        # Restrict identity to the same registered source; never merge materials by name.
        rows = c.execute("SELECT * FROM pipeline_candidates WHERE job_id=? AND status NOT IN ('rejected','revoked')", (jid,)).fetchall()
        groups = {}
        units = {'Pa': ('pressure', '1'), 'MPa': ('pressure', '1000000'), 'GPa': ('pressure', '1000000000'),
                 'N': ('force', '1'), 'kN': ('force', '1000'), 'm': ('length', '1'), 'mm': ('length', '.001')}
        expected = {'弹性模量': 'pressure', '载荷': 'force', '位移': 'length'}
        for row in rows:
            assertion = json.loads(row['payload']).get('assertion')
            if not assertion:
                continue
            dimension, factor = units[assertion['unit']]
            if dimension != expected.get(assertion['property']):
                cid = key([row['id'], 'unit_mismatch'])
                c.execute('INSERT OR IGNORE INTO pipeline_conflicts VALUES(?,?,?,?,?,?,?)',
                          (cid, row['id'], row['id'], 'unit_mismatch', '属性与单位量纲不符，禁止采纳', 'open', ''))
                continue
            normalized = Decimal(str(assertion['value'])) * Decimal(factor)
            group = (assertion['subject'], assertion['property'], dimension)
            for other, value in groups.get(group, []):
                if value != normalized:
                    left, right = sorted((row['id'], other))
                    cid = key([left, right, 'scope_review'])
                    c.execute('INSERT OR IGNORE INTO pipeline_conflicts VALUES(?,?,?,?,?,?,?)',
                              (cid, left, right, 'scope_review', '同一资料的同名属性数值不同；工况/温度/方向未明确，不直接判定工程矛盾', 'open', ''))
            groups.setdefault(group, []).append((row['id'], normalized))

    def list_candidates(self, jid='', status='', offset=0, limit=50):
        clauses, values = [], []
        for column, value in [('job_id', jid), ('status', status)]:
            if value:
                clauses.append(column + '=?')
                values.append(value)
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        with self.b.connect() as c:
            total = c.execute('SELECT COUNT(*) FROM pipeline_candidates' + where, values).fetchone()[0]
            rows = c.execute('SELECT * FROM pipeline_candidates' + where + ' ORDER BY rowid LIMIT ? OFFSET ?',
                             values + [max(1, min(limit, 100)), max(0, offset)]).fetchall()
            items = []
            for row in rows:
                item = dict(row)
                item['payload'], item['evidence'] = json.loads(item['payload']), json.loads(item['evidence'])
                item['conflicts'] = [dict(r) for r in c.execute('SELECT * FROM pipeline_conflicts WHERE left_id=? OR right_id=?', (item['id'], item['id']))]
                items.append(item)
        return {'items': items, 'total': total}

    def _validate_proof(self, c, evidence):
        file, _ = self.b.asset(evidence['file_id'])
        row = c.execute('SELECT text,file_id FROM chunks WHERE id=?', (evidence['chunk_id'],)).fetchone()
        if (file['sha256'] != evidence['file_hash'] or not row or row['file_id'] != file['id']
                or parsers.sha(row['text']) != evidence['chunk_hash']
                or row['text'][evidence['start']:evidence['end']] != evidence['quote']):
            raise ValueError('证据已经过期或原件校验失败，不能审核或引用旧候选')

    def _body(self, payload, evidence):
        label = payload.get('label')
        kind = {'MATERIAL': 'material', 'ELEMENT': 'mesh', 'ASSERTION': 'condition'}.get(label, 'term')
        data = {'source': f"file:{evidence['file_id']}；{evidence['locator']}",
                'summary': evidence['quote'], 'verification': '原文级人工采纳；不是工程验收',
                'limitations': '自动抽取候选经原文复核；适用性、单位制和边界条件仍需工程复核',
                'original_record': dump({'extraction': payload, 'provenance': evidence})}
        if kind == 'material':
            data['designation'] = payload['title']
        elif kind == 'mesh':
            data['element_type'] = payload['title']
        elif kind == 'term':
            data['definition'] = '原文提及：' + evidence['quote']
        else:
            data['loads' if payload['assertion']['property'] == '载荷' else 'summary'] = evidence['quote']
            data['units'] = payload['assertion']['unit']
        return {'type': kind, 'title': payload['title'], 'status': 'candidate', 'data': data}

    def review(self, ids: list[str], action: str, reviewer: str, note: str = '', conflict_note: str = ''):
        if not isinstance(ids, list) or not 1 <= len(ids) <= 100 or not all(isinstance(i, str) for i in ids):
            raise ValueError('每次审核需要 1–100 个候选 ID')
        if action not in {'accept', 'reject', 'revoke'} or not reviewer.strip() or len(reviewer) > 100 or len(note) > 4000 or len(conflict_note) > 4000:
            raise ValueError('审核动作、审核人或备注不合法')
        ids = list(dict.fromkeys(ids))
        changed = []
        with self.b.LOCK, self.b.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            rows = []
            for cid in ids:
                row = c.execute('SELECT * FROM pipeline_candidates WHERE id=?', (cid,)).fetchone()
                if not row:
                    raise KeyError('候选不存在：' + cid)
                rows.append(dict(row))
            # Entity endpoints must exist before accepting a relation in the same batch.
            rows.sort(key=lambda r: json.loads(r['payload'])['kind'] == 'relation')
            for row in rows:
                desired = {'accept': 'accepted', 'reject': 'rejected', 'revoke': 'revoked'}[action]
                if row['status'] == desired:
                    continue
                if (action in {'accept', 'reject'} and row['status'] != 'pending') or (action == 'revoke' and row['status'] != 'accepted'):
                    raise ValueError('候选状态已改变，请刷新后审核')
                payload, proof = json.loads(row['payload']), json.loads(row['evidence'])
                oid, object_hash = row['object_id'], row['object_hash']
                if action == 'accept':
                    self._validate_proof(c, proof)
                    issues = c.execute("SELECT * FROM pipeline_conflicts WHERE status='open' AND (left_id=? OR right_id=?)", (row['id'], row['id'])).fetchall()
                    if any(i['kind'] == 'unit_mismatch' for i in issues):
                        raise ValueError('候选属性与单位量纲不符，请拒绝后修正资料')
                    if issues and not conflict_note.strip():
                        raise ValueError('存在数值差异，需填写工况核对说明；不允许自动覆盖')
                    if payload['kind'] == 'entity':
                        oid = str(uuid.uuid5(uuid.NAMESPACE_URL, 'zhiheng-candidate:' + row['id']))
                        if c.execute('SELECT 1 FROM objects WHERE id=?', (oid,)).fetchone():
                            raise ValueError('候选对象 ID 已存在，拒绝覆盖')
                        obj = self._put_object(c, self._body(payload, proof), oid=oid)
                        object_hash = obj['hash']
                        source = c.execute('SELECT * FROM objects WHERE id=?', (proof['source_object_id'],)).fetchone()
                        if not source or source['status'] in {'retired', 'conflict'}:
                            raise ValueError('来源对象不可用')
                        rid = str(uuid.uuid5(uuid.NAMESPACE_URL, row['id'] + ':source'))
                        c.execute('INSERT INTO relations VALUES(?,?,?,?,?,?,?)',
                                  (rid, oid, source['id'], '来源于', dump(proof), obj['version'], source['version']))
                    else:
                        from .templates import RELATIONS
                        if payload.get('relation_type') not in RELATIONS:
                            raise ValueError('不支持的关系类型')
                        endpoints = []
                        for endpoint in ('source_key', 'target_key'):
                            dependency = key([row['job_id'], payload[endpoint]])
                            endpoint_row = c.execute("SELECT object_id,object_hash FROM pipeline_candidates WHERE id=? AND status='accepted'", (dependency,)).fetchone()
                            if not endpoint_row:
                                raise ValueError('请先采纳关系两端的实体候选')
                            obj = c.execute('SELECT * FROM objects WHERE id=?', (endpoint_row['object_id'],)).fetchone()
                            if not obj or obj['hash'] != endpoint_row['object_hash'] or obj['status'] in {'retired', 'conflict'}:
                                raise ValueError('关系端点已更新，需重新抽取')
                            endpoints.append(obj)
                        a, b = endpoints
                        if a['id'] == b['id']:
                            raise ValueError('禁止自关联')
                        oid = str(uuid.uuid5(uuid.NAMESPACE_URL, 'zhiheng-relation:' + row['id']))
                        relation = (oid, a['id'], b['id'], payload['relation_type'], dump(proof), a['version'], b['version'])
                        c.execute('INSERT INTO relations VALUES(?,?,?,?,?,?,?)', relation)
                        object_hash = key(relation)
                    for issue in issues:
                        c.execute("UPDATE pipeline_conflicts SET status='acknowledged',note=? WHERE id=?", (conflict_note, issue['id']))
                    self.b.revision(c)
                elif action == 'reject':
                    c.execute("UPDATE pipeline_conflicts SET status='dismissed',note=? WHERE status='open' AND (left_id=? OR right_id=?)", ('候选被拒绝：' + note, row['id'], row['id']))
                elif action == 'revoke':
                    if not note.strip():
                        raise ValueError('撤销采纳需要说明原因')
                    if payload['kind'] == 'entity':
                        old_row = c.execute('SELECT * FROM objects WHERE id=?', (oid,)).fetchone()
                        if not old_row or old_row['hash'] != object_hash:
                            raise ValueError('对象在采纳后已编辑，拒绝自动停用')
                        old = self.b.record(old_row)
                        self._put_object(c, {**old, 'status': 'retired'}, oid=oid, old=old)
                    else:
                        relation = c.execute('SELECT * FROM relations WHERE id=?', (oid,)).fetchone()
                        if not relation or key(tuple(relation)) != object_hash:
                            raise ValueError('关系在采纳后已编辑，拒绝自动删除')
                        c.execute('DELETE FROM relations WHERE id=?', (oid,))
                    self.b.revision(c)
                c.execute('UPDATE pipeline_candidates SET status=?,object_id=?,object_hash=?,reviewer=?,note=?,updated=? WHERE id=?',
                          (desired, oid, object_hash, reviewer.strip(), note, self.b.now(), row['id']))
                c.execute('INSERT INTO pipeline_reviews(candidate_id,action,reviewer,note,created) VALUES(?,?,?,?,?)',
                          (row['id'], action, reviewer.strip(), dump({'note': note, 'conflict_note': conflict_note}), self.b.now()))
                changed.append({'id': row['id'], 'status': desired, 'object_id': oid, 'engineering_approval': False})
            if changed and action != 'reject':
                c.execute("INSERT OR REPLACE INTO pipeline_meta VALUES('indexes','dirty')")
        return {'items': changed, 'indexes': 'dirty' if changed and action != 'reject' else 'unchanged', 'engineering_approval': False}
