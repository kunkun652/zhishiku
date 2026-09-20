from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "knowledge.db"


def snapshot():
    db = sqlite3.connect(DB)
    try:
        objects = dict(db.execute("SELECT id,version FROM objects WHERE active=1"))
        assets = dict(db.execute("SELECT id,version FROM assets"))
        return objects, assets
    finally:
        db.close()


before_objects, before_assets = snapshot()
completed = subprocess.run([sys.executable, str(ROOT / "scripts" / "import_data.py")], cwd=ROOT, capture_output=True, check=False)
after_objects, after_assets = snapshot()
evidence = {
    "checked_at": datetime.now(timezone.utc).isoformat(),
    "import_exit_code": completed.returncode,
    "active_object_count": len(after_objects),
    "asset_count": len(after_assets),
    "object_versions_stable": before_objects == after_objects,
    "asset_versions_stable": before_assets == after_assets,
    "changed_object_versions": {key: [before_objects.get(key), value] for key, value in after_objects.items() if before_objects.get(key) != value},
    "changed_asset_versions": {key: [before_assets.get(key), value] for key, value in after_assets.items() if before_assets.get(key) != value},
}
(ROOT / "artifacts" / "repeat-import-evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(evidence, ensure_ascii=False))
raise SystemExit(0 if completed.returncode == 0 and before_objects == after_objects and before_assets == after_assets else 1)
