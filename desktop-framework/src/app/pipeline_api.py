"""Additive API installation; existing objects, templates, graph UI and routes stay intact."""
from __future__ import annotations
import json
import threading
import uuid
from fastapi import File, HTTPException, UploadFile
from .pipeline_store import Pipeline, dump
from .pipeline_agent import HybridRetriever, EvidenceAgent
from .pipeline_runtime import Ollama
from .pipeline_parsers import MAX_BYTES


def install(backend, worker=None, model=None):
    app = backend.app
    if getattr(app.state, 'knowledge_pipeline', None):
        return app.state.knowledge_pipeline
    pipeline = Pipeline(backend, worker=worker)
    retriever = HybridRetriever(backend)
    agent = EvidenceAgent(backend, retriever=retriever, model=model)
    app.state.knowledge_pipeline = pipeline
    index_lock = threading.Lock()
    index_state = {'status': 'not_checked'}
    component_state = {'semantica': {'status': 'not_checked'}, 'agent': {'status': 'not_checked'}}

    def translate(action):
        try:
            return action()
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except (RuntimeError, OSError) as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.get('/api/pipeline/status')
    def status(probe: bool = False):
        if probe:
            component_state['semantica'] = pipeline.worker.status()
            component_state['agent'] = agent.model.status()
        with backend.connect() as c:
            jobs = {r[0]: r[1] for r in c.execute('SELECT state,COUNT(*) FROM pipeline_jobs GROUP BY state')}
            candidates = {r[0]: r[1] for r in c.execute('SELECT status,COUNT(*) FROM pipeline_candidates GROUP BY status')}
            dirty = c.execute("SELECT value FROM pipeline_meta WHERE key='indexes'").fetchone()
        embedding = backend.EMBEDDINGS.status() if probe else {'status': 'not_checked'}
        return {'schema': 'zhiheng-pipeline/1', 'jobs': jobs, 'candidates': candidates,
                'components': {**component_state, 'embedding': embedding}, 'indexes': dict(index_state),
                'index_refresh_required': bool(dirty and dirty[0] == 'dirty'),
                'agent_connected': component_state['agent'].get('status') == 'ready',
                'engineering_approval': False, 'solver_execution': False,
                'scope': '已登记/主动上传资产；不是 D:\\知识库 全盘自动治理；源文件只读'}

    @app.post('/api/pipeline/upload')
    async def upload(file: UploadFile = File(...)):
        raw = await file.read(MAX_BYTES + 1)
        return translate(lambda: pipeline.upload(raw, file.filename or ''))

    @app.get('/api/pipeline/files')
    def registered_files(offset: int = 0, limit: int = 50):
        with backend.connect() as c:
            items = [dict(r) for r in c.execute('SELECT id,object_id,name,sha256,size FROM files ORDER BY rowid DESC LIMIT ? OFFSET ?',
                                              (max(1, min(limit, 100)), max(0, offset)))]
            total = c.execute('SELECT COUNT(*) FROM files').fetchone()[0]
        return {'items': items, 'total': total}

    @app.post('/api/pipeline/jobs')
    def start(body: dict):
        if not isinstance(body.get('file_id'), str) or set(body) - {'file_id', 'mode'}:
            raise HTTPException(422, '仅接受已登记 file_id 和抽取 mode')
        return translate(lambda: pipeline.start(body['file_id'], body.get('mode', 'regex')))

    @app.get('/api/pipeline/jobs/{jid}')
    def job(jid: str):
        return translate(lambda: pipeline.job(jid))

    @app.get('/api/pipeline/candidates')
    def candidates(job_id: str = '', status: str = '', offset: int = 0, limit: int = 50):
        return pipeline.list_candidates(job_id, status, offset, limit)

    @app.post('/api/pipeline/review')
    def review(body: dict):
        if set(body) - {'ids', 'action', 'reviewer', 'note', 'conflict_note'} or not all(isinstance(body.get(k, ''), str) for k in ('action', 'reviewer', 'note', 'conflict_note')):
            raise HTTPException(422, '审核请求格式不合法')
        return translate(lambda: pipeline.review(body.get('ids'), body.get('action', ''), body.get('reviewer', ''),
                                               body.get('note', ''), body.get('conflict_note', '')))

    @app.post('/api/retrieve')
    def retrieve(body: dict):
        if set(body) - {'query', 'filters', 'top_k'}:
            raise HTTPException(422, '未知检索字段')
        return translate(lambda: retriever.retrieve(body.get('query'), body.get('filters'), body.get('top_k', 10)))

    @app.post('/api/agent/ask')
    def ask(body: dict):
        if set(body) - {'query', 'filters', 'top_k'}:
            raise HTTPException(422, '未知问答字段')
        return translate(lambda: agent.answer(body.get('query'), body.get('filters'), body.get('top_k', 10)))

    @app.get('/api/agent/runs/{run_id}')
    def agent_run(run_id: str):
        with backend.connect() as c:
            row = c.execute('SELECT result FROM pipeline_agent_runs WHERE id=?', (run_id,)).fetchone()
        if not row:
            raise HTTPException(404, '问答记录不存在')
        return json.loads(row[0])

    def rebuild():
        from . import derived_graph
        acquired = False
        try:
            index_state.update(status='building_graph', error=None)
            acquired = backend.SEMANTIC_BUILD_LOCK.acquire(False)
            if not acquired:
                raise RuntimeError('已有图谱重建任务，本轮未重复启动')
            with backend.connect() as c:
                revision, nodes, edges = derived_graph.read_source(c, backend.record)
            artifact = pipeline.worker.run({'operation': 'graph', 'nodes': nodes, 'edges': edges}, timeout=180)
            expected = derived_graph.normalize(nodes, edges)
            if not derived_graph.compare(expected, artifact['canonical'])['equal']:
                raise RuntimeError('Semantica 派生产物与主库不一致，未发布')
            name = 'graph-artifact-' + uuid.uuid4().hex + '.json'
            (backend.ROOT / name).write_text(dump(artifact), 'utf-8')
            manifest = {'schema': 'zhiheng-derived/2', 'build_version': '2', 'revision': revision,
                        'semantica_version': artifact['semantica_version'], 'time': backend.now(),
                        'nodes': len(nodes), 'edges': len(edges), 'content_hash': derived_graph.digest(expected), 'artifact': name}
            with backend.LOCK, backend.connect() as c:
                current = int(c.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0])
                if current != revision:
                    raise RuntimeError('构建期间主库已变化；没有切换到过期产物，请重试')
                derived_graph.publish(backend.ROOT, manifest)
            index_state.update(status='starting_vectors', graph={'status': 'consistent', 'revision': revision})
            # Reuse the existing isolated token-complete BGE-M3 index, no new vector DB.
            try:
                vectors = backend.EMBEDDINGS.call('/v2/build')
                index_state.update(status='vectors_building' if vectors.get('status') == 'building' else 'activation_required', embedding=vectors)
            except Exception as exc:
                index_state.update(status='graph_ready_vectors_unavailable', error=str(exc)[:600])
        except Exception as exc:
            index_state.update(status='failed', error=str(exc)[:1000])
        finally:
            if acquired:
                backend.SEMANTIC_BUILD_LOCK.release()
            index_lock.release()

    @app.post('/api/pipeline/indexes/refresh')
    def refresh_indexes():
        if not index_lock.acquire(False):
            return dict(index_state)
        # Jobs live in the desktop application; no assistant-side background promises.
        thread = threading.Thread(target=rebuild, daemon=True, name='knowledge-index-refresh')
        index_state.update(status='queued')
        thread.start()
        return dict(index_state)

    @app.get('/api/pipeline/indexes')
    def indexes():
        result = dict(index_state)
        if result.get('status') == 'ready':
            with backend.connect() as c:
                current = int(c.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0])
            if result.get('graph', {}).get('revision') != current:
                result['status'] = 'stale'
        if result.get('status') in {'vectors_building', 'activation_required'}:
            try:
                state = backend.EMBEDDINGS.call('/v2/status')
                result['embedding'] = state
                if state.get('status') == 'ready':
                    result['status'] = 'activation_required'
                elif state.get('status') != 'building':
                    result['status'] = 'incomplete'
            except Exception as exc:
                result.update(status='failed', error=str(exc)[:600])
        return result

    @app.post('/api/pipeline/indexes/activate')
    def activate_indexes():
        def activate():
            from . import derived_graph
            with backend.connect() as c:
                revision, nodes, edges = derived_graph.read_source(c, backend.record)
            graph = derived_graph.state(backend.ROOT, revision, nodes, edges)
            if graph['status'] != 'consistent':
                raise ValueError('图谱尚未与主库一致，请先更新索引')
            vectors = backend.EMBEDDINGS.call('/v2/activate')
            if vectors.get('status') != 'ready':
                raise ValueError('向量索引未就绪')
            with backend.LOCK, backend.connect() as c:
                if int(c.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0]) != revision:
                    raise ValueError('启用期间主库变化，请重新检查索引')
                c.execute("INSERT OR REPLACE INTO pipeline_meta VALUES('indexes','ready')")
            index_state.update(status='ready', embedding=vectors, graph=graph)
            return dict(index_state)
        return translate(activate)

    # Keep source-only uvicorn and desktop.exe behavior identical at the new entry point.
    app.add_event_handler('shutdown', pipeline.close)
    return pipeline
