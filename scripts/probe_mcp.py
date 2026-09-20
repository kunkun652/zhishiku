import json, os, subprocess, sys
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

root=Path(__file__).resolve().parents[1]
server=root/'integrations'/'dsh'/'kb_mcp_server.py'
env={**os.environ,'PYTHONUTF8':'1'}
p=subprocess.Popen([sys.executable,str(server)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,encoding='utf-8',env=env)
def req(payload):
    p.stdin.write(json.dumps(payload,ensure_ascii=False)+'\n');p.stdin.flush();return json.loads(p.stdout.readline())
try:
    init=req({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-06-18','capabilities':{},'clientInfo':{'name':'acceptance-probe','version':'1'}}})
    tools=req({'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}})
    call=req({'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'kb_search','arguments':{'query':'网格'}}})
    hyphen=req({'jsonrpc':'2.0','id':4,'method':'tools/call','params':{'name':'kb_search','arguments':{'query':'DPW-W1'}}})
    filtered=req({'jsonrpc':'2.0','id':5,'method':'tools/call','params':{'name':'kb_search','arguments':{'query':'材料','type':'材料卡'}}})
    preview=req({'jsonrpc':'2.0','id':6,'method':'tools/call','params':{'name':'kb_preview_asset','arguments':{'asset_id':'mesh-wingbox'}}})
    unsupported=req({'jsonrpc':'2.0','id':7,'method':'tools/call','params':{'name':'kb_preview_asset','arguments':{'asset_id':'doc-pazy'}}})
    out={'initialize':init,'tool_count':len(tools['result']['tools']),'tool_names':[x['name'] for x in tools['result']['tools']], 'real_call':call}
    out['hyphen_call']=hyphen
    out['type_filtered_call']=filtered
    out['three_d_preview_call']=preview
    out['unsupported_preview_call']=unsupported
    (root/'artifacts'/'mcp-probe.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8-sig')
    print(json.dumps(out,ensure_ascii=False,indent=2))
finally:
    p.terminate();p.wait(timeout=5)
