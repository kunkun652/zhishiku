"""Verify the delivered EXE and GitHub source using an isolated data space."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent / 'semantica'
OUT = ROOT / 'evidence' / ('semantica-github-' + time.strftime('%Y%m%d-%H%M%S'))
OUT.mkdir(parents=True)
EXE = ROOT / 'release/知衡仿真知识库/知衡仿真知识库.exe'
env = {**os.environ, 'ZH_DATA_ROOT': str(OUT / 'data')}
checks = []
proc = subprocess.Popen([str(EXE), '--server-only'], env=env, creationflags=subprocess.CREATE_NO_WINDOW)
try:
    runtime_file = OUT / 'data/runtime.json'
    for _ in range(120):
        if runtime_file.exists():
            break
        if proc.poll() is not None:
            raise RuntimeError('EXE exited before startup')
        time.sleep(.5)
    runtime = json.loads(runtime_file.read_text('utf-8'))
    def api(path, body=None):
        request = urllib.request.Request(runtime['url'] + path,
            data=None if body is None else json.dumps(body).encode(),
            headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.load(response)
    health = api('/api/health')
    assert Path(health['data_root']) == OUT / 'data'
    assert health['total'] == 0
    a = api('/api/objects', {'type': 'model', 'title': '集成测试模型（合成夹具）', 'data': {'source': '隔离测试'}})
    b = api('/api/objects', {'type': 'case', 'title': '集成测试案例（合成夹具）', 'data': {'source': '隔离测试'}})
    api('/api/relations', {'source': b['id'], 'target': a['id'], 'type': '使用模型', 'evidence': '合成夹具：验证关系依据保留'})
    status = api('/api/semantica/rebuild', {})
    assert status['status'] == 'passed' and status['nodes'] == 2 and status['edges'] == 1
    packaged = json.loads((OUT / 'data/graph-derived.json').read_text('utf-8'))
    checks.append('delivered EXE API invokes packaged Semantica successfully')
    source_env = {**os.environ, 'PYTHONPATH': str(REPO) + os.pathsep + str(ROOT.parent / 'runtime/semantica-packages')}
    script = "import semantica,runpy; print(semantica.__version__,semantica.__file__); runpy.run_path(" + repr(str(ROOT / 'src/semantic_worker.py')) + ",run_name='__main__')"
    result = subprocess.run([sys.executable, '-c', script, str(OUT / 'data/graph-input.json'), str(OUT / 'github-graph.json')], env=source_env, capture_output=True, timeout=120)
    (OUT / 'github-worker.log').write_bytes(result.stdout + result.stderr)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    source = json.loads((OUT / 'github-graph.json').read_text('utf-8'))
    assert source['entities'] == packaged['entities']
    assert source['relationships'] == packaged['relationships']
    checks.append('GitHub 0.7.0 source preserves identical entities and relationships through existing adapter')
    api('/api/objects', {'type': 'term', 'title': '触发派生图过期（合成夹具）', 'data': {}})
    assert api('/api/health')['semantica']['status'] == 'stale'
    assert api('/api/semantica/rebuild', {})['nodes'] == 3
    checks.append('database revision invalidates derived graph and rebuild restores it')
    report = {'status': 'passed', 'exe': str(EXE), 'exe_sha256': hashlib.sha256(EXE.read_bytes()).hexdigest(),
        'runtime': runtime, 'repository': 'https://github.com/semantica-agi/semantica',
        'commit': subprocess.check_output(['git', '-C', str(REPO), 'rev-parse', 'HEAD'], text=True).strip(),
        'packaged_status': status, 'checks': checks, 'production_data_modified': False,
        'new_source_packaged': False}
    (OUT / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
finally:
    proc.terminate()
    proc.wait(timeout=20)
