from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = Path(r"D:\知识库")
DB = ROOT / "data" / "knowledge.db"
ASSET_STORE = ROOT / "data" / "assets"
SAMPLES = ROOT / "data" / "samples"
ARTIFACTS = ROOT / "artifacts"
PY_DEPS = ROOT / "runtime" / "python-packages"
sys.path.insert(0, str(PY_DEPS))

SOURCES = {
    "cad-dpw-w1": SOURCE_ROOT / r"原始资料\公开数据集收集\DLR_F6\DPW-W1.stp",
    "mesh-plate": SOURCE_ROOT / r"原始资料\公开数据集收集\GitHub_pyNastran\_已解压\pyNastran-main\pyNastran-main\models\plate\plate.bdf",
    "result-plate": SOURCE_ROOT / r"原始资料\公开数据集收集\GitHub_pyNastran\_已解压\pyNastran-main\pyNastran-main\models\plate\plate.op2",
    "doc-pazy": SOURCE_ROOT / r"知识库\03_网格\实体资产\Pazy-S10\Readme_Raw_Data.pdf",
    "card-term": SOURCE_ROOT / r"知识库\01_术语语义参数\术语卡.csv",
    "card-mesh": SOURCE_ROOT / r"知识库\03_网格\网格策略卡.csv",
    "card-material": SOURCE_ROOT / r"知识库\04_材料\材料卡.csv",
    "card-condition": SOURCE_ROOT / r"知识库\05_载荷与工况\工况卡.csv",
    "mesh-wingbox": Path(r"D:\wingbox.bdf"),
    "mesh-framedeck": Path(r"D:\framedeck.bdf"),
    "cad-frame-step": Path(r"D:\demo3\frame.STEP"),
}

DUPLICATE_REFERENCES = {r"D:\wingbox_stitched_together-000.bdf": "mesh-wingbox"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest().upper()


def json_hash(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest().upper()


def stable_id(prefix: str, text: str) -> str:
    return f"{prefix}-{hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]}"


def ensure_column(db: sqlite3.Connection, table: str, name: str, declaration: str) -> None:
    columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
    if name not in columns:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")


def connect() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS assets(
          id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL,
          source_path TEXT NOT NULL, local_path TEXT, sha256 TEXT NOT NULL,
          size INTEGER NOT NULL, status TEXT NOT NULL, license_note TEXT,
          metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS objects(
          id TEXT PRIMARY KEY, type TEXT NOT NULL, title TEXT NOT NULL,
          version TEXT NOT NULL, status TEXT NOT NULL, source_asset_id TEXT,
          locator TEXT, body TEXT NOT NULL, data_json TEXT NOT NULL,
          FOREIGN KEY(source_asset_id) REFERENCES assets(id)
        );
        CREATE TABLE IF NOT EXISTS edges(
          id TEXT PRIMARY KEY, source_id TEXT NOT NULL, target_id TEXT NOT NULL,
          relation TEXT NOT NULL, method TEXT NOT NULL, evidence TEXT NOT NULL,
          status TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(
          object_id UNINDEXED, title, body, tokenize='unicode61'
        );
        CREATE TABLE IF NOT EXISTS imports(
          run_id TEXT PRIMARY KEY, started_at TEXT, finished_at TEXT,
          source_count INTEGER, unique_assets INTEGER, parsed_objects INTEGER,
          failures_json TEXT
        );
        CREATE TABLE IF NOT EXISTS asset_versions(
          asset_id TEXT NOT NULL, version INTEGER NOT NULL, kind TEXT NOT NULL,
          name TEXT NOT NULL, source_path TEXT NOT NULL, local_path TEXT NOT NULL,
          sha256 TEXT NOT NULL, size INTEGER NOT NULL, status TEXT NOT NULL,
          license_note TEXT, metadata_json TEXT NOT NULL, imported_at TEXT NOT NULL,
          PRIMARY KEY(asset_id, version), UNIQUE(asset_id, sha256)
        );
        CREATE TABLE IF NOT EXISTS object_versions(
          object_id TEXT NOT NULL, version INTEGER NOT NULL, type TEXT NOT NULL,
          title TEXT NOT NULL, status TEXT NOT NULL, source_asset_id TEXT,
          locator TEXT, body TEXT NOT NULL, data_json TEXT NOT NULL,
          content_hash TEXT NOT NULL, created_at TEXT NOT NULL,
          PRIMARY KEY(object_id, version), UNIQUE(object_id, content_hash)
        );
        """
    )
    ensure_column(db, "assets", "version", "INTEGER NOT NULL DEFAULT 1")
    ensure_column(db, "assets", "imported_at", "TEXT")
    ensure_column(db, "objects", "content_hash", "TEXT")
    ensure_column(db, "objects", "updated_at", "TEXT")
    ensure_column(db, "objects", "active", "INTEGER NOT NULL DEFAULT 1")
    now = utc_now()
    for row in db.execute("SELECT * FROM assets").fetchall():
        db.execute(
            "INSERT OR IGNORE INTO asset_versions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (row["id"], int(row["version"] or 1), row["kind"], row["name"], row["source_path"], row["local_path"], row["sha256"], row["size"], row["status"], row["license_note"], row["metadata_json"], row["imported_at"] or now),
        )
    for row in db.execute("SELECT * FROM objects").fetchall():
        payload = {key: row[key] for key in ("type", "title", "status", "source_asset_id", "locator", "body", "data_json")}
        digest = row["content_hash"] or json_hash(payload)
        db.execute("UPDATE objects SET content_hash=?,updated_at=COALESCE(updated_at,?) WHERE id=?", (digest, now, row["id"]))
        db.execute(
            "INSERT OR IGNORE INTO object_versions VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (row["id"], int(row["version"] or 1), row["type"], row["title"], row["status"], row["source_asset_id"], row["locator"], row["body"], row["data_json"], digest, row["updated_at"] or now),
        )
    db.commit()
    return db


def read_csv_rows(path: Path):
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "gb18030", "utf-8"):
        try:
            return list(csv.DictReader(raw.decode(encoding).splitlines())), encoding
        except UnicodeDecodeError:
            pass
    raise UnicodeError(f"cannot decode {path}")


def first_value(row: dict, candidates: tuple[str, ...], fallback: str) -> str:
    for key in candidates:
        if row.get(key, "").strip():
            return row[key].strip()
    return next((str(value).strip() for value in row.values() if value and str(value).strip()), fallback)


def compact_float(value: float) -> float:
    return float(f"{float(value):.8g}")


def parse_bdf(path: Path) -> dict:
    """Use pyNastran for BDF syntax/coordinates and emit solid boundary faces only."""
    from pyNastran.bdf.bdf import BDF

    model = BDF(debug=False, log=None)
    model.read_bdf(str(path), xref=False, punch=False, read_includes=False)
    card_counts = {str(key): int(value) for key, value in model.card_count.items()}
    shell_faces: list[tuple[list[int], int]] = []
    line_elements: list[tuple[list[int], int]] = []
    solid_boundary: dict[tuple[int, ...], tuple[list[int], int]] = {}
    unsupported = Counter()
    solid_patterns = {
        "CTETRA": ((0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3)),
        "CPENTA": ((0, 2, 1), (3, 4, 5), (0, 1, 4, 3), (1, 2, 5, 4), (2, 0, 3, 5)),
        "CHEXA": ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)),
        "CPYRAM": ((0, 3, 2, 1), (0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)),
    }
    for eid, element in model.elements.items():
        etype = element.type
        ids = [int(value) for value in element.node_ids if value is not None]
        if etype == "CTRIA3" and len(ids) >= 3:
            shell_faces.append((ids[:3], int(eid)))
        elif etype == "CQUAD4" and len(ids) >= 4:
            shell_faces.append((ids[:4], int(eid)))
        elif etype in {"CBAR", "CBEAM", "CROD", "CONROD", "CBUSH"} and len(ids) >= 2:
            line_elements.append((ids[:2], int(eid)))
        elif etype in solid_patterns:
            for pattern in solid_patterns[etype]:
                if max(pattern) >= len(ids):
                    continue
                face = [ids[index] for index in pattern]
                key = tuple(sorted(face))
                if key in solid_boundary:
                    del solid_boundary[key]
                else:
                    solid_boundary[key] = (face, int(eid))
        else:
            unsupported[etype] += 1
    faces = shell_faces + list(solid_boundary.values())
    used_ids = {nid for face, _ in faces for nid in face}
    used_ids.update(nid for line, _ in line_elements for nid in line)
    render_node_ids = sorted(nid for nid in used_ids if nid in model.nodes)
    index = {nid: i for i, nid in enumerate(render_node_ids)}
    positions: list[float] = []
    for nid in render_node_ids:
        positions.extend(compact_float(value) for value in model.nodes[nid].get_position_no_xref(model))
    triangle_indices: list[int] = []
    surface_element_ids: list[int] = []
    for face, eid in faces:
        ids = [index[nid] for nid in face if nid in index]
        if len(ids) == 3:
            triangle_indices.extend(ids); surface_element_ids.append(eid)
        elif len(ids) == 4:
            triangle_indices.extend((ids[0], ids[1], ids[2], ids[0], ids[2], ids[3])); surface_element_ids.extend((eid, eid))
    line_indices: list[int] = []
    line_element_ids: list[int] = []
    for line, eid in line_elements:
        if all(nid in index for nid in line):
            line_indices.extend((index[line[0]], index[line[1]])); line_element_ids.append(eid)
    gaps = []
    if unsupported:
        gaps.append("未显示的单元类型: " + ", ".join(f"{key}={value}" for key, value in sorted(unsupported.items())))
    return {
        "source": path.name, "parser": "pyNastran 1.4.1",
        "coordinate_handling": "GRID.get_position_no_xref(model)，输出基础坐标系位置",
        "surface_method": "壳单元原始面；实体单元仅保留按节点拓扑仅出现一次的外表面",
        "node_ids": render_node_ids, "positions": positions, "triangle_indices": triangle_indices,
        "surface_element_ids": surface_element_ids, "line_indices": line_indices, "line_element_ids": line_element_ids,
        "node_count": len(model.nodes), "element_count": len(model.elements), "render_node_count": len(render_node_ids),
        "boundary_face_count": len(faces), "render_triangle_count": len(triangle_indices) // 3,
        "render_line_count": len(line_indices) // 2, "card_counts": card_counts, "gaps": gaps,
    }


def parse_op2(path: Path, node_ids: list[int]) -> dict:
    from pyNastran.op2.op2 import OP2

    op2 = OP2(debug=False, log=None)
    op2.read_op2(str(path), combine=True, build_dataframe=False, skip_undefined_matrices=True)
    result = {"source": path.name, "variable": "位移模", "component": "|Txyz|", "unit": "未知（源文件未声明）", "subcase": None, "values": [], "node_ids": node_ids}
    if not op2.displacements:
        result["gap"] = "OP2 中未发现位移结果表"; return result
    subcase = sorted(op2.displacements)[0]
    table = op2.displacements[subcase]
    data = table.data[0, :, :3]
    ids = [int(value) for value in table.node_gridtype[:, 0]]
    mags = (data[:, 0] ** 2 + data[:, 1] ** 2 + data[:, 2] ** 2) ** 0.5
    lookup = {nid: float(value) for nid, value in zip(ids, mags)}
    values = [lookup.get(nid) for nid in node_ids]
    finite = [value for value in values if value is not None]
    result.update({"subcase": int(subcase), "values": values, "min": min(finite) if finite else None, "max": max(finite) if finite else None})
    return result


def inventory() -> dict:
    counts, categories, rows = Counter(), Counter(), []
    stack = [SOURCE_ROOT]
    while stack:
        current = stack.pop()
        try:
            for entry in os.scandir(current):
                try:
                    if entry.is_symlink(): categories["reparse_or_symlink_excluded"] += 1
                    elif entry.is_dir(follow_symlinks=False): stack.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        stat = entry.stat(follow_symlinks=False)
                        ext = Path(entry.name).suffix.lower() or "[no-extension]"
                        counts[ext] += 1
                        top = Path(entry.path).relative_to(SOURCE_ROOT).parts[0]
                        categories[top] += 1; rows.append((entry.path, stat.st_size, ext, top))
                except OSError: categories["unreadable_entries"] += 1
        except OSError: categories["unreadable_directories"] += 1
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    with (ARTIFACTS / "source-inventory.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle); writer.writerow(["path", "size", "extension", "scope"]); writer.writerows(rows)
    return {"scanned_files": len(rows), "by_extension": dict(counts.most_common()), "by_scope": dict(categories), "policy": "只读盘点；不跟随重解析点；只复制明确登记的演示源。"}


def upsert_asset(db: sqlite3.Connection, aid: str, src: Path, metadata: dict) -> dict:
    digest = sha256(src)
    current = db.execute("SELECT * FROM assets WHERE id=?", (aid,)).fetchone()
    version = int(current["version"] or 1) if current else 1
    if current and current["sha256"] != digest: version += 1
    target_dir = ASSET_STORE / aid; target_dir.mkdir(parents=True, exist_ok=True)
    local = target_dir / f"v{version}-{digest[:12]}-{src.name}"
    if not local.is_file() or sha256(local) != digest: shutil.copy2(src, local)
    if sha256(local) != digest: raise RuntimeError(f"copy hash mismatch: {src}")
    kind = "card_source" if aid.startswith("card-") else ("document" if src.suffix.lower() == ".pdf" else "engineering_asset")
    status = "本地整理数据" if aid.startswith("card-") else ("用户本地演示源" if aid in {"mesh-wingbox", "mesh-framedeck", "cad-frame-step"} else "公开样本")
    license_note = "来源与许可范围待按原件确认；本演示不重授权"
    imported = utc_now(); meta_json = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
    values = (aid, kind, src.name, str(src), str(local), digest, src.stat().st_size, status, license_note, meta_json, version, imported)
    db.execute("INSERT INTO assets(id,kind,name,source_path,local_path,sha256,size,status,license_note,metadata_json,version,imported_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET kind=excluded.kind,name=excluded.name,source_path=excluded.source_path,local_path=excluded.local_path,sha256=excluded.sha256,size=excluded.size,status=excluded.status,license_note=excluded.license_note,metadata_json=excluded.metadata_json,version=excluded.version,imported_at=excluded.imported_at", values)
    db.execute("INSERT OR IGNORE INTO asset_versions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (aid, version, kind, src.name, str(src), str(local), digest, src.stat().st_size, status, license_note, meta_json, imported))
    return {"id": aid, "version": version, "sha256": digest, "local_path": str(local)}


def upsert_object(db: sqlite3.Connection, oid: str, typ: str, title: str, source: str | None, locator: str, body: str, data: dict, status: str = "已解析") -> int:
    data_json = json.dumps(data, ensure_ascii=False, sort_keys=True)
    digest = json_hash({"type": typ, "title": title, "status": status, "source_asset_id": source, "locator": locator, "body": body, "data_json": data_json})
    current = db.execute("SELECT version,content_hash FROM objects WHERE id=?", (oid,)).fetchone()
    version = int(current["version"] or 1) if current else 1
    if current and current["content_hash"] != digest: version += 1
    updated = utc_now(); values = (oid, typ, title, str(version), status, source, locator, body, data_json, digest, updated, 1)
    db.execute("INSERT INTO objects(id,type,title,version,status,source_asset_id,locator,body,data_json,content_hash,updated_at,active) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET type=excluded.type,title=excluded.title,version=excluded.version,status=excluded.status,source_asset_id=excluded.source_asset_id,locator=excluded.locator,body=excluded.body,data_json=excluded.data_json,content_hash=excluded.content_hash,updated_at=excluded.updated_at,active=1", values)
    db.execute("INSERT OR IGNORE INTO object_versions VALUES(?,?,?,?,?,?,?,?,?,?,?)", (oid, version, typ, title, status, source, locator, body, data_json, digest, updated))
    return version


def main() -> None:
    missing = [str(path) for path in SOURCES.values() if not path.is_file()]
    if missing: raise SystemExit("Missing inputs:\n" + "\n".join(missing))
    started, failures = utc_now(), []
    inv = inventory(); SAMPLES.mkdir(parents=True, exist_ok=True); ASSET_STORE.mkdir(parents=True, exist_ok=True)
    db = connect(); asset_records = {}
    placeholders = ",".join("?" for _ in SOURCES)
    db.execute(f"UPDATE objects SET active=0 WHERE source_asset_id IN ({placeholders})", tuple(SOURCES))
    for aid, src in SOURCES.items():
        scope = src.relative_to(SOURCE_ROOT).parts[0] if SOURCE_ROOT in src.parents else "用户明确指定的 D 盘演示源"
        metadata = {"source_scope": scope, "copied_for_demo": True}
        if aid == "mesh-wingbox":
            duplicate = Path(next(iter(DUPLICATE_REFERENCES)))
            metadata["duplicate_reference"] = {"path": str(duplicate), "same_sha256": duplicate.is_file() and sha256(duplicate) == sha256(src), "imported": False}
        asset_records[aid] = upsert_asset(db, aid, src, metadata)

    meshes = {}
    for name, aid in (("plate", "mesh-plate"), ("wingbox", "mesh-wingbox"), ("framedeck", "mesh-framedeck")):
        try:
            mesh = parse_bdf(Path(asset_records[aid]["local_path"]))
            mesh.update({"asset_id": aid, "asset_version": asset_records[aid]["version"], "source_sha256": asset_records[aid]["sha256"]})
            (SAMPLES / f"{name}.mesh.json").write_text(json.dumps(mesh, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            meshes[name] = mesh
        except Exception as exc: failures.append({"asset": aid, "stage": "bdf", "error": f"{type(exc).__name__}: {exc}"})

    plate_mesh = meshes.get("plate", {"node_ids": [], "node_count": 0, "element_count": 0})
    try: result = parse_op2(Path(asset_records["result-plate"]["local_path"]), plate_mesh["node_ids"])
    except Exception as exc:
        result = {"source": "plate.op2", "variable": "待解析", "unit": "未知", "values": [], "gap": f"{type(exc).__name__}: {exc}"}
        failures.append({"asset": "result-plate", "stage": "op2", "error": result["gap"]})
    (SAMPLES / "plate.result.json").write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    upsert_object(db, "case-cad-dpw", "Case", "DPW-W1 公开 CAD 浏览样本", "cad-dpw-w1", "STEP 全文件", "公开 DPW-W1 几何样本，仅验证浏览器端 OpenCascade WASM 读取与 Three.js 显示；它不是可执行仿真案例。", {"case_kind": "CAD 浏览", "asset_ids": ["cad-dpw-w1"], "execution_readiness": {"ready": False, "gaps": ["仅有几何浏览资产", "未绑定分析模型、材料、载荷/边界、单位、求解器与结果"]}})
    upsert_object(db, "case-cad-frame", "Case", "用户本地 frame STEP 浏览样本", "cad-frame-step", "frame.STEP 全文件", "用户明确指定的本地 STEP，仅用于验证只读复制、版本哈希、浏览器端 OpenCascade WASM 读取与 Three.js 交互。文件名与 framedeck.bdf 近似不能证明二者相关。", {"case_kind": "CAD 浏览", "asset_ids": ["cad-frame-step"], "possible_relation": {"target": "case-fe-framedeck", "status": "待确认", "reason": "仅 frame/framedeck 文件名近似；无共同来源、几何映射、版本或人工确认依据"}, "execution_readiness": {"ready": False, "gaps": ["仅有几何浏览资产", "与 framedeck.bdf 的关系待确认", "未绑定分析模型、材料、载荷/边界、单位、求解器与结果"]}})
    upsert_object(db, "case-fe-plate", "Case", "pyNastran plate 有限元与结果样本", "mesh-plate", "plate.bdf + plate.op2", f"公开 pyNastran plate 样本，BDF 解析得到 {plate_mesh['node_count']} 节点、{plate_mesh['element_count']} 单元；OP2 位移场可视化。材料/工况工程适用性及单位未确认。", {"case_kind": "有限元+结果", "asset_ids": ["mesh-plate", "result-plate"], "mesh": {"nodes": plate_mesh["node_count"], "elements": plate_mesh["element_count"]}, "result": {key: result.get(key) for key in ("variable", "component", "unit", "subcase", "min", "max", "gap")}, "execution_readiness": {"ready": False, "gaps": ["材料卡与工况卡未与该案例建立经审核的适用性绑定", "单位未知", "缺少受控求解配置与验证门"]}})
    for name, title in (("wingbox", "用户本地 wingbox 有限元演示模型"), ("framedeck", "用户本地 framedeck 有限元演示模型")):
        mesh = meshes.get(name)
        if not mesh: continue
        aid = f"mesh-{name}"
        body = f"用户明确指定的本地 BDF；pyNastran 解析得到 {mesh['node_count']} 节点、{mesh['element_count']} 单元、{mesh['boundary_face_count']} 个渲染外表面。源单位和求解结果未知。"
        upsert_object(db, f"case-fe-{name}", "Case", title, aid, f"{Path(SOURCES[aid]).name} 全文件", body, {"case_kind": "有限元网格演示", "asset_ids": [aid], "mesh": {key: mesh[key] for key in ("node_count", "element_count", "render_node_count", "boundary_face_count", "render_triangle_count", "render_line_count", "card_counts", "gaps")}, "unit": "未知（源文件未确认）", "result": {"available": False, "gap": "未提供或登记求解结果文件"}, "execution_readiness": {"ready": False, "gaps": ["材料/属性工程适用性待确认", "载荷与约束含义待确认", "单位待确认", "无受控求解配置", "无求解结果与独立验证"]}})

    try:
        from pypdf import PdfReader
        pdf = PdfReader(asset_records["doc-pazy"]["local_path"])
        for index, page in enumerate(pdf.pages):
            text = (page.extract_text() or "").strip()
            if text: upsert_object(db, f"doc-pazy-p{index + 1}", "SourceSpan", f"Pazy 原始数据说明 · 第 {index + 1} 页", "doc-pazy", f"page={index + 1}", text, {"page": index + 1, "asset_open_fragment": f"#page={index + 1}"})
            else: failures.append({"asset": "doc-pazy", "stage": "pdf", "page": index + 1, "error": "无可提取文本，待 OCR"})
    except Exception as exc: failures.append({"asset": "doc-pazy", "stage": "pdf", "error": f"{type(exc).__name__}: {exc}"})

    card_map = {"card-term": "术语卡", "card-mesh": "网格策略卡", "card-material": "材料卡", "card-condition": "工况卡"}
    for source_id, card_type in card_map.items():
        try:
            rows, encoding = read_csv_rows(SOURCES[source_id])
            for index, row in enumerate(rows):
                clean = {str(key).strip(): ("" if value is None else str(value).strip()) for key, value in row.items()}
                title = first_value(clean, ("名称", "术语", "卡片名称", "材料名称", "工况名称", "name", "title"), f"{card_type} {index + 1}")
                oid = stable_id("card", f"{source_id}:row:{index + 2}")
                body = "；".join(f"{key}: {value}" for key, value in clean.items() if value)
                upsert_object(db, oid, card_type, title, source_id, f"row={index + 2};encoding={encoding}", body, {"card_type": card_type, "fields": clean, "complete_record": True}, "现有卡片记录（未代替人工工程复核）")
        except Exception as exc: failures.append({"asset": source_id, "stage": "card_csv", "error": f"{type(exc).__name__}: {exc}"})

    edges = [
        ("edge-cad-case", "case-cad-dpw", "cad-dpw-w1", "使用模型", "人工清单", "案例 data.asset_ids 登记；仅浏览用途", "已登记"),
        ("edge-fe-input", "case-fe-plate", "mesh-plate", "生成输入", "同源公开样本清单", "plate.bdf 与案例对象绑定", "已登记"),
        ("edge-fe-result", "case-fe-plate", "result-plate", "产生结果", "同目录同基名且经解析", "plate.bdf / plate.op2；保存 subcase 与变量", "已解析"),
        ("edge-wingbox-input", "case-fe-wingbox", "mesh-wingbox", "使用网格", "用户明确指定", "只读复制并锁定 SHA-256；无结果文件", "已登记"),
        ("edge-framedeck-input", "case-fe-framedeck", "mesh-framedeck", "使用网格", "用户明确指定", "只读复制并锁定 SHA-256；无结果文件", "已登记"),
        ("edge-frame-cad", "case-cad-frame", "cad-frame-step", "使用模型", "用户明确指定", "只读复制并锁定 SHA-256；仅浏览用途", "已登记"),
        ("edge-frame-framedeck-candidate", "case-cad-frame", "case-fe-framedeck", "可能相关", "文件名线索", "frame/framedeck 名称近似；无共同来源、几何映射、版本或人工确认依据", "待确认"),
    ]
    db.executemany("INSERT OR REPLACE INTO edges VALUES(?,?,?,?,?,?,?)", edges)
    for source_id in card_map:
        for row in db.execute("SELECT id FROM objects WHERE source_asset_id=? AND active=1", (source_id,)):
            eid = stable_id("edge", f"{row['id']}:{source_id}")
            db.execute("INSERT OR REPLACE INTO edges VALUES(?,?,?,?,?,?,?)", (eid, row["id"], source_id, "来源于", "CSV 行解析", "对象 locator 保存原 CSV 行号", "已解析"))

    db.execute("DELETE FROM search_fts")
    db.execute("INSERT INTO search_fts(object_id,title,body) SELECT id,title,body FROM objects WHERE active=1")
    counts = dict(db.execute("SELECT type,count(*) FROM objects WHERE active=1 GROUP BY type").fetchall()); total_objects = sum(counts.values())
    db.execute("INSERT INTO imports VALUES(?,?,?,?,?,?,?)", (stable_id("import", started), started, utc_now(), inv["scanned_files"], len(SOURCES), total_objects, json.dumps(failures, ensure_ascii=False)))
    db.commit()
    source_digests = {aid: record["sha256"] for aid, record in asset_records.items()}
    duplicates = [{"path": path, "canonical_asset_id": aid, "same_sha256": Path(path).is_file() and sha256(Path(path)) == source_digests[aid], "imported": False} for path, aid in DUPLICATE_REFERENCES.items()]
    report = {"generated_at": utc_now(), "read_only_source": str(SOURCE_ROOT), "inventory": inv, "selected_source_references": len(SOURCES), "unique_selected_assets": len(set(source_digests.values())), "duplicate_references": duplicates, "parsed_objects": total_objects, "object_types": counts, "asset_versions": {aid: record["version"] for aid, record in asset_records.items()}, "failures": failures, "scope_statement": "D:\\知识库仅完成只读全量路径盘点；结构化导入仍限明确登记样本。Semantica 仅有独立 GraphBuilder 探针，不是本数据库导入执行引擎。", "exclusions": ["未移动、重命名、删除或写入源文件", "未跟随重解析点", "未对全库逐文件计算内容哈希", "wingbox 重复路径经 SHA-256 确认为同一内容，仅导入权威路径一次", "本地 BDF 未附求解结果，未伪造结果、单位或工程适用性"]}
    (ARTIFACTS / "data-cleaning-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"database": str(DB), "objects": total_objects, "types": counts, "assets": len(SOURCES), "failures": len(failures)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
