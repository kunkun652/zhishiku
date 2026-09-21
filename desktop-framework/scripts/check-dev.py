"""Source distribution preflight. Uses temporary data, never the real library."""
from pathlib import Path
import importlib
import os
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/static"


def check_assets():
    required = [
        "vendor/three/three.module.min.js", "vendor/three/three.core.min.js",
        "vendor/three/OrbitControls.js", "vendor/d3/d3.min.js",
        "vendor/occt/occt-import-js.js", "vendor/occt/occt-import-js.wasm",
        "vendor/occt/occt-import-js-worker.js",
    ]
    # Follow relative and /static module imports without opening a browser.
    for path in STATIC.rglob("*"):
        if path.suffix not in {".js", ".html"} or "vendor" in path.parts:
            continue
        source = path.read_text("utf-8")
        for spec in re.findall(r'''(?:from\s*|import\s*|importScripts\(\s*)['"]([^'"]+)['"]''', source):
            if spec.startswith("/static/"):
                required.append(spec.removeprefix("/static/"))
            elif spec.startswith("."):
                target = (path.parent / spec).resolve()
                assert target.is_file(), f"Missing module: {target}"
    for name in required:
        path = STATIC / name
        assert path.is_file() and path.stat().st_size, f"Missing asset: {name}; rerun setup-dev.ps1"
    assert (STATIC / "vendor/occt/occt-import-js.wasm").read_bytes()[:4] == b"\0asm"


def main():
    assert sys.platform == "win32", "This desktop setup targets Windows."
    for name in ("fastapi", "uvicorn", "webview", "multipart", "httpx", "pypdf", "fitz", "pyNastran", "meshio", "numpy"):
        importlib.import_module(name)
    check_assets()
    # Ignore inherited worker settings in the isolated test process.
    for name in ("ZH_EMBEDDING_PYTHON", "ZH_EMBEDDING_MODEL", "ZH_PIPELINE_PYTHON", "ZH_PIPELINE_MODEL"):
        os.environ.pop(name, None)
    with tempfile.TemporaryDirectory(prefix="zhiheng-dev-check-") as data:
        os.environ["ZH_DATA_ROOT"] = data
        sys.path.insert(0, str(ROOT / "src"))
        from app.service import app
        from fastapi.testclient import TestClient
        with TestClient(app) as client:
            assert client.get("/api/ping").status_code == 200
            assert client.get("/api/health").status_code == 401
            assert client.post("/api/session", json={"token": app.state.access.bootstrap}).status_code == 200
            assert client.get("/api/health").status_code == 200
            assert client.get("/").status_code == 200
            for resource in ("app.js", "vendor/three/three.module.min.js", "vendor/occt/occt-import-js.wasm"):
                assert client.get("/static/" + resource).status_code == 200
            assert client.get("/api/search?q=developer-smoke").status_code == 200
        # SQLite connections are closed by the app; the directory can be removed.
    print("PASS: imports, local assets, isolated empty library, authentication and HTTP routes.")
    print("WebView2 native window and optional AI workers require separate runtime verification.")


if __name__ == "__main__":
    main()
