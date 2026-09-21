"""Opt-in native WebView2 smoke test; never uses the operator's knowledge data.

Run with the source desktop .venv. Requires an interactive Windows session.
The hidden window uses the real desktop entry point and closes after checking JS.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import time

import webview

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
result = {}
create_window = webview.create_window
start = webview.start


def create(*args, **kwargs):
    kwargs["hidden"] = True
    return create_window(*args, **kwargs)


def inspect_window():
    window = webview.windows[0]
    try:
        for _ in range(120):
            state = window.evaluate_js("JSON.stringify({nav:document.querySelectorAll('nav [data-go]').length,text:document.body.innerText})")
            state = json.loads(state)
            if state["nav"] == 10 and "只检索" in state["text"]:
                break
            time.sleep(0.25)
        else:
            raise AssertionError("Workbench did not finish loading")
        window.evaluate_js("document.querySelector('nav [data-go=search]').click()")
        for _ in range(80):
            text = window.evaluate_js("document.querySelector('#page').innerText")
            if "原始资料" in text:
                result.update(passed=True, navigation=state["nav"], library_loaded=True)
                break
            time.sleep(0.25)
        else:
            raise AssertionError("Library did not finish loading")
    except Exception as exc:
        result.update(passed=False, error=str(exc))
    finally:
        window.destroy()


def start_checked(*args, **kwargs):
    return start(inspect_window, gui="edgechromium")


if __name__ == "__main__":
    saved_stdout, saved_stderr = sys.stdout, sys.stderr
    for key in ("ZH_EMBEDDING_PYTHON", "ZH_EMBEDDING_MODEL", "ZH_PIPELINE_PYTHON", "ZH_PIPELINE_MODEL"):
        os.environ.pop(key, None)
    with tempfile.TemporaryDirectory(prefix="zhiheng-window-smoke-") as data:
        os.environ["ZH_DATA_ROOT"] = data
        webview.create_window, webview.start = create, start_checked
        try:
            from desktop import main
            main()
        finally:
            log = sys.stdout
            sys.stdout, sys.stderr = saved_stdout, saved_stderr
            if log is not saved_stdout:
                log.close()
            webview.create_window, webview.start = create_window, start
        print(json.dumps(result, ensure_ascii=False))
        if not result.get("passed"):
            print(Path(data, "desktop.log").read_text("utf-8"))
            raise SystemExit(1)
