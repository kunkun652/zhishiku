from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "knowledge.db"
BASE = "http://127.0.0.1:8765"


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest().upper()


def request_json(path, method="GET", payload=None):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


checks = []


def check(name, ok, evidence):
    checks.append({"name": name, "passed": bool(ok), "evidence": evidence})


baseline = json.loads((ROOT / "docs" / "验收基线.json").read_text(encoding="utf-8"))
for item in baseline["originals"]:
    current = sha(item["path"])
    check("设计原件哈希不变: " + Path(item["path"]).name, current == item["sha256"], current)

db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row
types = dict(db.execute("SELECT type,count(*) FROM objects WHERE active=1 GROUP BY type"))
check("当前对象只含活动版本", sum(types.values()) == db.execute("SELECT count(*) FROM objects WHERE active=1").fetchone()[0], types)
check("四类卡片均存在", all(types.get(card, 0) > 0 for card in ("材料卡", "术语卡", "网格策略卡", "工况卡")), types)
check("五个独立案例存在", types.get("Case") == 5, types)
check("对象历史表保留版本", db.execute("SELECT count(*) FROM object_versions").fetchone()[0] >= sum(types.values()), db.execute("SELECT count(*) FROM object_versions").fetchone()[0])

assets = [dict(row) for row in db.execute("SELECT * FROM assets")]
hash_rows = []
for asset in assets:
    source_ok = Path(asset["source_path"]).is_file() and sha(asset["source_path"]) == asset["sha256"]
    copy_ok = Path(asset["local_path"]).is_file() and sha(asset["local_path"]) == asset["sha256"]
    hash_rows.append({"id": asset["id"], "source_ok": source_ok, "copy_ok": copy_ok, "version": asset["version"], "sha256": asset["sha256"]})
check("11个登记资产源文件与版本副本哈希一致", len(hash_rows) == 11 and all(row["source_ok"] and row["copy_ok"] for row in hash_rows), hash_rows)
frame_asset = next(row for row in assets if row["id"] == "cad-frame-step")
check("frame.STEP只读副本与指定源哈希一致", frame_asset["sha256"] == "A89DDB621F827154411CFFCBC0F5E585AA8C18E367846BCB8FB3E9EBF08E1098" and frame_asset["size"] == 14930768, {"sha256": frame_asset["sha256"], "size": frame_asset["size"], "source": frame_asset["source_path"], "copy": frame_asset["local_path"]})
check("wingbox重复路径只登记一个资产", sha(r"D:\wingbox.bdf") == sha(r"D:\wingbox_stitched_together-000.bdf") and len([row for row in assets if row["id"] == "mesh-wingbox"]) == 1, sha(r"D:\wingbox.bdf"))

health = request_json("/api/health")
check("API健康且统计一致", health["status"] == "ok" and health["objects"] == sum(types.values()) and health["assets"] == 11, health)
check("DeepSeek状态为三态枚举", health["deepseek"]["state"] in {"unconfigured", "configured_unverified", "call_passed"} and health["deepseek"]["connected"] == (health["deepseek"]["state"] == "call_passed"), health["deepseek"])

hyphen = request_json("/api/search?q=" + urllib.parse.quote("DPW-W1"))
check("带连字符普通检索不进入FTS语法错误", any(row["id"] == "case-cad-dpw" for row in hyphen["items"]), [row["id"] for row in hyphen["items"]])
query_evidence = {}
for term in ("Pazy", "网格", "材料", "framedeck", "frame STEP"):
    result = request_json("/api/search?q=" + urllib.parse.quote(term))
    query_evidence[term] = [{"id": row["id"], "source": row["source_asset_id"], "locator": row["locator"]} for row in result["items"][:3]]
check("四个真实查询返回来源定位", all(query_evidence[term] and all(row["source"] and row["locator"] for row in query_evidence[term]) for term in query_evidence), query_evidence)

download = urllib.request.urlopen(BASE + "/api/assets/card-term/file", timeout=10)
disposition = download.headers.get("Content-Disposition", "")
download.read(32)
check("中文资产使用RFC5987下载头", download.status == 200 and "filename*=UTF-8''" in disposition, disposition)
source = request_json("/api/objects/doc-pazy-p1")
check("PDF详情含正文页码与原件片段", bool(source.get("body")) and source.get("data", {}).get("page") == 1 and source.get("data", {}).get("asset_open_fragment") == "#page=1", {"body_length": len(source.get("body", "")), "data": source.get("data")})

material = request_json("/api/search?type=" + urllib.parse.quote("材料卡"))["items"][0]
condition = request_json("/api/search?type=" + urllib.parse.quote("工况卡"))["items"][0]
cad_package = request_json("/api/package", "POST", {"object_ids": [material["id"], condition["id"], "case-cad-dpw"]})
check("CAD加任意材料工况仍不可执行", cad_package["executable"] is False and any("绑定" in gap for gap in cad_package["gaps"]), cad_package["gaps"])
frame_package = request_json("/api/package", "POST", {"object_ids": ["case-cad-frame"]})
check("frame STEP任务包保守且关系待确认", frame_package["executable"] is False and {row["id"] for row in frame_package["assets"]} == {"cad-frame-step"} and any("framedeck" in gap for gap in frame_package["gaps"]), frame_package)
plate_package = request_json("/api/package", "POST", {"object_ids": ["case-fe-plate"]})
check("任务包收集案例data.asset_ids全部依赖", {row["id"] for row in plate_package["assets"]} == {"mesh-plate", "result-plate"}, [(row["id"], row["version"], row["sha256"]) for row in plate_package["assets"]])
check("任务包锁定对象与资产版本哈希", all(row.get("version") and row.get("content_hash") for row in plate_package["objects"]) and all(row.get("version") and row.get("sha256") for row in plate_package["assets"]), plate_package["snapshot_policy"])

expected = {
    "plate": (36, 25),
    "wingbox": (2675, 2657),
    "framedeck": (318738, 889052),
}
mesh_evidence = {}
for name, counts in expected.items():
    mesh = json.loads((ROOT / "data" / "samples" / f"{name}.mesh.json").read_text(encoding="utf-8"))
    mesh_evidence[name] = {key: mesh[key] for key in ("node_count", "element_count", "render_node_count", "boundary_face_count", "render_triangle_count", "render_line_count", "source_sha256")}
    check(f"{name} pyNastran计数与来源哈希", (mesh["node_count"], mesh["element_count"]) == counts and mesh["source_sha256"] == next(row["sha256"] for row in assets if row["id"] == mesh["asset_id"]), mesh_evidence[name])
frame = json.loads((ROOT / "data" / "samples" / "framedeck.mesh.json").read_text(encoding="utf-8"))
check("framedeck只输出CTETRA唯一外表面", frame["card_counts"].get("CTETRA") == 889052 and frame["surface_method"].endswith("外表面") and frame["boundary_face_count"] == frame["render_triangle_count"], {key: frame[key] for key in ("surface_method", "boundary_face_count", "render_triangle_count")})

result = json.loads((ROOT / "data" / "samples" / "plate.result.json").read_text(encoding="utf-8"))
plate = json.loads((ROOT / "data" / "samples" / "plate.mesh.json").read_text(encoding="utf-8"))
check("plate OP2真实结果字段解析", result.get("max") is not None and len(result.get("values", [])) == plate["render_node_count"], {key: result.get(key) for key in ("variable", "component", "unit", "subcase", "min", "max")})

ui = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
check("Three渲染生命周期完整释放", all(text in ui for text in ("cancelAnimationFrame", "controls.dispose()", "geometry.dispose()", "material.dispose()", "forceContextLoss", "renderer.domElement.remove()", "state.viewerToken")), "动画、控制器、几何、材质、上下文、旧画布和异步令牌均释放")
start = (ROOT / "scripts" / "start.ps1").read_text(encoding="utf-8")
open_script = (ROOT / "scripts" / "open_dsh.ps1").read_text(encoding="utf-8")
server_source = (ROOT / "server" / "app.py").read_text(encoding="utf-8")
dsh_patch = (ROOT / "integrations" / "dsh" / "cae-kb.cordis.yml").read_text(encoding="utf-8")
check("DSH子进程环境隔离且不改父HOME", all(text in server_source for text in ('"HOME": str(dsh_home)', '"USERPROFILE": str(dsh_home)', 'env=env', 'stdout=subprocess.PIPE')) and "$env:HOME =" not in start and "$env:USERPROFILE =" not in start, "API以独立环境托管DSH，认证启动行仅在内存读取")
check("DSH安全嵌入入口保留原生鉴权", all(text in server_source for text in ('if path == "/dsh/embed"', 'fetch_dest != "iframe"', 'self.send_header("Location", DSH_RUNTIME.authenticated_url)', 'self.send_header("Referrer-Policy", "no-referrer")')) and "frame.src='/dsh/embed'" in ui and 'referrerpolicy="same-origin"' in ui, "同源iframe入口换取DSH签名Cookie，随后直连原生DSH")
check("DSH启动链不再引用原CAE-AGENT-DSH目录", r"D:\CAE-AGENT-DSH" not in start and r"D:\CAE-AGENT-DSH" not in open_script and '"runtime" / "cae-dsh-app"' in server_source, "Node、DSH、Python MCP 均解析到项目 runtime/cae-dsh-app")
check("安全打开脚本进入嵌入助手页", "http://127.0.0.1:8765/#assistant" in open_script and (ROOT / "打开DSH.ps1").is_file(), "外部快捷入口也落到知识工作台内的原生DSH界面")
check("启动流程按项目PID动态发现CAE API", all(text in start for text in ("cae-client.pid", "Get-NetTCPConnection", "model.summary", "CAE_AGENT_API_URL = $caeApiUrl")) and "59312" not in start and "60890" not in start, "复制版cae-agent.exe进程的监听端口经只读model.summary确认后注入API")
check("内嵌DSH同时装载知识与Viewer MCP", all(text in dsh_patch for text in ("id: cae-viewer-mcp", "@cae-agent/dsh-cae-viewer-mcp", "CAE_AGENT_API_URL", "id: mcp-cae-kb")) and all(text in server_source for text in ("CAE_AGENT_MCP_SCRIPT", "cae_viewer_mcp", "CAE_KB_MCP_SCRIPT")), "同一3088 Host patch包含两项MCP integration")

copy_manifest = json.loads((ROOT / "artifacts" / "dsh-copy-manifest.json").read_text(encoding="utf-8"))
check("DSH复制组件哈希相等且复制载荷无junction", copy_manifest["verification"]["all_unmodified_components_equal"] and copy_manifest["verification"]["copied_payload_reparse_points"] == 0 and copy_manifest["verification"]["runtime_generated_dsh_data_excluded"] and all(row["content_equal"] for row in copy_manifest["components"]), {row["name"]: row["content_equal"] for row in copy_manifest["components"]})
check("CAE preset、双Skill与Viewer MCP均在本地包", all(path.is_file() for path in (ROOT / "runtime/cae-dsh-app/presets/cae/preset.yml", ROOT / "runtime/cae-dsh-app/skills/cae-aerospace-static-analysis/SKILL.md", ROOT / "runtime/cae-dsh-app/skills/cae-geometry-meshing/SKILL.md", ROOT / "runtime/cae-dsh-app/tools/cae_viewer_mcp/mcp_server.py")), "本地 preset/skills/tools 完整")

try:
    urllib.request.urlopen("http://127.0.0.1:3088/", timeout=5)
    dsh_protected = False
except urllib.error.HTTPError as error:
    dsh_protected = error.code == 401
check("DSH根路径仍受令牌保护", dsh_protected, "未带令牌返回401")

dsh_status = request_json("/api/dsh/status")
check("知识服务托管的DSH运行时就绪", dsh_status["state"] == "ready" and dsh_status["authenticated"] is True and dsh_status["process_alive"] is True and "token" not in dsh_status, dsh_status)
try:
    urllib.request.urlopen(BASE + "/dsh/embed", timeout=5)
    embed_guarded = False
except urllib.error.HTTPError as error:
    embed_guarded = error.code == 403
check("DSH嵌入入口拒绝普通直访", embed_guarded, "缺少同源Referer和iframe目的时返回403")

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

embed_request = urllib.request.Request(BASE + "/dsh/embed", headers={"Referer": BASE + "/", "Sec-Fetch-Dest": "iframe"})
try:
    urllib.request.build_opener(NoRedirect).open(embed_request, timeout=5)
    embed_redirect_ok = False
except urllib.error.HTTPError as error:
    location = error.headers.get("Location", "")
    embed_redirect_ok = error.code == 302 and location.startswith("http://127.0.0.1:3088/") and "?" in location and error.headers.get("Cache-Control") == "no-store" and error.headers.get("Referrer-Policy") == "no-referrer"
check("受控iframe导航获得一次性原生DSH跳转", embed_redirect_ok, "302到本机3088且禁止缓存和引荐；认证地址不写证据")

runtime_logs = [ROOT / "runtime" / "logs" / name for name in ("api.out.log", "api.err.log", "dsh.err.log")]
token_logged = any("?token=" in path.read_text(encoding="utf-8", errors="replace") for path in runtime_logs if path.is_file())
check("DSH认证令牌未写入运行日志", not token_logged, [path.name for path in runtime_logs if path.is_file()])

with tempfile.TemporaryDirectory(prefix="cae-kb-version-test-") as temp:
    spec = importlib.util.spec_from_file_location("import_data_test", ROOT / "scripts" / "import_data.py")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    module.DB = Path(temp) / "test.db"; module.ASSET_STORE = Path(temp) / "assets"
    test_db = module.connect(); source_path = Path(temp) / "source.txt"; source_path.write_text("one", encoding="utf-8")
    a1 = module.upsert_asset(test_db, "asset", source_path, {}); a1_repeat = module.upsert_asset(test_db, "asset", source_path, {})
    source_path.write_text("two", encoding="utf-8"); a2 = module.upsert_asset(test_db, "asset", source_path, {})
    o1 = module.upsert_object(test_db, "object", "Type", "Title", "asset", "line=1", "one", {})
    o1_repeat = module.upsert_object(test_db, "object", "Type", "Title", "asset", "line=1", "one", {})
    o2 = module.upsert_object(test_db, "object", "Type", "Title", "asset", "line=1", "two", {})
    test_db.commit()
    asset_history = test_db.execute("SELECT count(*) FROM asset_versions WHERE asset_id='asset'").fetchone()[0]
    object_history = test_db.execute("SELECT count(*) FROM object_versions WHERE object_id='object'").fetchone()[0]
    check("同内容稳定且源变化生成不可变新版本", (a1["version"], a1_repeat["version"], a2["version"], o1, o1_repeat, o2, asset_history, object_history) == (1, 1, 2, 1, 1, 2, 2, 2), {"asset_versions": [a1["version"], a1_repeat["version"], a2["version"]], "object_versions": [o1, o1_repeat, o2], "history": [asset_history, object_history]})
    test_db.close()

sem = json.loads((ROOT / "artifacts" / "semantica-probe.json").read_text(encoding="utf-8"))
check("Semantica仅作为真实本地GraphBuilder探针", sem["status"] == "passed", sem)
mcp = json.loads((ROOT / "artifacts" / "mcp-probe.json").read_text(encoding="utf-8-sig"))
check("MCP初始化、8工具与真实调用", mcp["initialize"]["result"]["serverInfo"]["name"] == "cae-knowledge-mcp" and mcp["tool_count"] == 8 and not mcp["real_call"]["result"].get("isError"), {"tool_count": mcp["tool_count"], "tools": mcp["tool_names"]})
filtered = json.loads(mcp["type_filtered_call"]["result"]["content"][0]["text"])
check("kb_search的type参数真实筛选", bool(filtered["items"]) and {row["type"] for row in filtered["items"]} == {"材料卡"}, {"count": len(filtered["items"]), "types": sorted({row["type"] for row in filtered["items"]})})
preview = json.loads(mcp["three_d_preview_call"]["result"]["content"][0]["text"])
unsupported_preview = json.loads(mcp["unsupported_preview_call"]["result"]["content"][0]["text"])
check("三维资产预览直达对应模型", preview["preview_supported"] is True and preview["viewer_model"] == "wingbox" and preview["preview_url"].endswith("/?asset=mesh-wingbox#models") and 'new URLSearchParams(location.search).get(\'asset\')' in ui, preview)
check("未知预览格式保留原件且明确不支持", unsupported_preview["preview_supported"] is False and unsupported_preview["preview_url"] is None and unsupported_preview["file_url"].endswith("/api/assets/doc-pazy/file") and bool(unsupported_preview["preview_note"]), unsupported_preview)
viewer_mcp = json.loads((ROOT / "artifacts" / "viewer-mcp-probe.json").read_text(encoding="utf-8"))
check("复制版Viewer MCP发现工具并完成只读调用", viewer_mcp["server"]["name"] == "cae-viewer" and viewer_mcp["tool_count"] == 68 and viewer_mcp["read_only_call"] == "model_summary" and not viewer_mcp["is_error"], {"tool_count": viewer_mcp["tool_count"], "call": viewer_mcp["read_only_call"], "scope": viewer_mcp["scope"]})
embedded_mcp = json.loads((ROOT / "artifacts" / "embedded-dsh-mcp-evidence.json").read_text(encoding="utf-8"))
integrations = {row["entry_id"]: row for row in embedded_mcp["active_host_integrations"]}
check("同一内嵌DSH会话挂载双MCP", embedded_mcp["embedded_dsh"]["agent_preset"] == "cae" and embedded_mcp["embedded_dsh"]["session_cwd"] == str(ROOT) and all(integrations[key]["fiber_phase"] == "active" for key in ("include:cae-viewer-mcp", "include:mcp-cae-kb")), embedded_mcp["embedded_dsh"])
check("内嵌DSH双MCP工具清单与只读调用通过", embedded_mcp["tool_handshakes_and_read_only_calls"]["knowledge"]["tool_count"] == 8 and embedded_mcp["tool_handshakes_and_read_only_calls"]["knowledge"]["call_passed"] and embedded_mcp["tool_handshakes_and_read_only_calls"]["viewer"]["tool_count"] == 68 and embedded_mcp["tool_handshakes_and_read_only_calls"]["viewer"]["call_passed"] and embedded_mcp["project_cae_service"]["dynamic_api_url"] == viewer_mcp["api_url"], embedded_mcp["tool_handshakes_and_read_only_calls"])
check("浏览器资产路由实际加载wingbox", embedded_mcp["asset_preview_contract"]["browser_active_model"] == "wingbox" and embedded_mcp["asset_preview_contract"]["browser_canvas_count"] == 1 and (ROOT / "artifacts" / "asset-preview-route.png").is_file(), embedded_mcp["asset_preview_contract"])

try:
    urllib.request.urlopen(BASE + "/api/assets/%2e%2e%2f%2e%2e%2fsecret/file", timeout=5)
    traversal_blocked = False
except urllib.error.HTTPError as error:
    traversal_blocked = error.code in (403, 404)
check("任意路径读取被阻止", traversal_blocked, "未登记路径返回403/404")

report = {"generated_at": datetime.now(timezone.utc).isoformat(), "passed": sum(row["passed"] for row in checks), "total": len(checks), "checks": checks, "mesh_evidence": mesh_evidence}
(ROOT / "artifacts" / "test-evidence.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"passed": report["passed"], "total": report["total"], "failed": [row["name"] for row in checks if not row["passed"]]}, ensure_ascii=False))
raise SystemExit(0 if report["passed"] == report["total"] else 1)
