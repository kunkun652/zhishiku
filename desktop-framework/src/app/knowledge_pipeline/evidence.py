"""A single retrieval contract shared by the UI and the read-only answer Agent."""
from __future__ import annotations
import json
import uuid
from .contracts import bounded_text, dumps, sha, validate_answer

FILTERS = {"type", "analysis_type", "status", "category", "designation", "object_id"}


class EvidenceService:
    def __init__(self, pipeline):
        self.pipeline = pipeline
        self.core = pipeline.core

    def _valid_provenance(self, p, c) -> bool:
        try:
            file, _ = self.core.asset(p["file_id"])
            obj = c.execute("SELECT hash,status FROM objects WHERE id=?", (p["source_object_id"],)).fetchone()
            chunk = c.execute("SELECT text,file_id FROM chunks WHERE id=?", (p["chunk_id"],)).fetchone()
            return bool(file["sha256"] == p["file_hash"] and obj and obj["hash"] == p["source_object_hash"]
                        and obj["status"] not in ("retired", "conflict") and chunk and chunk["file_id"] == p["file_id"]
                        and sha(chunk["text"]) == p["chunk_hash"] and p["quote"] in chunk["text"]
                        and self.pipeline.chunk_eligible(c, p["chunk_id"], chunk["text"]))
        except Exception:
            return False

    def retrieve(self, query: str, *, filters=None, top_k: int = 10) -> dict:
        bounded_text(query, "query", 4000)
        if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 20:
            raise ValueError("top_k 必须为 1–20 的整数")
        filters = {} if filters is None else filters
        if not isinstance(filters, dict) or set(filters) - FILTERS or any(not isinstance(v, str) or len(v) > 200 for v in filters.values()):
            raise ValueError("检索筛选字段不合法")
        if filters.get("status") in ("retired", "conflict"):
            raise ValueError("停用或冲突对象不能作为 Agent 的事实依据")
        result = self.core.search(q=query, mode="hybrid", graph_backend="semantica", limit=top_k, **filters)
        pack = {"schema": "zhiheng-evidence-pack/1", "query": query, "objects": [], "evidence": [],
                "relations": [], "conflicts": [], "gaps": [], "retrieval": result.get("run", {}),
                "embedding": result.get("embedding", {}), "graph": result.get("graph", {}),
                "engineering_approved": False}
        seen, text_budget = set(), 6000
        with self.core.connect() as c:
            revision = int(c.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0])
            if result.get("run", {}).get("revision") not in (None, revision):
                raise ValueError("检索期间主库已变化，请重新检索")
            pack["revision"] = revision
            def append(evidence):
                nonlocal text_budget
                text = evidence.get("quote", "")
                key = sha(dumps(evidence))
                if key in seen or not text:
                    return
                if len(text) > text_budget:
                    pack["gaps"].append("证据包达到字符预算；更多出处可在原对象中查看")
                    return
                text_budget -= len(text)
                seen.add(key)
                pack["evidence"].append({"id": "E" + str(len(pack["evidence"]) + 1), **evidence})
            for item in result.get("items", []):
                current = c.execute("SELECT hash,status FROM objects WHERE id=?", (item["id"],)).fetchone()
                if not current or current["hash"] != item["hash"] or current["status"] in ("retired", "conflict"):
                    continue
                pack["objects"].append({k: item.get(k) for k in ("id", "title", "type", "version", "hash", "status", "retrieval_channels", "fusion_score")})
                for candidate in c.execute("SELECT provenance,conflicts FROM kp_candidates WHERE object_id=? AND kind='entity' AND status='accepted'", (item["id"],)):
                    p = json.loads(candidate["provenance"])
                    pack["conflicts"].extend(json.loads(candidate["conflicts"]))
                    if p.get("adopted_hash") and p["adopted_hash"] != item["hash"]:
                        pack["gaps"].append(item["title"] + "：对象已修改，旧抽取出处未用于回答")
                        continue
                    if self._valid_provenance(p, c):
                        append({"object_id": item["id"], "object_hash": item["hash"], "kind": "source_quote", **p})
                    else:
                        pack["gaps"].append(item["title"] + "：原始依据已变化，抽取出处未用于回答")
                for fact in c.execute("SELECT payload,provenance FROM kp_facts WHERE object_id=? AND object_hash=?", (item["id"], item["hash"])):
                    p = json.loads(fact["provenance"])
                    if self._valid_provenance(p, c):
                        append({"object_id": item["id"], "object_hash": item["hash"], "kind": "attribute_quote",
                                "attribute": json.loads(fact["payload"]), **p})
                for hit in item.get("evidence", []):
                    fid, text = hit.get("file_id"), hit.get("text", "")
                    if not fid or not text:
                        continue
                    try:
                        file, _ = self.core.asset(fid)
                    except Exception:
                        pack["gaps"].append("某原件不可用或校验失败，已排除该引用")
                        continue
                    matches = c.execute("SELECT id,text FROM chunks WHERE object_id=? AND file_id=? AND page=?", (item["id"], fid, hit.get("page", 0))).fetchall()
                    row = next((r for r in matches if text in r["text"]), None)
                    if row and self.pipeline.chunk_eligible(c, row["id"], row["text"]):
                        append({"kind": "source_quote", "object_id": item["id"], "object_hash": item["hash"],
                                "file_id": fid, "file_hash": file["sha256"], "page": hit.get("page", 0),
                                "source_object_id": item["id"], "source_object_hash": item["hash"],
                                "chunk_id": row["id"], "chunk_hash": sha(row["text"]), "quote": text,
                                "assertion_kind": "source_text_not_engineering_approval"})
                for path in item.get("relation_paths", []):
                    valid = []
                    for edge in path:
                        saved = c.execute("SELECT r.* FROM relations r JOIN objects a ON a.id=r.source AND a.version=r.source_version JOIN objects b ON b.id=r.target AND b.version=r.target_version WHERE r.id=? AND a.status NOT IN ('retired','conflict') AND b.status NOT IN ('retired','conflict')", (edge["id"],)).fetchone()
                        if not saved or saved["evidence"] != edge["evidence"]:
                            break
                        try:
                            provenance = json.loads(saved["evidence"])
                        except (ValueError, TypeError):
                            provenance = None
                        if isinstance(provenance, dict) and "file_id" in provenance and not self._valid_provenance(provenance, c):
                            break
                        valid.append(dict(saved))
                    else:
                        if valid:
                            pack["relations"].append(valid)
            if not pack["evidence"]:
                pack["gaps"].append("没有通过出处核验的可引用正文；不生成无依据答案")
            pack["gaps"].extend(result.get("run", {}).get("degradations", []))
        pack["gaps"] = list(dict.fromkeys(pack["gaps"]))
        while len(dumps(pack)) > 100000 and pack["relations"]:
            pack["relations"].pop()
            if "关系上下文达到预算，部分路径未纳入回答" not in pack["gaps"]:
                pack["gaps"].append("关系上下文达到预算，部分路径未纳入回答")
        if len(dumps(pack)) > 100000:
            raise ValueError("证据元数据超过预算，请缩小检索范围")
        pack["hash"] = sha(dumps(pack))
        return pack

    def ask(self, query: str, filters=None, top_k: int = 10) -> dict:
        pack = self.retrieve(query, filters=filters, top_k=top_k)
        run_id = uuid.uuid4().hex
        if not pack["evidence"]:
            result = {"status": "insufficient_evidence", "claims": [], "gaps": pack["gaps"]}
        else:
            try:
                generated = self.pipeline.runtime.call("answer", {"query": query, "evidence_pack": pack})
                checked = validate_answer({k: generated[k] for k in ("claims", "gaps")}, {e["id"] for e in pack["evidence"]})
                with self.core.connect() as c:
                    current = int(c.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0])
                    if current != pack["revision"]:
                        raise ValueError("生成期间资料已变化，已丢弃答案，请重新提问")
                    if any(not self._valid_provenance(e, c) for e in pack["evidence"]):
                        raise ValueError("生成期间原件、正文或质量标记发生变化，已丢弃答案")
                result = {"status": "answered" if checked["claims"] else "insufficient_evidence", **checked,
                          "model": generated.get("model"), "semantica_version": generated.get("semantica_version")}
            except Exception as exc:
                result = {"status": "model_unavailable_or_rejected", "claims": [], "gaps": [str(exc)]}
        result.update({"run_id": run_id, "evidence_pack": pack, "tools": ["hybrid_retrieve", "verify_source_evidence"],
                       "engineering_approved": False, "read_only": True, "solver_executed": False})
        with self.core.connect() as c:
            c.execute("INSERT INTO kp_agent_runs VALUES(?,?,?,?,?,?)", (run_id, query, result["status"], dumps(pack),
                      dumps({k: v for k, v in result.items() if k != "evidence_pack"}), self.core.now()))
        return result
