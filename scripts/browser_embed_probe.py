from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from websockets.sync.client import connect


ROOT = Path(__file__).resolve().parents[1]
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
CDP_PORT = 9223


def wait_json(url: str, timeout: float = 15, predicate=None):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                value = json.load(response)
                if predicate is None or predicate(value):
                    return value
        except Exception:
            time.sleep(0.25)
    raise TimeoutError(url)


def main():
    legacy_profile = (ROOT / "runtime" / "browser-embed-test").resolve()
    if legacy_profile.parent == (ROOT / "runtime").resolve() and legacy_profile.name == "browser-embed-test":
        shutil.rmtree(legacy_profile, ignore_errors=True)
    profile = Path(tempfile.mkdtemp(prefix="browser-embed-test-", dir=ROOT / "runtime"))
    target_url = os.environ.get("CAE_KB_BROWSER_PROBE_URL", "http://127.0.0.1:8765/#assistant")
    process = subprocess.Popen(
        [
            str(EDGE),
            "--headless=new",
            "--disable-gpu",
            f"--remote-debugging-port={CDP_PORT}",
            f"--user-data-dir={profile}",
            "--window-size=1600,1000",
            target_url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    (ROOT / "runtime" / "run" / "browser-test.pid").write_text(str(process.pid), encoding="ascii")
    try:
        pages = wait_json(
            f"http://127.0.0.1:{CDP_PORT}/json",
            predicate=lambda rows: any(row.get("type") == "page" and "127.0.0.1:8765" in row.get("url", "") for row in rows),
        )
        page = next(row for row in pages if row.get("type") == "page" and "127.0.0.1:8765" in row.get("url", ""))
        with connect(page["webSocketDebuggerUrl"], max_size=20_000_000) as socket:
            sequence = 0
            contexts = {}
            websocket_count = 0
            websocket_methods = set()

            def send(method, params=None):
                nonlocal sequence, websocket_count
                sequence += 1
                request_id = sequence
                socket.send(json.dumps({"id": request_id, "method": method, "params": params or {}}))
                while True:
                    message = json.loads(socket.recv())
                    if message.get("method") == "Runtime.executionContextCreated":
                        context = message["params"]["context"]
                        contexts[context["id"]] = context
                    if message.get("method") == "Network.webSocketCreated":
                        websocket_count += 1
                    if message.get("method") in {"Network.webSocketFrameSent", "Network.webSocketFrameReceived"}:
                        payload = message.get("params", {}).get("response", {}).get("payloadData", "")
                        try:
                            frame = json.loads(payload)
                            if isinstance(frame, dict) and isinstance(frame.get("method"), str):
                                websocket_methods.add(frame["method"])
                        except Exception:
                            pass
                    if message.get("id") == request_id:
                        return message

            send("Runtime.enable")
            send("Page.enable")
            send("Network.enable")
            time.sleep(12 if "#models" in target_url else 6)
            send("Runtime.evaluate", {"expression": "0"})

            if "#models" in target_url:
                model_result = None
                for context_id, context in list(contexts.items()):
                    if not context.get("auxData", {}).get("isDefault"):
                        continue
                    response = send("Runtime.evaluate", {"contextId": context_id, "expression": "JSON.stringify({href:location.href,active:document.querySelector('#modelTabs button.active')?.dataset.model||null,viewInfo:document.querySelector('#viewInfo')?.innerText||null,canvasCount:document.querySelectorAll('#view canvas').length})", "returnByValue": True})
                    value = response.get("result", {}).get("result", {}).get("value")
                    if value and "127.0.0.1:8765" in value:
                        model_result = json.loads(value)
                        break
                screenshot = send("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
                screenshot_path = ROOT / "artifacts" / "asset-preview-route.png"
                screenshot_path.write_bytes(base64.b64decode(screenshot["result"]["data"]))
                print(json.dumps({"model_route": model_result, "screenshot": str(screenshot_path)}, ensure_ascii=False))
                return

            def evaluate_in_dsh(expression, await_promise=False):
                for context_id, context in list(contexts.items()):
                    if not context.get("auxData", {}).get("isDefault"):
                        continue
                    origin_result = send("Runtime.evaluate", {"contextId": context_id, "expression": "location.origin", "returnByValue": True})
                    origin = origin_result.get("result", {}).get("result", {}).get("value")
                    if origin == "http://127.0.0.1:3088":
                        return send("Runtime.evaluate", {"contextId": context_id, "expression": expression, "returnByValue": True, "awaitPromise": await_promise})
                return None

            evaluate_in_dsh("""(()=>{const b=[...document.querySelectorAll('button')].find(x=>x.innerText.includes('继续'));if(b){b.click();return true}return false})()""")
            time.sleep(1)
            contexts.clear()
            send("Page.reload", {"ignoreCache": True})
            time.sleep(6)
            send("Runtime.evaluate", {"expression": "0"})
            created = evaluate_in_dsh("""(()=>{const b=[...document.querySelectorAll('button')].find(x=>x.innerText.includes('新建会话'));if(b){b.click();return true}return false})()""")
            time.sleep(2)
            send("Runtime.evaluate", {"expression": "0"})
            rpc_probe = evaluate_in_dsh("""(async()=>{const call=async(endpoint,args)=>{const rpcId=crypto.randomUUID();const response=await fetch('/api/'+endpoint,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({type:'client-request',rpcId,method:endpoint,payload:{args}})});const body=await response.json();if(!response.ok||body?.result?.ok!==true)throw new Error(endpoint+': '+JSON.stringify(body));return body.result.value};const roster=await call('agentPresets/list',{});const preset=await call('agentPresets/read',{agentPreset:'cae'});const inventory=await call('pluginInventory/list',{});const listed=await call('session/list',{_request:{}});let session=listed.items.find(x=>x.blank&&x.cwd==='D:\\\\zhishiku'&&x.projections?.values?.agentPreset==='cae');let sessionCreated=false;if(!session){const made=await call('session/create',{request:{cwd:'D:\\\\zhishiku',agentPreset:'cae'}});session={sessionId:made.sessionId,cwd:'D:\\\\zhishiku',blank:true,projections:{values:{agentPreset:made.agentPreset||'cae'}}};sessionCreated=true}const activeIntegrations=inventory.entries.filter(x=>['include:cae-viewer-mcp','include:mcp-cae-kb'].includes(x.entryId)).map(x=>({entryId:x.entryId,moduleName:x.moduleName,enabled:x.enabled,fiberPhase:x.fiberPhase}));return JSON.stringify({defaultPreset:roster.presets.find(x=>x.isDefault)?.id,preset:{id:preset.agentPreset,name:preset.name},activeIntegrations,session:{sessionId:session.sessionId,cwd:session.cwd,blank:session.blank,agentPreset:session.projections?.values?.agentPreset||'cae',created:sessionCreated}})})()""", await_promise=True)

            rows = []
            expression = """JSON.stringify({href:location.origin+location.pathname+location.hash,title:document.title,text:(document.body?.innerText||'').slice(0,5000),buttons:[...document.querySelectorAll('button')].map(x=>x.innerText||x.getAttribute('aria-label')||'').filter(Boolean).slice(0,40),iframes:document.querySelectorAll('iframe').length})"""
            for context_id, context in list(contexts.items()):
                if not context.get("auxData", {}).get("isDefault"):
                    continue
                response = send("Runtime.evaluate", {"contextId": context_id, "expression": expression, "returnByValue": True})
                value = response.get("result", {}).get("result", {}).get("value")
                if value:
                    rows.append(json.loads(value))
            screenshot = send("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
            screenshot_path = ROOT / "artifacts" / "dsh-embedded.png"
            screenshot_path.write_bytes(base64.b64decode(screenshot["result"]["data"]))
            created_value = created and created.get("result", {}).get("result", {}).get("value")
            rpc_value = rpc_probe and rpc_probe.get("result", {}).get("result", {}).get("value")
            rpc_error = rpc_probe and rpc_probe.get("result", {}).get("exceptionDetails", {}).get("exception", {}).get("description")
            print(json.dumps({"contexts": rows, "new_session_clicked": bool(created_value), "websocket_created": websocket_count > 0, "websocket_count": websocket_count, "websocket_methods": sorted(websocket_methods), "rpc_probe": json.loads(rpc_value) if rpc_value else None, "rpc_error": rpc_error, "screenshot": str(screenshot_path)}, ensure_ascii=False))
    finally:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
        pid_file = ROOT / "runtime" / "run" / "browser-test.pid"
        if pid_file.is_file():
            pid_file.unlink()
        resolved_profile = profile.resolve()
        if resolved_profile.parent == (ROOT / "runtime").resolve() and resolved_profile.name.startswith("browser-embed-test-"):
            shutil.rmtree(resolved_profile, ignore_errors=True)


if __name__ == "__main__":
    main()
