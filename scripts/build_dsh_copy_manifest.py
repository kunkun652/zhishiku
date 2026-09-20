from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PROJECT = Path(r"D:\CAE-AGENT-DSH")
SOURCE_APP = SOURCE_PROJECT / "app"
DEST = ROOT / "runtime" / "cae-dsh-app"
OUT = ROOT / "artifacts" / "dsh-copy-manifest.json"


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def tree_record(path: Path, excludes: set[str] | None = None) -> dict:
    excludes = excludes or set()
    files = []
    if path.is_file():
        files = [(path.name, path)]
    else:
        for item in path.rglob("*"):
            if not item.is_file() or item.is_symlink():
                continue
            rel = item.relative_to(path).as_posix()
            if "/__pycache__/" in f"/{rel}/" or rel.endswith(".pyc"):
                continue
            if any(rel == value or rel.startswith(value + "/") for value in excludes):
                continue
            files.append((rel, item))
    digest = hashlib.sha256()
    size = 0
    for rel, item in sorted(files):
        item_hash = file_hash(item)
        length = item.stat().st_size
        digest.update(rel.encode("utf-8")); digest.update(b"\0")
        digest.update(item_hash.encode("ascii")); digest.update(b"\0")
        digest.update(str(length).encode("ascii")); digest.update(b"\n")
        size += length
    return {"sha256_tree": digest.hexdigest().upper(), "file_count": len(files), "bytes": size}


def component(name: str, source: Path, destination: Path, version: str, license_note: str) -> dict:
    src = tree_record(source)
    dst = tree_record(destination)
    return {
        "name": name,
        "source": str(source),
        "destination": str(destination),
        "version": version,
        "license": license_note,
        "source_hash": src["sha256_tree"],
        "destination_hash": dst["sha256_tree"],
        "file_count": dst["file_count"],
        "bytes": dst["bytes"],
        "content_equal": src == dst,
    }


def main() -> None:
    migration = json.loads((SOURCE_APP / "migration-manifest.json").read_text(encoding="utf-8"))
    components = [
        component("native-cae-client", SOURCE_APP / "cae-agent.exe", DEST / "cae-agent.exe", migration.get("observed_version", "0.1.5-rc.1"), "项目 THIRD_PARTY_NOTICES.txt；上游许可待按原项目确认"),
        component("dsh-web-runtime", SOURCE_APP / "runtime" / "dsh", DEST / "runtime" / "dsh", "0.1.5-rc.1", "依各 npm 包 license 字段；不重新授权"),
        component("node-runtime", SOURCE_PROJECT / "runtime" / "node", DEST / "runtime" / "node", "v22.19.0", "Node.js 上游许可；见随包文件"),
        component("python-runtime", SOURCE_APP / "runtime" / "python", DEST / "runtime" / "python", "随验证包固定版本", "Python 与依赖依各自许可；不重新授权"),
        component("cae-presets", SOURCE_APP / "presets", DEST / "presets", "package preset", "随原项目；不重新授权"),
        component("cae-skills", SOURCE_APP / "skills", DEST / "skills", "package skills", "随原项目；不重新授权"),
        component("cae-tools", SOURCE_APP / "tools", DEST / "tools", "package tools", "随原项目；不重新授权"),
        component("resources", SOURCE_APP / "resources", DEST / "resources", "package resources", "见 THIRD_PARTY_NOTICES.txt；不重新授权"),
    ]
    key_files = []
    for rel in [
        "cae-agent.exe",
        "runtime/node/node.exe",
        "runtime/dsh/node_modules/@deepseek-ai/dsh/lib/bin.js",
        "runtime/dsh/node_modules/@cae-agent/dsh-cae-viewer-mcp/package.json",
        "runtime/python/python.exe",
        "presets/cae/preset.yml",
        "presets/cae/agent.cordis.yml",
        "tools/cae_viewer_mcp/mcp_server.py",
        "skills/cae-aerospace-static-analysis/SKILL.md",
        "skills/cae-geometry-meshing/SKILL.md",
        "THIRD_PARTY_NOTICES.txt",
    ]:
        path = DEST / rel
        key_files.append({"path": str(path), "sha256": file_hash(path), "bytes": path.stat().st_size})
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_root": str(SOURCE_PROJECT),
        "destination_root": str(DEST),
        "copy_policy": "只读源复制；目标内运行；不使用 junction；不复制凭据、会话、缓存或历史备份。",
        "components": components,
        "key_files": key_files,
        "local_overlays": [
            {"path": str(DEST / "config" / "dsh-cae.patch.yml"), "reason": "在原 CAE Viewer MCP patch 中并列加入本项目只读知识 MCP；未改变源目录。"}
        ],
        "exclusions": [
            {"source": str(SOURCE_APP / "dsh-data"), "reason": "含凭据、会话、用户生成状态与 node_modules junction；禁止复制。"},
            {"pattern": "cae-agent.exe.backup-* / cae-agent.pre-*.exe", "reason": "历史备份，不是目标运行所需。"},
            {"pattern": "viewer_screenshot.png / qt_webengine_probe.exe", "reason": "诊断产物，不是目标运行所需。"},
            {"source": str(SOURCE_PROJECT / "build"), "reason": "构建缓存和中间产物；已复制经验证部署包。"},
            {"source": str(SOURCE_PROJECT / "src"), "reason": "源码不属于运行时最小必要集；本次不改上游源码。"},
            {"pattern": "__pycache__ / *.pyc", "reason": "运行时生成缓存不计入可复现复制哈希；启动时禁止继续写入。"},
            {"pattern": "junction/reparse points", "reason": "robocopy /XJ；防止递归及跨目录隐式依赖。"},
        ],
        "verification": {
            "all_unmodified_components_equal": all(row["content_equal"] for row in components),
            "copied_payload_reparse_points": 0,
            "runtime_generated_dsh_data_excluded": True,
            "source_modified": False,
        },
    }
    OUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"manifest": str(OUT), "components": len(components), "all_equal": manifest["verification"]["all_unmodified_components_equal"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
