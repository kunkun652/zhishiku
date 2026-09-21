"""Add the pipeline without replacing the existing graph and detail routes."""
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
import json
import threading
from fastapi import HTTPException, UploadFile, File
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool
from .evidence import EvidenceService
from .parsers import MAX_BYTES
from .pipeline import Pipeline


def install(core, runtime=None):
    app = core.app
    if getattr(app.state, "knowledge_pipeline", None):
        return app.state.knowledge_pipeline
    pipeline = Pipeline(core, runtime)
    evidence = EvidenceService(pipeline)
    app.state.knowledge_pipeline = pipeline
    app.state.evidence_service = evidence
    old_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        async with old_lifespan(application):
            thread = threading.Thread(target=pipeline.maintenance, daemon=True, name="knowledge-indexes")
            thread.start()
            try:
                yield
            finally:
                pipeline.close()
                await asyncio.to_thread(thread.join, 6)
    app.router.lifespan_context = lifespan

    def invoke(function, *args, **kwargs):
        try:
            return function(*args, **kwargs)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.get('/api/pipeline/status')
    def status():
        return pipeline.status()

    @app.post('/api/pipeline/probe')
    def probe():
        return invoke(pipeline.runtime.call, "probe", {})

    @app.get('/api/pipeline/jobs')
    def jobs():
        with core.connect() as c:
            return {"items": [dict(r) for r in c.execute("SELECT id,file_id,status,error,created,updated FROM kp_jobs ORDER BY created DESC LIMIT 100")],
                    "total": c.execute("SELECT COUNT(*) FROM kp_jobs").fetchone()[0], "limit": 100}

    @app.get('/api/pipeline/jobs/{job_id}')
    def job(job_id: str):
        return invoke(pipeline.job, job_id)

    @app.post('/api/pipeline/upload')
    async def upload(file: UploadFile = File(...)):
        raw = await file.read(MAX_BYTES + 1)
        return await run_in_threadpool(invoke, pipeline.import_bytes, raw, file.filename or "asset.txt")

    @app.post('/api/pipeline/files/{file_id}')
    def submit_file(file_id: str):
        return invoke(pipeline.submit_file, file_id)

    @app.post('/api/assistant/ingest')
    async def managed_upload(file: UploadFile = File(...)):
        raw = await file.read(MAX_BYTES + 1)
        job = await run_in_threadpool(invoke, pipeline.import_bytes, raw, file.filename or 'asset.txt')
        return invoke(pipeline.manage, job['id'])

    @app.post('/api/assistant/files/{file_id}/process')
    def managed_file(file_id: str):
        job = invoke(pipeline.submit_file, file_id)
        return invoke(pipeline.manage, job['id'])

    @app.get('/api/assistant/jobs')
    def managed_jobs():
        with core.connect() as c:
            return {'items': [dict(r) for r in c.execute('SELECT * FROM kp_managed_jobs ORDER BY updated DESC LIMIT 100')]}

    @app.post('/api/pipeline/jobs/{job_id}/run', status_code=202)
    def run(job_id: str):
        return invoke(pipeline.queue, job_id)

    @app.post('/api/pipeline/jobs/{job_id}/review')
    def review(job_id: str, body: dict):
        return invoke(pipeline.review, job_id, body.get("accept", []), body.get("reject", []),
                      body.get("reviewer", ""), body.get("note", ""), body.get("acknowledge_conflicts") is True)

    @app.post('/api/pipeline/indexes/refresh')
    def refresh():
        return invoke(pipeline.refresh_indexes)

    @app.post('/api/retrieve')
    def retrieve(body: dict):
        return invoke(evidence.retrieve, body.get("query", ""), filters=body.get("filters"), top_k=body.get("top_k", 10))

    @app.post('/api/agent/ask')
    def ask(body: dict):
        return invoke(evidence.ask, body.get("query", ""), filters=body.get("filters"), top_k=body.get("top_k", 10))

    @app.get('/api/agent/runs/{run_id}')
    def run_detail(run_id: str):
        with core.connect() as c:
            row = c.execute("SELECT * FROM kp_agent_runs WHERE id=?", (run_id,)).fetchone()
            if not row:
                raise HTTPException(404, "运行记录不存在")
            result = dict(row)
            result["evidence_pack"] = json.loads(result["evidence_pack"])
            result["result"] = json.loads(result["result"])
            result['source_state'] = 'current' if all(evidence._valid_provenance(e, c)
                for e in result['evidence_pack'].get('evidence', [])) else 'stale'
            result['history_note'] = '保留当时证据快照；来源变化后不得视作当前有效结论'
            return result

    @app.get('/knowledge-pipeline')
    def workspace():
        return RedirectResponse('/#home')

    previous_health = core.health
    app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) != '/api/health']
    @app.get('/api/health')
    def health():
        info = previous_health()
        state = pipeline.runtime.status()
        return {**info, "build": "1.6.0-trusted-workbench", "agent_path_wired": True,
                "agent_connected": state.get("last_probe", {}).get("status") == "ready",
                "agent_runtime": state, "agent_mode": "只读证据问答；不执行 CAE", "engineering_approval": False}
    app.openapi_schema = None
    return pipeline
