"""Unified existing hybrid recall -> provenance-checked evidence -> read-only Agent."""
from __future__ import annotations
import json
import uuid
from .pipeline_store import dump, key
from .pipeline_parsers import sha
from .pipeline_runtime import Ollama

FILTERS = {'type', 'analysis_type', 'status', 'category', 'designation', 'object_id'}


class HybridRetriever:
    def __init__(self, backend):
        self.b = backend

    def retrieve(self, query: str, filters: dict | None = None, top_k: int = 10) -> dict:
        if not isinstance(query, str) or not query.strip() or len(query) > 2000:
            raise ValueError('查询需要 1–2000 个字符')
        filters = filters or {}
        if not isinstance(filters, dict) or set(filters) - FILTERS or not all(isinstance(v, str) and len(v) <= 300 for v in filters.values()):
            raise ValueError('检索筛选字段不合法')
        if filters.get('status') in {'retired', 'conflict'}:
            raise ValueError('Agent 不使用停用或冲突对象作为回答证据')
        if type(top_k) is not int or not 1 <= top_k <= 20:
            raise ValueError('top_k 必须在 1–20 之间')
        # Keep the project's real FTS5/BGE-M3/RRF implementation as the sole retriever.
        result = self.b.search(q=query.strip(), mode='hybrid', graph_backend='semantica', limit=top_k, **filters)
        revision = result.get('run', {}).get('revision')
        items = list(result.get('items', []))
        degradations = list(result.get('run', {}).get('degradations', []))
        # Existing graph expansion seeds from lexical results. Also expand actual vector
        # hits so a semantic-only match can reach evidence-backed neighboring objects.
        expanded = []
        seen = {r['id'] for r in items}
        for seed in [r for r in items if '语义向量' in r.get('retrieval_channels', [])][:2]:
            related = self.b.search(q=seed['id'], mode='graph', graph_backend='semantica', limit=5, **filters)
            if related.get('run', {}).get('revision') != revision:
                raise ValueError('检索期间知识库版本变化，请重新提问')
            degradations.extend(related.get('run', {}).get('degradations', []))
            for r in related.get('items', []):
                if r['id'] not in seen:
                    expanded.append(r)
                    seen.add(r['id'])
        # Expansion is reported separately, not assigned a made-up probability.
        items = items + expanded[:5]
        evidence, rejected, valid_files = [], [], {}
        object_ids = {item['id'] for item in items}
        with self.b.connect() as c:
            c.execute('BEGIN')
            quality_revision = c.execute('SELECT COALESCE(MAX(id),0) FROM chunk_quality_events').fetchone()[0]
            current_revision = int(c.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0])
            if revision != current_revision:
                raise ValueError('检索快照已过期，请重新提问')
            def file_valid(fid, expected=None):
                if fid not in valid_files:
                    try:
                        actual, _ = self.b.asset(fid)
                        owner = c.execute('SELECT status FROM objects WHERE id=?', (actual['object_id'],)).fetchone()
                        valid_files[fid] = dict(actual) if owner and owner['status'] not in {'retired', 'conflict'} else None
                    except Exception:
                        valid_files[fid] = None
                info = valid_files[fid]
                return info if info and (expected is None or info['sha256'] == expected) else None

            def append(entry):
                if not entry.get('quote') or len(evidence) >= 30:
                    return
                entry['id'] = 'E-' + key(entry)[:16]
                if not any(e['id'] == entry['id'] for e in evidence):
                    evidence.append(entry)

            for item in items:
                current = c.execute('SELECT * FROM objects WHERE id=?', (item['id'],)).fetchone()
                if not current or current['hash'] != item['hash'] or current['status'] in {'retired', 'conflict'}:
                    rejected.append({'object_id': item['id'], 'reason': '对象版本过期或已停用'})
                    continue
                base = {'object_id': item['id'], 'object_version': item['version'], 'object_hash': item['hash'],
                        'title': item['title'], 'channels': item.get('retrieval_channels', []),
                        'engineering_approval': False}
                for hit in item.get('evidence', []):
                    # Vector v2 evidence uses parent_id; lexical evidence uses chunk_id.
                    cid = hit.get('chunk_id')
                    if cid is None and str(hit.get('parent_id', '')).startswith('c:'):
                        suffix = str(hit['parent_id'])[2:]
                        cid = int(suffix) if suffix.isdigit() else None
                    if cid is None:
                        # Resolve a v2 unit ID through the read-only vector index, not by guessing.
                        unit_id = hit.get('unit_id')
                        path = self.b.ROOT / 'vectors-v2.sqlite3'
                        if unit_id and path.is_file():
                            import sqlite3
                            from contextlib import closing
                            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as index:
                                unit = index.execute('SELECT parent FROM units WHERE key=?', (unit_id,)).fetchone()
                            if unit and str(unit[0]).startswith('c:') and str(unit[0])[2:].isdigit():
                                cid = int(str(unit[0])[2:])
                    row = c.execute('SELECT * FROM chunks WHERE id=?', (cid,)).fetchone() if cid is not None else None
                    quoted = hit.get('text', '')
                    info = file_valid(row['file_id']) if row else None
                    if not row or row['object_id'] != item['id'] or not info or not quoted or quoted not in row['text']:
                        rejected.append({'object_id': item['id'], 'reason': '片段无法核验到当前原件'})
                        continue
                    from . import content_quality
                    if not content_quality.eligible(c, row['id'], row['text']):
                        rejected.append({'object_id': item['id'], 'reason': '片段已被质量审核排除'})
                        continue
                    location = c.execute('SELECT * FROM pipeline_segments WHERE chunk_id=? LIMIT 1', (row['id'],)).fetchone()
                    append({**base, 'kind': 'source_excerpt', 'quote': quoted[:1800], 'chunk_id': row['id'],
                            'chunk_hash': sha(row['text']), 'file_id': row['file_id'], 'file_hash': info['sha256'],
                            'page': row['page'] or None, 'locator': location['locator'] if location else '沿用既有解析位置',
                            'url': f"/api/model-assets/{row['file_id']}/file" + (f"#page={row['page']}" if row['page'] else ''),
                            'source_type': 'original_excerpt', 'review_status': 'source_not_engineering_verified'})
                for candidate in c.execute("SELECT * FROM pipeline_candidates WHERE object_id=? AND status='accepted'", (item['id'],)):
                    proof = json.loads(candidate['evidence'])
                    row = c.execute('SELECT * FROM chunks WHERE id=?', (proof['chunk_id'],)).fetchone()
                    if (candidate['object_hash'] != item['hash'] or not file_valid(proof['file_id'], proof['file_hash']) or not row
                            or sha(row['text']) != proof['chunk_hash'] or row['text'][proof['start']:proof['end']] != proof['quote']):
                        rejected.append({'object_id': item['id'], 'reason': '采纳记录的来源已变化'})
                        continue
                    from . import content_quality
                    if not content_quality.eligible(c, row['id'], row['text']):
                        continue
                    append({**base, **proof, 'kind': 'reviewed_extraction', 'review_status': 'source_reviewed',
                            'reviewer': candidate['reviewer'], 'url': f"/api/model-assets/{proof['file_id']}/file"})
                for path in item.get('relation_paths', []):
                    for edge in path:
                        row = c.execute('SELECT * FROM relations WHERE id=?', (edge['id'],)).fetchone()
                        if not row or any(row[k] != edge.get(k) for k in ('source', 'target', 'type', 'evidence', 'source_version', 'target_version')):
                            continue
                        endpoints = [c.execute('SELECT version,status FROM objects WHERE id=?', (row[k],)).fetchone() for k in ('source', 'target')]
                        if any(not e or e['version'] != row[k] or e['status'] in {'retired', 'conflict'}
                               for e, k in zip(endpoints, ('source_version', 'target_version'))):
                            continue
                        # Pipeline-authored relation evidence also depends on immutable source bytes.
                        try:
                            relation_proof = json.loads(row['evidence'])
                        except (ValueError, TypeError):
                            relation_proof = None
                        if isinstance(relation_proof, dict) and relation_proof.get('file_id'):
                            original = c.execute('SELECT text FROM chunks WHERE id=?', (relation_proof.get('chunk_id'),)).fetchone()
                            if (not file_valid(relation_proof['file_id'], relation_proof.get('file_hash')) or not original
                                    or sha(original[0]) != relation_proof.get('chunk_hash')):
                                continue
                        # A relationship record is evidence of a recorded association only.
                        origin = {k: relation_proof[k] for k in ('file_id', 'file_hash', 'chunk_id', 'chunk_hash')} if isinstance(relation_proof, dict) and relation_proof.get('file_id') else {}
                        append({**base, **origin, 'kind': 'relation_record', 'relation_id': row['id'],
                                'source_id': row['source'], 'target_id': row['target'], 'relation_type': row['type'],
                                'quote': row['evidence'][:1800], 'source_type': 'recorded_relation',
                                'review_status': 'not_engineering_verified', 'url': f"/api/objects/{item['id']}/wiki"})
            conflicts = []
            if object_ids:
                # Include unresolved/acknowledged differences touching cited files, not unrelated library issues.
                fids = set(valid_files)
                for row in c.execute("SELECT pc.*,a.evidence left_evidence,b.evidence right_evidence FROM pipeline_conflicts pc JOIN pipeline_candidates a ON a.id=pc.left_id JOIN pipeline_candidates b ON b.id=pc.right_id WHERE pc.status IN ('open','acknowledged')"):
                    if any(json.loads(row[k])['file_id'] in fids for k in ('left_evidence', 'right_evidence')):
                        conflicts.append({k: row[k] for k in ('id', 'kind', 'detail', 'status', 'note')})
        with self.b.connect() as c:
            if int(c.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0]) != revision:
                raise ValueError('证据准备期间知识库版本变化，请重新提问')
        return {'schema': 'zhiheng-evidence/1', 'query': query, 'revision': revision, 'quality_revision': quality_revision, 'evidence': evidence,
                'results': [{'object_id': r['id'], 'title': r['title'], 'channels': r.get('retrieval_channels', []),
                             'fusion_score': r.get('fusion_score'), 'score_is_probability': False} for r in items],
                'channels': {'embedding': result.get('embedding'), 'graph': result.get('graph'),
                             'used': result.get('run', {}).get('channels', [])},
                'degradations': list(dict.fromkeys(degradations)), 'rejected_evidence': rejected, 'conflicts': conflicts,
                'status': 'ready' if evidence else 'no_evidence', 'engineering_approval': False}


class EvidenceAgent:
    def __init__(self, backend, retriever=None, model=None):
        self.b = backend
        self.retriever = retriever or HybridRetriever(backend)
        self.model = model or Ollama()

    def answer(self, query: str, filters=None, top_k=10) -> dict:
        pack = self.retriever.retrieve(query, filters, top_k)
        run_id = str(uuid.uuid4())
        response = {'run_id': run_id, 'query': query, 'evidence_pack': pack, 'claims': [], 'gaps': [],
                    'mode': 'read_only_evidence_agent', 'engineering_approval': False, 'solver_executed': False}
        if not pack['evidence']:
            response.update(status='no_evidence', gaps=['没有可核验的原文证据；没有调用模型编写答案'])
        else:
            state = self.model.status()
            if state.get('status') != 'ready':
                response.update(status='model_unavailable', model=state, gaps=['本地问答模型未就绪；仅返回真实检索证据，不伪装成大模型回答'])
            else:
                try:
                    # Never turn a known unresolved numeric difference into an apparently definitive answer.
                    caution = '\n注意存在以下待核对差异：' + dump(pack['conflicts']) if pack['conflicts'] else ''
                    generated = self.model.generate(query + caution, pack['evidence'])
                    evidence = {e['id']: e for e in pack['evidence']}
                    claims = generated.get('claims')
                    if not isinstance(claims, list) or len(claims) > 30:
                        raise ValueError('模型回答不符合 claims 契约')
                    checked = []
                    for claim in claims:
                        if not isinstance(claim, dict) or not isinstance(claim.get('text'), str) or not claim['text'].strip() or len(claim['text']) > 4000:
                            raise ValueError('模型回答句子不合法')
                        citations = claim.get('citations')
                        if not isinstance(citations, list) or not 1 <= len(citations) <= 10:
                            raise ValueError('模型回答缺少有效引用')
                        for citation in citations:
                            if not isinstance(citation, dict):
                                raise ValueError('模型引用格式不合法')
                            eid, quote = citation.get('id'), citation.get('quote')
                            if eid not in evidence or not isinstance(quote, str) or not quote.strip() or quote not in evidence[eid]['quote']:
                                raise ValueError('模型编造了引用 ID 或引用原文，拒绝输出该回答')
                        checked.append({'text': claim['text'], 'citations': citations, 'interpretation': '模型解读，仍需核验蕴含关系'})
                    gaps = generated.get('gaps', [])
                    if not isinstance(gaps, list) or not all(isinstance(g, str) and len(g) <= 2000 for g in gaps) or len(gaps) > 30:
                        raise ValueError('模型 gaps 格式不合法')
                    # Do not publish an answer against a concurrently changed authority database.
                    with self.b.connect() as c:
                        if int(c.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0]) != pack['revision']:
                            raise ValueError('生成期间知识库版本变化，回答已阻止，请重新提问')
                        quality = c.execute('SELECT COALESCE(MAX(id),0) FROM chunk_quality_events').fetchone()[0]
                        if quality != pack.get('quality_revision', quality):
                            raise ValueError('生成期间证据质量状态变化，请重新提问')
                        checked_files = set()
                        for entry in pack['evidence']:
                            fid = entry.get('file_id')
                            if fid and fid not in checked_files:
                                actual, _ = self.b.asset(fid)
                                if actual['sha256'] != entry.get('file_hash'):
                                    raise ValueError('生成期间原件变化，请重新提问')
                                checked_files.add(fid)
                            if entry.get('chunk_id'):
                                chunk = c.execute('SELECT text FROM chunks WHERE id=?', (entry['chunk_id'],)).fetchone()
                                from . import content_quality
                                if not chunk or sha(chunk[0]) != entry['chunk_hash'] or not content_quality.eligible(c, entry['chunk_id'], chunk[0]):
                                    raise ValueError('生成期间片段变化或被排除，请重新提问')
                    response.update(status='answered' if checked else 'insufficient_evidence', claims=checked,
                                    gaps=gaps, model=generated.get('model'), citation_validation='ID 与逐字摘录通过；非事实正确性证明')
                except Exception as exc:
                    response.update(status='generation_failed', gaps=[str(exc)[:600]], claims=[])
        with self.b.connect() as c:
            c.execute('INSERT INTO pipeline_agent_runs VALUES(?,?,?,?)', (run_id, query, dump(response), self.b.now()))
        return response
