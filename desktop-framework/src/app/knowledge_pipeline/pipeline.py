"""Durable, review-gated ingestion into the existing SQLite authority database."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
from pathlib import Path
import re
import threading
import uuid

from .contracts import VERSION, MAX_CANDIDATES, bounded_text, dumps, sha, validate_extraction
from .parsers import parse
from .runtime import Runtime

SCHEMA = """
CREATE TABLE IF NOT EXISTS answer_dependencies(run_id TEXT,file_id TEXT,file_hash TEXT,object_id TEXT,object_hash TEXT,PRIMARY KEY(run_id,file_id,object_id));
CREATE TABLE IF NOT EXISTS kp_managed_jobs(job_id TEXT PRIMARY KEY,status TEXT,detail TEXT,updated TEXT);
CREATE TABLE IF NOT EXISTS kp_jobs(
 id TEXT PRIMARY KEY,file_id TEXT,source_sha TEXT,owner_id TEXT,owner_hash TEXT,
 signature TEXT,status TEXT,error TEXT,report TEXT,created TEXT,updated TEXT,
 UNIQUE(file_id,signature));
CREATE TABLE IF NOT EXISTS kp_segments(
 id TEXT PRIMARY KEY,job_id TEXT,chunk_id INTEGER,page INTEGER,start INTEGER,end INTEGER,
 text TEXT,text_hash TEXT,locator TEXT,result TEXT);
CREATE INDEX IF NOT EXISTS kp_segments_job ON kp_segments(job_id);
CREATE TABLE IF NOT EXISTS kp_candidates(
 id TEXT PRIMARY KEY,job_id TEXT,kind TEXT,payload TEXT,provenance TEXT,status TEXT,
 object_id TEXT,conflicts TEXT);
CREATE INDEX IF NOT EXISTS kp_candidates_job ON kp_candidates(job_id,status);
CREATE INDEX IF NOT EXISTS kp_candidates_object ON kp_candidates(object_id);
CREATE TABLE IF NOT EXISTS kp_reviews(
 id INTEGER PRIMARY KEY,job_id TEXT,candidate_id TEXT,decision TEXT,reviewer TEXT,note TEXT,created TEXT);
CREATE TABLE IF NOT EXISTS kp_facts(
 id TEXT PRIMARY KEY,group_key TEXT,object_id TEXT,object_hash TEXT,payload TEXT,provenance TEXT);
CREATE INDEX IF NOT EXISTS kp_facts_key ON kp_facts(group_key);
CREATE TABLE IF NOT EXISTS kp_index_requests(
 id TEXT PRIMARY KEY,revision INTEGER,status TEXT,detail TEXT,created TEXT,updated TEXT);
CREATE TABLE IF NOT EXISTS kp_agent_runs(
 id TEXT PRIMARY KEY,query TEXT,status TEXT,evidence_pack TEXT,result TEXT,created TEXT);
"""


class Pipeline:
    def __init__(self, core, runtime=None):
        self.core = core
        self.root = Path(core.ROOT)
        self.runtime = runtime or Runtime(self.root)
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="knowledge-ingest")
        self.futures = {}
        self.queue_lock = threading.Lock()
        self.index_lock = threading.Lock()
        self.stop = threading.Event()
        with core.connect() as c:
            c.executescript(SCHEMA)
            c.execute("UPDATE kp_jobs SET status='interrupted',error='上次处理被中断，可继续处理' WHERE status IN ('queued','running')")
        from .. import change_queue
        change_queue.install(core)

    def signature(self) -> str:
        state = self.runtime.status()
        return sha(dumps({"protocol": VERSION, "model": state.get("model", ""),
                          "parser": "zhiheng-readonly/1", "semantica_target": "0.7.0"}))

    def close(self):
        self.stop.set()
        if hasattr(self.runtime, "close"):
            self.runtime.close()
        self.pool.shutdown(wait=False, cancel_futures=True)

    def _object(self, c, kind: str, title: str, data: dict, status="candidate") -> dict:
        kind, title, data = self.core.validate({"type": kind, "title": title, "data": data})
        item = {"id": str(uuid.uuid4()), "type": kind, "title": title, "version": 1,
                "status": status, "data": data, "updated": self.core.now()}
        item["hash"] = self.core.digest({k: v for k, v in item.items() if k != "updated"})
        c.execute("INSERT INTO objects VALUES(?,?,?,?,?,?,?,?)",
                  (item["id"], kind, title, 1, status, self.core.encoded(data), item["hash"], item["updated"]))
        c.execute("INSERT INTO versions VALUES(?,?,?)", (item["id"], 1, self.core.encoded(item)))
        return item

    def request_indexes(self, c):
        revision = int(c.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0])
        stamp = self.core.now()
        c.execute("INSERT INTO kp_index_requests VALUES(?,?,?,?,?,?)", (uuid.uuid4().hex, revision,
                  "pending", dumps({"fts5": "ready", "graph": "pending", "embedding": "pending"}), stamp, stamp))

    def import_bytes(self, raw: bytes, filename: str) -> dict:
        """Only explicit upload bytes. Never scans or alters an arbitrary disk root."""
        name = Path(filename.replace("\\", "/")).name
        if not name or len(name) > 240:
            raise ValueError("文件名无效")
        parsed = parse(raw, name)
        digest = hashlib.sha256(raw).hexdigest()
        with self.core.LOCK, self.core.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            before = c.total_changes
            existing = c.execute("SELECT * FROM files WHERE sha256=? ORDER BY id LIMIT 1", (digest,)).fetchone()
            if existing:
                file_id = existing["id"]
                owner = self.core.record(c.execute("SELECT * FROM objects WHERE id=?", (existing["object_id"],)).fetchone())
                self.core.asset(file_id)
            else:
                owner = self._object(c, "document", name, {"source": name,
                    "summary": "通过知识加工入口登记的原始资料", "extraction_status": parsed["coverage"],
                    "limitations": "；".join(parsed["warnings"]), "rights": "待确认；未授权用于训练"})
                file_id = str(uuid.uuid4())
                path = self.root / "assets" / (digest + Path(name).suffix.lower())
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    raise ValueError("受管原件哈希不一致，拒绝覆盖")
                if not path.exists():
                    path.write_bytes(raw)
                c.execute("INSERT INTO files VALUES(?,?,?,?,?,?)", (file_id, owner["id"], name, digest,
                          len(raw), str(path.relative_to(self.root))))
            job_id = self._register(c, file_id, digest, owner, parsed)
            if c.total_changes > before:
                self.core.revision(c)
                self.request_indexes(c)
        return self.job(job_id)

    def submit_file(self, file_id: str) -> dict:
        file, path = self.core.asset(file_id)
        if path.stat().st_size > 20 * 1024 * 1024:
            raise ValueError("单文件超过 20 MiB；请分册处理")
        parsed = parse(path.read_bytes(), file["name"])
        with self.core.LOCK, self.core.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            before = c.total_changes
            owner = self.core.record(c.execute("SELECT * FROM objects WHERE id=?", (file["object_id"],)).fetchone())
            job_id = self._register(c, file_id, file["sha256"], owner, parsed)
            if c.total_changes > before:
                self.core.revision(c)
                self.request_indexes(c)
        return self.job(job_id)

    def _register(self, c, file_id, source_sha, owner, parsed) -> str:
        config_signature = self.signature()
        signature = sha(dumps([config_signature, owner["hash"], source_sha]))
        old = c.execute("SELECT id FROM kp_jobs WHERE file_id=? AND signature=?", (file_id, signature)).fetchone()
        if old:
            return old["id"]
        if owner["status"] in ("retired", "conflict"):
            raise ValueError("停用或冲突资料不能直接作为抽取来源")
        job_id, stamp = uuid.uuid4().hex, self.core.now()
        report = {k: v for k, v in parsed.items() if k != "segments"}
        report.update({"configuration_signature": config_signature, "segments": len(parsed["segments"]),
                       "engineering_approved": False})
        c.execute("INSERT INTO kp_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (job_id, file_id, source_sha, owner["id"], owner["hash"], signature,
             "parsed", "", dumps(report), stamp, stamp))
        tokens = self.core.retrieval.tokens
        for s in parsed["segments"]:
            old = c.execute("SELECT id FROM chunks WHERE file_id=? AND object_id=? AND page=? AND text=? LIMIT 1",
                            (file_id, owner["id"], s["page"], s["text"])).fetchone()
            if old:
                chunk_id = old["id"]
            else:
                chunk_id = c.execute("INSERT INTO chunks(object_id,file_id,page,text) VALUES(?,?,?,?)",
                                     (owner["id"], file_id, s["page"], s["text"])).lastrowid
                c.execute("INSERT INTO chunks_fts(rowid,tokens) VALUES(?,?)", (chunk_id, tokens(s["text"])))
            c.execute("INSERT INTO kp_segments VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (uuid.uuid4().hex, job_id, chunk_id, s["page"], s["start"], s["end"],
                       s["text"], s["text_hash"], s["locator"], None))
        c.execute("INSERT OR IGNORE INTO sources VALUES(?,?,?,?,?,?,?,?)",
                  (source_sha, owner["id"], file_id, "显式上传", dumps([file_id]), parsed["coverage"],
                   parsed["pages"], parsed["text_pages"]))
        return job_id

    def job(self, job_id: str) -> dict:
        with self.core.connect() as c:
            row = c.execute("SELECT * FROM kp_jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise KeyError("任务不存在")
            job = dict(row)
            job["report"] = json.loads(job["report"])
            job["candidates"] = []
            for item in c.execute("SELECT * FROM kp_candidates WHERE job_id=? ORDER BY kind,id", (job_id,)):
                candidate = dict(item)
                for field in ("payload", "provenance", "conflicts"):
                    candidate[field] = json.loads(candidate[field])
                job["candidates"].append(candidate)
            job["processed"] = c.execute("SELECT COUNT(*) FROM kp_segments WHERE job_id=? AND result IS NOT NULL", (job_id,)).fetchone()[0]
            return job

    def chunk_eligible(self, c, chunk_id, text):
        quality = getattr(self.core, "content_quality", None)
        return quality is None or quality.eligible(c, chunk_id, text)

    def _source_current(self, job: dict, c) -> None:
        file, _ = self.core.asset(job["file_id"])
        row = c.execute("SELECT hash,status FROM objects WHERE id=?", (job["owner_id"],)).fetchone()
        if not row or row["hash"] != job["owner_hash"] or row["status"] in ("retired", "conflict") or file["sha256"] != job["source_sha"]:
            raise ValueError("原件或所属对象已变化；本次候选过期，禁止采纳")
        for s in c.execute("SELECT s.chunk_id,s.text_hash,c.text FROM kp_segments s LEFT JOIN chunks c ON c.id=s.chunk_id WHERE s.job_id=?", (job["id"],)):
            if s["text"] is None or sha(s["text"]) != s["text_hash"] or not self.chunk_eligible(c, s["chunk_id"], s["text"]):
                raise ValueError("来源正文块已变化或被排除；本次候选过期")

    def queue(self, job_id: str) -> dict:
        with self.queue_lock:
            if self.stop.is_set():
                raise RuntimeError("知识处理服务已关闭")
            job = self.job(job_id)
            if job["status"] not in ("parsed", "failed", "interrupted", "queued", "running"):
                raise ValueError("任务已产出候选，请完成审核；不得重复抽取并覆盖审核记录")
            self.futures = {k: v for k, v in self.futures.items() if not v.done()}
            if job_id not in self.futures:
                if len(self.futures) >= 20:
                    raise RuntimeError("队列已满，请待现有任务完成后提交")
                if not self.runtime.status().get("configured"):
                    raise RuntimeError("知识模型未配置；原文已登记，但未进行 Semantica 抽取")
                with self.core.connect() as c:
                    c.execute("UPDATE kp_jobs SET status='queued',error='',updated=? WHERE id=?", (self.core.now(), job_id))
                self.futures[job_id] = self.pool.submit(self.process, job_id)
        return self.job(job_id)

    def process(self, job_id: str) -> dict:
        job = self.job(job_id)
        try:
            if job["report"].get("configuration_signature") != self.signature():
                raise ValueError("抽取配置发生变化；请重新登记为新的处理版本")
            with self.core.LOCK, self.core.connect() as c:
                c.execute("BEGIN IMMEDIATE")
                self._source_current(job, c)
                state = c.execute("SELECT status FROM kp_jobs WHERE id=?", (job_id,)).fetchone()[0]
                if state not in ("parsed", "queued", "failed", "interrupted"):
                    raise ValueError("任务不允许重复运行")
                c.execute("UPDATE kp_jobs SET status='running',error='',updated=? WHERE id=?", (self.core.now(), job_id))
                segments = [dict(r) for r in c.execute("SELECT * FROM kp_segments WHERE job_id=? ORDER BY page,start,id", (job_id,))]
            for segment in segments:
                if self.stop.is_set():
                    raise RuntimeError("程序关闭，任务可继续处理")
                if segment["result"] is None:
                    response = self.runtime.call("extract", {"text": segment["text"]})
                    clean = validate_extraction({k: response[k] for k in ("entities", "relations")}, segment["text"])
                    if not response.get("graph_hash") or not response.get("semantica_version"):
                        raise RuntimeError("缺少 Semantica 实际图谱构建记录")
                    clean["engine"] = {k: response.get(k) for k in ("model", "model_digest", "semantica_version", "graph_hash")}
                    segment["result"] = dumps(clean)
                    with self.core.connect() as c:
                        c.execute("UPDATE kp_segments SET result=? WHERE id=?", (segment["result"], segment["id"]))
            candidates, facts = self._candidates(job, segments)
            if len(candidates) > MAX_CANDIDATES:
                raise ValueError("单文件候选超过 2000 项，未部分采纳；请分册处理")
            with self.core.connect() as c:
                keys = list({r["id"] for r in facts})
                for start in range(0, len(keys), 400):
                    batch = keys[start:start + 400]
                    sql = "SELECT f.payload,f.provenance FROM kp_facts f JOIN objects o ON o.id=f.object_id AND o.hash=f.object_hash WHERE o.status NOT IN ('retired','conflict') AND f.group_key IN (" + ",".join("?" for _ in batch) + ")"
                    for row in c.execute(sql, batch):
                        f, p = json.loads(row[0]), json.loads(row[1])
                        facts.append({"id": f["group_key"], "value": f["value"], "source": p["file_id"], "page": p["page"]})
            detection = self.runtime.call("conflicts", {"facts": facts})
            conflict_map = {}
            for conflict in detection.get("conflicts", []):
                conflict_map.setdefault(conflict["entity_id"], []).append({
                    "kind": "possible_value_conflict", "values": conflict.get("conflicting_values", []),
                    "sources": conflict.get("sources", []), "resolved": False,
                    "note": "同名/同单位/同工况文本不保证同一工程对象，必须人工核实"})
            with self.core.LOCK, self.core.connect() as c:
                c.execute("BEGIN IMMEDIATE")
                self._source_current(job, c)
                for candidate in candidates:
                    flags = [flag for key in candidate.pop("fact_keys") for flag in conflict_map.get(key, [])]
                    c.execute("INSERT INTO kp_candidates VALUES(?,?,?,?,?,?,?,?)",
                              (candidate["id"], job_id, candidate["kind"], dumps(candidate["payload"]),
                               dumps(candidate["provenance"]), "pending", "", dumps(flags)))
                report = {**job["report"], "processed": len(segments), "candidate_count": len(candidates),
                          "possible_conflicts": len(conflict_map), "conflict_engine": detection.get("semantica_version")}
                c.execute("UPDATE kp_jobs SET status=?,report=?,error='',updated=? WHERE id=?",
                          ("review_pending" if candidates else "no_candidates", dumps(report), self.core.now(), job_id))
        except Exception as exc:
            with self.core.connect() as c:
                c.execute("UPDATE kp_jobs SET status=?,error=?,updated=? WHERE id=? AND status NOT IN ('review_pending','reviewed','no_candidates')",
                          ("interrupted" if self.stop.is_set() else "failed", str(exc)[:1000], self.core.now(), job_id))
        return self.job(job_id)

    @staticmethod
    def fact_key(entity: dict, attr: dict) -> str:
        return sha(dumps([entity["kind"], entity["name"].strip().casefold(), attr["name"].strip().casefold(),
                          attr["unit"].strip(), attr["context"].strip()]))

    def _candidates(self, job, segments):
        candidates, facts = [], []
        engine_ids = set()
        for segment in segments:
            extracted = json.loads(segment["result"])
            engine = extracted["engine"]
            engine_ids.add(dumps({k: engine.get(k) for k in ("model", "model_digest", "semantica_version")}))
            mapping = {e["key"]: sha(job["id"] + segment["id"] + e["key"]) for e in extracted["entities"]}
            def provenance(item):
                return {"file_id": job["file_id"], "file_hash": job["source_sha"], "source_object_id": job["owner_id"],
                        "source_object_hash": job["owner_hash"], "chunk_id": segment["chunk_id"],
                        "chunk_hash": segment["text_hash"], "page": segment["page"],
                        "start": segment["start"] + item["start"], "end": segment["start"] + item["end"],
                        "segment_start": segment["start"], "locator": segment["locator"],
                        "quote": item["quote"], "locator_ambiguous": item.get("locator_ambiguous", False),
                        "engine": engine, "assertion_kind": "extracted_candidate"}
            for entity in extracted["entities"]:
                keys = []
                for attr in entity["attributes"]:
                    key = self.fact_key(entity, attr)
                    keys.append(key)
                    facts.append({"id": key, "value": attr["value"], "source": job["file_id"], "page": segment["page"]})
                candidates.append({"id": mapping[entity["key"]], "kind": "entity", "payload": entity,
                                   "provenance": provenance(entity), "fact_keys": keys})
            for i, edge in enumerate(extracted["relations"]):
                candidates.append({"id": sha(job["id"] + segment["id"] + "relation" + str(i)), "kind": "relation",
                    "payload": {**edge, "source_candidate": mapping[edge["source"]], "target_candidate": mapping[edge["target"]]},
                    "provenance": provenance(edge), "fact_keys": []})
        if len(engine_ids) > 1:
            raise ValueError("同一文件混用了不同模型或引擎版本；拒绝采纳")
        return candidates, facts

    def review(self, job_id: str, accept: list[str], reject: list[str], reviewer: str, note: str,
               acknowledge_conflicts: bool = False) -> dict:
        bounded_text(reviewer, "reviewer", 100)
        bounded_text(note, "review note", 2000)
        if not isinstance(accept, list) or not isinstance(reject, list) or not all(isinstance(i, str) for i in accept + reject):
            raise ValueError("accept/reject 必须为 ID 数组")
        if len(accept) != len(set(accept)) or len(reject) != len(set(reject)) or set(accept) & set(reject):
            raise ValueError("审核 ID 不得重复或同时采纳与拒绝")
        if not accept and not reject:
            raise ValueError("至少选择一条候选")
        job = self.job(job_id)
        with self.core.LOCK, self.core.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            self._source_current(job, c)
            all_rows = {r["id"]: dict(r) for r in c.execute("SELECT * FROM kp_candidates WHERE job_id=?", (job_id,))}
            for key in accept + reject:
                if key not in all_rows or all_rows[key]["status"] != "pending":
                    raise ValueError("候选不属于此任务或已被审核；请刷新")
            accepted = sorted((all_rows[k] for k in accept), key=lambda r: r["kind"] != "entity")
            for row in accepted:
                payload, p, conflicts = (json.loads(row[k]) for k in ("payload", "provenance", "conflicts"))
                # Recheck value disagreements at adoption, including candidates created concurrently.
                if row["kind"] == "entity":
                    for attr in payload["attributes"]:
                        key = self.fact_key(payload, attr)
                        others = c.execute("SELECT f.payload FROM kp_facts f JOIN objects o ON o.id=f.object_id AND o.hash=f.object_hash WHERE f.group_key=? AND o.status!='retired'", (key,)).fetchall()
                        values = {json.loads(x[0])["value"] for x in others}
                        if values - {attr["value"]} and not conflicts:
                            conflicts.append({"kind": "adoption_value_disagreement", "values": sorted(values | {attr["value"]}), "resolved": False,
                                              "note": "采纳时安全复查发现新差异，尚非同一工程对象冲突的认定"})
                if conflicts and not acknowledge_conflicts:
                    raise ValueError("存在潜在冲突，必须显式确认；冲突对象仍不会作为默认检索事实")
                c.execute("UPDATE kp_candidates SET conflicts=? WHERE id=?", (dumps(conflicts), row["id"]))
                if row["kind"] == "entity":
                    data = {"summary": p["quote"], "source": dumps(p), "original_record": dumps(payload),
                            "verification": "资料采纳审核：" + reviewer + "；" + note,
                            "limitations": "自动抽取候选；资料采纳不等于工程适用性或参数认证"}
                    if payload["kind"] == "material":
                        properties = []
                        for attr in payload["attributes"]:
                            value = None
                            if re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", attr["value"]):
                                number = float(attr["value"])
                                if math.isfinite(number):
                                    value = number
                            properties.append({"name": attr["name"], "value": value, "raw_value": attr["value"],
                                               "unit": attr["unit"], "source": attr["quote"], "context": attr["context"]})
                        data["properties"] = properties
                    if payload["kind"] == "term":
                        data["definition"] = p["quote"]
                    obj = self._object(c, payload["kind"], payload["name"], data, "conflict" if conflicts else "candidate")
                    p["adopted_hash"] = obj["hash"]
                    c.execute("UPDATE kp_candidates SET provenance=? WHERE id=?", (dumps(p), row["id"]))
                    all_rows[row["id"]]["provenance"] = dumps(p)
                    row["object_id"] = obj["id"]
                    all_rows[row["id"]]["object_id"] = obj["id"]
                    c.execute("INSERT INTO relations VALUES(?,?,?,?,?,?,?)", (str(uuid.uuid4()), obj["id"], job["owner_id"],
                              "来源于", dumps(p), 1, c.execute("SELECT version FROM objects WHERE id=?", (job["owner_id"],)).fetchone()[0]))
                    for index, attr in enumerate(payload["attributes"]):
                        fact = {**attr, "group_key": self.fact_key(payload, attr), "entity_kind": payload["kind"], "entity_name": payload["name"]}
                        fact_p = {**p, "quote": attr["quote"], "start": p["segment_start"] + attr["start"], "end": p["segment_start"] + attr["end"]}
                        c.execute("INSERT INTO kp_facts VALUES(?,?,?,?,?,?)", (sha(row["id"] + str(index)), fact["group_key"], obj["id"], obj["hash"], dumps(fact), dumps(fact_p)))
                else:
                    endpoints = [all_rows.get(payload[x]) for x in ("source_candidate", "target_candidate")]
                    if any(not x or not x["object_id"] or (x["status"] != "accepted" and x["id"] not in accept) for x in endpoints):
                        raise ValueError("采纳关系前必须采纳两端实体")
                    a, b = [c.execute("SELECT * FROM objects WHERE id=?", (x["object_id"],)).fetchone() for x in endpoints]
                    if not a or not b or a["status"] in ("retired", "conflict") or b["status"] in ("retired", "conflict"):
                        raise ValueError("关系端点失效或存在未解决冲突")
                    if any(json.loads(x["provenance"]).get("adopted_hash") != o["hash"] for x, o in zip(endpoints, (a, b))):
                        raise ValueError("关系端点已修改，禁止复用过期抽取关系")
                    row["object_id"] = str(uuid.uuid4())
                    c.execute("INSERT INTO relations VALUES(?,?,?,?,?,?,?)", (row["object_id"], a["id"], b["id"], payload["kind"], dumps(p), a["version"], b["version"]))
                c.execute("UPDATE kp_candidates SET status='accepted',object_id=? WHERE id=?", (row["object_id"], row["id"]))
            for key, decision in [(k, "accepted") for k in accept] + [(k, "rejected") for k in reject]:
                c.execute("UPDATE kp_candidates SET status=? WHERE id=?", (decision, key))
                c.execute("INSERT INTO kp_reviews(job_id,candidate_id,decision,reviewer,note,created) VALUES(?,?,?,?,?,?)", (job_id, key, decision, reviewer, note, self.core.now()))
            remaining = c.execute("SELECT COUNT(*) FROM kp_candidates WHERE job_id=? AND status='pending'", (job_id,)).fetchone()[0]
            c.execute("UPDATE kp_jobs SET status=?,updated=? WHERE id=?", ("review_pending" if remaining else "reviewed", self.core.now(), job_id))
            if accept:
                self.core.revision(c)
                self.request_indexes(c)
        return self.job(job_id)

    def refresh_indexes(self) -> dict:
        """Drive the existing real derived indexes; a fallback is never called complete."""
        if not self.index_lock.acquire(blocking=False):
            return {"status": "busy"}
        try:
            with self.core.connect() as c:
                started = int(c.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0])
            detail = {"fts5": "ready"}
            try:
                state = self.core.semantic_consistency_after_build()
                if state.get("status") != "consistent":
                    state = self.core.semantica_rebuild()
                detail["graph"] = state
            except Exception as exc:
                detail["graph"] = {"status": "unavailable", "message": str(getattr(exc, "detail", exc))}
            try:
                state = self.core.EMBEDDINGS.call("/v2/status")
                if state.get("status") not in ("ready", "building"):
                    state = self.core.EMBEDDINGS.call("/v2/build")
                detail["embedding"] = state
            except Exception as exc:
                detail["embedding"] = {"status": "unavailable", "message": str(exc)}
            ready = detail["graph"].get("status") == "consistent" and detail["embedding"].get("status") == "ready"
            status = "ready" if ready else "waiting_vectors" if detail["embedding"].get("status") == "building" else "blocked"
            with self.core.connect() as c:
                c.execute('BEGIN IMMEDIATE')
                revision = int(c.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0])
                if revision != started:
                    status = "pending"
                    detail["message"] = "刷新期间主库已变化，将按新版本再次刷新"
                elif ready:
                    # Graph is versioned, FTS lives in this SQLite transaction. Publish
                    # the vector pointer only after all components match this revision.
                    activated = self.core.EMBEDDINGS.call('/v2/activate')
                    if activated.get('status') != 'ready':
                        raise ValueError('向量发布验证失败，保留上一发布记录')
                    detail['embedding'] = activated
                    from ..change_queue import publish
                    publish(self.core, c, revision, detail)
                c.execute("UPDATE kp_index_requests SET status=?,detail=?,updated=? WHERE revision<=? AND status!='ready'", (status, dumps(detail), self.core.now(), revision))
            return {"status": status, "revision": revision, **detail}
        finally:
            self.index_lock.release()

    def maintenance(self):
        while not self.stop.wait(5):
            try:
                self.manage_pending()
            except Exception:
                # A failed managed job must not stop unrelated index maintenance.
                pass
            from ..change_queue import enqueue
            try:
                enqueue(self.core)
                with self.core.connect() as c:
                    pending = c.execute("SELECT 1 FROM kp_index_requests WHERE status IN ('pending','waiting_vectors') LIMIT 1").fetchone()
            except Exception:
                # A transient database lock must not kill the durable queue consumer.
                # The cursor was not advanced, so the next iteration resumes safely.
                continue
            if pending:
                try:
                    self.refresh_indexes()
                except Exception as exc:
                    with self.core.connect() as c:
                        c.execute("UPDATE kp_index_requests SET status='blocked',detail=?,updated=? WHERE status IN ('pending','waiting_vectors')", (dumps({"error": str(exc)[:1000]}), self.core.now()))

    def manage(self, job_id):
        job = self.job(job_id)
        with self.core.connect() as c:
            c.execute("INSERT OR IGNORE INTO kp_managed_jobs VALUES(?,?,?,?)",
                      (job_id, 'pending', '由后台 Agent 处理；自动校验只采纳为候选', self.core.now()))
        return {**job, 'managed': True}

    def manage_pending(self):
        with self.core.connect() as c:
            rows = c.execute("SELECT job_id FROM kp_managed_jobs WHERE status IN ('pending','waiting_model','processing') ORDER BY updated LIMIT 20").fetchall()
        for row in rows:
            job_id = row['job_id']
            state, detail = 'processing', ''
            try:
                job = self.job(job_id)
                if job['status'] in ('parsed', 'interrupted'):
                    if not self.runtime.status().get('configured'):
                        state, detail = 'waiting_model', '原文已保存；等待配置知识抽取模型'
                    else:
                        self.queue(job_id)
                elif job['status'] == 'review_pending':
                    # Automatic source checks never stand in for named human engineering review.
                    if any(x['conflicts'] or x['provenance'].get('locator_ambiguous') for x in job['candidates']):
                        state, detail = 'needs_attention', '存在冲突或出处歧义，已保留候选供 Agent 核查'
                    else:
                        ids = [x['id'] for x in job['candidates'] if x['status'] == 'pending']
                        if ids:
                            self.review(job_id, ids, [], 'AI / 来源校验', '后台核对原件哈希、逐字引文和引用端点；仅登记候选，不构成人工工程复核')
                        state = 'complete'
                elif job['status'] in ('reviewed', 'no_candidates'):
                    state = 'complete'
                elif job['status'] == 'failed':
                    state, detail = 'needs_attention', job['error']
            except Exception as exc:
                state, detail = 'needs_attention', str(exc)[:1000]
            with self.core.connect() as c:
                c.execute('UPDATE kp_managed_jobs SET status=?,detail=?,updated=? WHERE job_id=?', (state, detail, self.core.now(), job_id))

    def status(self) -> dict:
        with self.core.connect() as c:
            jobs = {r[0]: r[1] for r in c.execute("SELECT status,COUNT(*) FROM kp_jobs GROUP BY status")}
            candidates = {r[0]: r[1] for r in c.execute("SELECT status,COUNT(*) FROM kp_candidates GROUP BY status")}
            latest = [dict(r) for r in c.execute("SELECT * FROM kp_index_requests ORDER BY created DESC LIMIT 5")]
            for row in latest:
                row["detail"] = json.loads(row["detail"])
        return {"protocol": VERSION, "jobs": jobs, "candidates": candidates, "index_requests": latest,
                "runtime": self.runtime.status(), "engineering_approved": False,
                "scope": "仅覆盖显式提交的文件；不是全磁盘或全库治理完成声明"}
