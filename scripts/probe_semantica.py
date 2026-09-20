import json, sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'runtime'/'semantica-packages'))
result={'adapter':'Semantica probe','status':'failed'}
try:
    import semantica
    result.update({'version':getattr(semantica,'__version__','unknown'),'import':True})
    # Use the installed package itself, without a remote LLM, to verify a real local graph path.
    from semantica.kg import GraphBuilder
    builder=GraphBuilder(merge_entities=True)
    graph=builder.build({'entities':[{'id':'case-fe-plate','type':'Case','name':'pyNastran plate'},{'id':'result-plate','type':'ResultAsset','name':'plate.op2'}], 'relationships':[{'source':'case-fe-plate','target':'result-plate','type':'produces_result'}]})
    result.update({'status':'passed','graph_type':type(graph).__name__,'note':'使用本地模式实体/关系运行 GraphBuilder；生产图谱仍以 SQLite 来源边为权威派生。'})
except Exception as exc:
    result.update({'error':f'{type(exc).__name__}: {exc}'})
(root/'artifacts').mkdir(exist_ok=True)
(root/'artifacts'/'semantica-probe.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
raise SystemExit(0 if result['status']=='passed' else 1)
