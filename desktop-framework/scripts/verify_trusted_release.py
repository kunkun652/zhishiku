"""Read-only release receipts; never bypass app authentication or send KB text."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
from contextlib import closing
import urllib.request
from urllib.error import HTTPError

root=Path(__file__).resolve().parents[1]
formal=root/'release/知衡仿真知识库'
parser=argparse.ArgumentParser();parser.add_argument('--preflight',action='store_true');args=parser.parse_args()
with closing(sqlite3.connect((formal/'data/knowledge.sqlite3').as_uri()+'?mode=ro',uri=True)) as c:
    running=c.execute("SELECT count(*) FROM kp_jobs WHERE status IN ('running','queued')").fetchone()[0]
    pending=c.execute("SELECT count(*) FROM kp_index_requests WHERE status IN ('pending','waiting_vectors')").fetchone()[0]
    counts=dict(c.execute('SELECT type,count(*) FROM objects GROUP BY type'))
if args.preflight:
    assert running==0 and pending==0,'Pending jobs: defer restart'
    print('Idle release verified: no running/queued jobs or pending index requests')
    raise SystemExit(0)
before=json.loads((root/'backups/pre-trusted-20260921/preservation.json').read_text('utf-8'))
after=json.loads((root/'evidence/trusted-after-release/preservation.json').read_text('utf-8'))
preserved={k:before[k]==after[k] for k in ('tables','files','assets')}
assert all(preserved.values()),preserved
runtime=json.loads((formal/'data/runtime.json').read_text('utf-8'))
assert runtime['exe']==str(formal/'知衡仿真知识库.exe')
assert runtime['url'].startswith('http://127.0.0.1:')
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
with opener.open(runtime['url']+'/api/ping',timeout=15) as response:ping=json.load(response)
try:
    opener.open(runtime['url']+'/api/library/files',timeout=15)
    raise AssertionError('Anonymous library access succeeded')
except HTTPError as error:
    assert error.code==401
candidate=root/'release-candidate-reader-20260921/知衡仿真知识库'
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
paths=['知衡仿真知识库.exe']+['_internal/static/'+p for p in ('reader.js','workbench.js','app.js','outline-theme.css','index.html')]
bundle={p:sha(formal/p) for p in paths}
assert all(bundle[p]==sha(candidate/p) for p in paths)
receipt={'runtime':runtime,'ping':ping,'anonymous_library_status':401,'business_counts':counts,
         'preservation':preserved,'preservation_scope':'Business-table row hashes; old/new vector and graph file SHA256; asset path/size/mtime inventory (not per-file rehash).',
         'bundle_sha256':bundle,'source_tests':88,'generation_and_token_tests':3,
         'real_answer_provider_tested':False,'engineering_approval':False}
(root/'evidence/trusted-release-acceptance.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),'utf-8')
print(json.dumps(receipt,ensure_ascii=False,indent=2))
