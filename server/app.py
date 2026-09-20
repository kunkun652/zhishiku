from __future__ import annotations

import json
import mimetypes
import os
import re
import sqlite3
import subprocess
import sys
import threading
import atexit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "knowledge.db"
APP = ROOT / "app"
MODEL_STATUS = ROOT / "runtime" / "model-status.json"
MESH_FILES = {
    "plate": ROOT / "data" / "samples" / "plate.mesh.json",
    "wingbox": ROOT / "data" / "samples" / "wingbox.mesh.json",
    "framedeck": ROOT / "data" / "samples" / "framedeck.mesh.json",
}


class DshRuntime:
    """Own one local DSH process and retain its launch URL only in memory."""

    def __init__(self):
        self.process = None
        self.authenticated_url = ""
        self.error = ""
        self.ready = threading.Event()
        self.lock = threading.Lock()

    def start(self):
        with self.lock:
            if self.process and self.process.poll() is None:
                return
            bundle = ROOT / "runtime" / "cae-dsh-app"
            node = bundle / "runtime" / "node" / "node.exe"
            dsh = bundle / "runtime" / "dsh" / "node_modules" / "@deepseek-ai" / "dsh" / "lib" / "bin.js"
            patch = ROOT / "integrations" / "dsh" / "cae-kb.cordis.yml"
            dsh_home = ROOT / "runtime" / "dsh-home"
            run_dir = ROOT / "runtime" / "run"
            log_dir = ROOT / "runtime" / "logs"
            for directory in (dsh_home, run_dir, log_dir):
                directory.mkdir(parents=True, exist_ok=True)
            cae_api_url = os.environ.get("CAE_AGENT_API_URL", "").strip().rstrip("/")
            if not re.fullmatch(r"http://127\.0\.0\.1:\d{2,5}", cae_api_url):
                raise RuntimeError("project CAE API endpoint is missing or invalid")
            env = dict(os.environ)
            env.update({
                "HOME": str(dsh_home), "USERPROFILE": str(dsh_home), "DSH_HOME": str(dsh_home),
                "DSH_PERMISSION_MODE": "read-only", "DSH_TELEMETRY_MODE": "DISABLED",
                "CAE_AGENT_SKILLS_DIR": str(bundle / "skills"),
                "CAE_AGENT_API_URL": cae_api_url,
                "CAE_AGENT_PYTHON": str(bundle / "runtime" / "python" / "python.exe"),
                "CAE_AGENT_MCP_SCRIPT": str(bundle / "tools" / "cae_viewer_mcp" / "mcp_server.py"),
                "CAE_AGENT_MCP_CWD": str(bundle / "tools" / "cae_viewer_mcp"),
                "CAE_KB_PYTHON": str(bundle / "runtime" / "python" / "python.exe"),
                "CAE_KB_MCP_SCRIPT": str(ROOT / "integrations" / "dsh" / "kb_mcp_server.py"),
                "CAE_KB_ROOT": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1",
            })
            stderr = (log_dir / "dsh.err.log").open("ab")
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            self.authenticated_url = ""; self.error = ""; self.ready.clear()
            self.process = subprocess.Popen(
                [str(node), str(dsh), "--profile", "web", "--patch", str(patch), "--no-open", "--host", "127.0.0.1", "--port", "3088"],
                cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=stderr,
                text=True, encoding="utf-8", errors="replace", creationflags=flags,
            )
            (run_dir / "dsh.pid").write_text(str(self.process.pid), encoding="ascii")
            threading.Thread(target=self._read_stdout, daemon=True).start()

    def _read_stdout(self):
        try:
            for line in self.process.stdout:
                match = re.search(r"dsh web:\s+(http://127\.0\.0\.1:3088/\?[^\s()]+)", line)
                if match:
                    self.authenticated_url = match.group(1)
                    self.ready.set()
                elif any(word in line.lower() for word in ("error", "failed", "exception")):
                    self.error = re.sub(r"http://127\.0\.0\.1:3088/\?[^\s()]+", "[authenticated-url-redacted]", line).strip()[:1000]
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
        finally:
            if self.process and self.process.poll() is not None:
                self.error = self.error or f"DSH exited with code {self.process.returncode}"
            if not self.ready.is_set():
                self.ready.set()

    def status(self):
        process_alive = bool(self.process and self.process.poll() is None)
        return {
            "state": "ready" if process_alive and bool(self.authenticated_url) else ("starting" if process_alive else "failed"),
            "process_alive": process_alive, "authenticated": bool(self.authenticated_url),
            "port": 3088, "pid": self.process.pid if process_alive else None,
            "viewer_api_url": os.environ.get("CAE_AGENT_API_URL"),
            "error": self.error or None,
        }

    def stop(self):
        process = self.process
        if process and process.poll() is None:
            process.terminate()
            try: process.wait(timeout=8)
            except subprocess.TimeoutExpired: process.kill()


DSH_RUNTIME = DshRuntime()
atexit.register(DSH_RUNTIME.stop)


def connect():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    return db


def row_dict(row):
    data = dict(row)
    for key in ("data_json", "metadata_json", "failures_json"):
        if key in data:
            try:
                data[key.removesuffix("_json")] = json.loads(data.pop(key))
            except Exception:
                pass
    return data


def model_status() -> dict:
    default = {
        "state": "unconfigured",
        "connected": False,
        "label": "未配置",
        "reason": "隔离 DSH 尚未完成模型配置；MCP 可用不等于模型调用通过。",
    }
    try:
        data = json.loads(MODEL_STATUS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
    state = data.get("state")
    if state not in {"unconfigured", "configured_unverified", "call_passed"}:
        return default
    labels = {"unconfigured": "未配置", "configured_unverified": "已配置、未验证", "call_passed": "真实调用通过"}
    return {
        "state": state,
        "connected": state == "call_passed",
        "label": labels[state],
        "reason": data.get("reason") or labels[state],
        "verified_at": data.get("verified_at"),
    }


def fts_expression(term: str) -> str:
    tokens = re.findall(r"[^\W_]+", term, flags=re.UNICODE)
    return " AND ".join('"' + token.replace('"', '""') + '"' for token in tokens[:20])


def package_gaps(objects: list[dict], assets: list[dict], missing_assets: list[str]) -> list[str]:
    gaps: list[str] = []
    cases = [obj for obj in objects if obj["type"] == "Case"]
    if not cases:
        gaps.append("缺少案例对象")
    if len(cases) > 1:
        gaps.append("选择了多个相互独立的案例；必须拆分任务包")
    for case in cases:
        readiness = case.get("data", {}).get("execution_readiness", {})
        if readiness.get("ready") is not True:
            details = readiness.get("gaps") or ["案例未声明通过执行就绪检查"]
            gaps.extend(f"{case['title']}：{detail}" for detail in details)
    types = {obj["type"] for obj in objects}
    if "材料卡" not in types:
        gaps.append("缺少材料卡")
    if "工况卡" not in types:
        gaps.append("缺少工况卡")
    if cases and ("材料卡" in types or "工况卡" in types):
        bindings = cases[0].get("data", {}).get("reviewed_bindings", {})
        if not bindings.get("material_object_id"):
            gaps.append("所选材料卡未与案例建立经审核的材料绑定")
        if not bindings.get("condition_object_id"):
            gaps.append("所选工况卡未与案例建立经审核的工况绑定")
    if missing_assets:
        gaps.append("缺少登记资产依赖：" + ", ".join(sorted(missing_assets)))
    if not assets and cases:
        gaps.append("案例没有可锁定的登记资产")
    return list(dict.fromkeys(gaps))


class Handler(BaseHTTPRequestHandler):
    server_version = "CaeKnowledgeDemo/0.2"

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}", flush=True)

    def send_json(self, payload, status=200):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def body_json(self):
        length = min(int(self.headers.get("Content-Length", "0")), 1024 * 1024)
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        url = urlparse(self.path)
        path, query = url.path, parse_qs(url.query)
        if path == "/api/dsh/status":
            self.send_json({**DSH_RUNTIME.status(), "deepseek": model_status()}); return
        if path == "/dsh/embed":
            host = self.headers.get("Host", "")
            referer = self.headers.get("Referer", "")
            fetch_dest = self.headers.get("Sec-Fetch-Dest", "")
            allowed_host = host in {"127.0.0.1:8765", "localhost:8765"}
            allowed_referer = referer.startswith("http://127.0.0.1:8765/") or referer.startswith("http://localhost:8765/")
            if not allowed_host or not allowed_referer or fetch_dest != "iframe":
                self.send_json({"error": "embedded_dsh_navigation_required"}, 403); return
            if not DSH_RUNTIME.authenticated_url:
                self.send_json({"error": "dsh_not_ready"}, 503); return
            self.send_response(302)
            self.send_header("Location", DSH_RUNTIME.authenticated_url)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Length", "0")
            self.end_headers(); return
        if path == "/api/health":
            with connect() as db:
                counts = dict(db.execute("SELECT type,count(*) FROM objects WHERE active=1 GROUP BY type"))
                assets = db.execute("SELECT count(*) FROM assets").fetchone()[0]
                versions = db.execute("SELECT count(*) FROM object_versions").fetchone()[0]
            self.send_json({"status": "ok", "database": DB.exists(), "objects": sum(counts.values()), "types": counts, "assets": assets, "object_versions": versions, "deepseek": model_status()})
            return
        if path == "/api/search":
            term = query.get("q", [""])[0].strip()
            typ = query.get("type", [""])[0].strip()
            with connect() as db:
                rows = []
                expression = fts_expression(term) if term else ""
                if expression:
                    try:
                        sql = "SELECT o.*, bm25(search_fts) rank FROM search_fts JOIN objects o ON o.id=search_fts.object_id WHERE o.active=1 AND search_fts MATCH ?"
                        args = [expression]
                        if typ:
                            sql += " AND o.type=?"; args.append(typ)
                        rows = db.execute(sql + " ORDER BY rank LIMIT 50", args).fetchall()
                    except sqlite3.OperationalError:
                        rows = []
                if term and not rows:
                    sql = "SELECT *,0 rank FROM objects WHERE active=1 AND (title LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\')"
                    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                    args = [f"%{escaped}%", f"%{escaped}%"]
                    if typ:
                        sql += " AND type=?"; args.append(typ)
                    rows = db.execute(sql + " ORDER BY type,title LIMIT 50", args).fetchall()
                elif not term:
                    sql = "SELECT * FROM objects WHERE active=1" + (" AND type=?" if typ else "") + " ORDER BY type,title LIMIT 100"
                    rows = db.execute(sql, ([typ] if typ else [])).fetchall()
            self.send_json({"query": term, "semantic_search": False, "items": [row_dict(row) for row in rows]})
            return
        if path.startswith("/api/objects/"):
            oid = unquote(path.split("/", 3)[3])
            with connect() as db:
                row = db.execute("SELECT * FROM objects WHERE id=? AND active=1", (oid,)).fetchone()
                history = [dict(item) for item in db.execute("SELECT version,content_hash,created_at FROM object_versions WHERE object_id=? ORDER BY version", (oid,))]
            if not row:
                self.send_json({"error": "object_not_found"}, 404); return
            payload = row_dict(row); payload["version_history"] = history
            self.send_json(payload); return
        if path == "/api/assets":
            with connect() as db:
                rows = db.execute("SELECT * FROM assets ORDER BY id").fetchall()
            self.send_json({"items": [row_dict(row) for row in rows]}); return
        if path.startswith("/api/assets/") and path.endswith("/file"):
            aid = unquote(path.split("/")[3]); requested = query.get("version", [None])[0]
            with connect() as db:
                if requested and requested.isdigit():
                    row = db.execute("SELECT asset_id id,name,local_path,sha256,size,version FROM asset_versions WHERE asset_id=? AND version=?", (aid, int(requested))).fetchone()
                else:
                    row = db.execute("SELECT * FROM assets WHERE id=?", (aid,)).fetchone()
            if not row:
                self.send_json({"error": "asset_not_found"}, 404); return
            file_path = Path(row["local_path"])
            if not file_path.is_file() or ROOT not in file_path.resolve().parents:
                self.send_json({"error": "registered_local_copy_unavailable"}, 404); return
            raw = file_path.read_bytes()
            ascii_name = re.sub(r"[^A-Za-z0-9._-]", "_", file_path.name) or "asset"
            disposition = f"inline; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(file_path.name, safe='')}"
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(file_path.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Content-Disposition", disposition)
            self.send_header("X-Content-SHA256", row["sha256"])
            self.end_headers(); self.wfile.write(raw); return
        if path.startswith("/api/assets/"):
            aid = unquote(path.split("/", 3)[3])
            with connect() as db:
                row = db.execute("SELECT * FROM assets WHERE id=?", (aid,)).fetchone()
                history = [dict(item) for item in db.execute("SELECT version,sha256,size,imported_at FROM asset_versions WHERE asset_id=? ORDER BY version", (aid,))]
            if not row:
                self.send_json({"error": "asset_not_found"}, 404); return
            payload = row_dict(row); payload["version_history"] = history
            self.send_json(payload); return
        if path == "/api/graph":
            seed = query.get("seed", [""])[0]
            with connect() as db:
                edges = db.execute("SELECT * FROM edges WHERE source_id=? OR target_id=?", (seed, seed)).fetchall() if seed else db.execute("SELECT * FROM edges WHERE method!='CSV 行解析' LIMIT 250").fetchall()
                ids = {value for edge in edges for value in (edge["source_id"], edge["target_id"])}
                nodes = []
                for oid in ids:
                    row = db.execute("SELECT id,type,title,status,source_asset_id,'object' node_kind FROM objects WHERE id=? AND active=1", (oid,)).fetchone()
                    if row:
                        nodes.append(dict(row)); continue
                    row = db.execute("SELECT id,kind type,name title,status,NULL source_asset_id,'asset' node_kind FROM assets WHERE id=?", (oid,)).fetchone()
                    if row: nodes.append(dict(row))
            self.send_json({"nodes": nodes, "edges": [dict(edge) for edge in edges]}); return
        if path.startswith("/api/mesh/"):
            name = unquote(path.split("/")[3])
            target = MESH_FILES.get(name)
            if not target:
                self.send_json({"error": "mesh_not_registered"}, 404); return
            self._send_static(target, "application/json; charset=utf-8"); return
        if path == "/api/result/plate":
            self._send_static(ROOT / "data" / "samples" / "plate.result.json", "application/json; charset=utf-8"); return
        target = APP / (path.lstrip("/") or "index.html")
        if target.is_dir(): target /= "index.html"
        if APP not in target.resolve().parents and target.resolve() != APP.resolve():
            self.send_error(403); return
        self._send_static(target)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/package":
            data = self.body_json(); ids = data.get("object_ids", [])
            if not isinstance(ids, list) or len(ids) > 100:
                self.send_json({"error": "invalid_object_ids"}, 400); return
            with connect() as db:
                objects = [row_dict(row) for oid in ids if (row := db.execute("SELECT * FROM objects WHERE id=? AND active=1", (oid,)).fetchone())]
                asset_ids = {obj.get("source_asset_id") for obj in objects if obj.get("source_asset_id")}
                for obj in objects:
                    related = obj.get("data", {}).get("asset_ids", [])
                    if isinstance(related, list): asset_ids.update(value for value in related if isinstance(value, str))
                assets, missing = [], []
                for aid in sorted(asset_ids):
                    row = db.execute("SELECT * FROM assets WHERE id=?", (aid,)).fetchone()
                    if row: assets.append(row_dict(row))
                    else: missing.append(aid)
            gaps = package_gaps(objects, assets, missing)
            payload = {
                "schema": "cae-task-package/2",
                "snapshot_policy": "对象版本、内容哈希、资产版本与 SHA-256 均已锁定；后续源变化不会改写本快照标识。",
                "objects": objects, "assets": assets, "gaps": gaps,
                "executable": len([obj for obj in objects if obj["type"] == "Case"]) == 1 and not gaps,
            }
            self.send_json(payload); return
        if path == "/api/dsh/open":
            origin = self.headers.get("Origin", "")
            if origin not in {"http://127.0.0.1:8765", "http://localhost:8765"}:
                self.send_json({"error": "origin_not_allowed"}, 403); return
            script = ROOT / "scripts" / "open_dsh.ps1"
            if not script.is_file():
                self.send_json({"error": "open_script_missing"}, 500); return
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.Popen(["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)], cwd=str(ROOT), creationflags=flags)
            self.send_json({"status": "opening", "message": "DSH 将由本机运行时在默认浏览器中完成一次性令牌交换；令牌不返回给知识库页面。"}, 202); return
        self.send_json({"error": "read_only_or_unknown_endpoint"}, 404)

    def _send_static(self, path: Path, mime=None):
        if not path.is_file():
            self.send_error(404); return
        raw = path.read_bytes(); self.send_response(200)
        self.send_header("Content-Type", mime or mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers(); self.wfile.write(raw)


if __name__ == "__main__":
    if not DB.is_file(): raise SystemExit("数据库不存在，请先运行 scripts/import_data.py")
    host, port = "127.0.0.1", int(os.environ.get("CAE_KB_PORT", "8765"))
    DSH_RUNTIME.start()
    DSH_RUNTIME.ready.wait(timeout=30)
    print(f"CAE 知识库: http://{host}:{port}", flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()
