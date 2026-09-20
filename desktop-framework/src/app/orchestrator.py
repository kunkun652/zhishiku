"""Local bounded graph recall and rank fusion; never creates engineering facts."""
import re,time
from concurrent.futures import ThreadPoolExecutor,TimeoutError
from . import semantic_search,derived_graph

POOL=ThreadPoolExecutor(max_workers=3,thread_name_prefix='recall')

def route(q,mode):
    if mode!='auto':return mode,'用户指定'
    if re.search(r'关联|用了|采用|来源|哪些报告|什么材料',q):return 'graph','关系问题，先定位实体再展开'
    if re.search(r'\b[A-Z]{2,}[- /]?\d+|\b\d{4}-[A-Z]\d|[0-9a-f]{8}-[0-9a-f-]{27,}',q,re.I):return 'keyword','编号优先精确匹配'
    return 'hybrid','描述问题，关键词与语义召回'

def graph_recall(c,items,seeds,hops=2,budget=80,edges=None,backend="authority"):
    byid={r['id']:r for r in items};adj={};found={}
    for row in (edges if edges is not None else c.execute('SELECT * FROM relations ORDER BY id')):
        e=dict(row);a=byid.get(e['source']);b=byid.get(e['target'])
        if not a or not b or not e['evidence'] or a['version']!=e['source_version'] or b['version']!=e['target_version']:continue
        for src,dst,direction in ((a,b,'outgoing'),(b,a,'incoming')):
            adj.setdefault(src['id'],[]).append((dst['id'],{**e,'direction':direction}))
    queue=[(s['id'],[],{s['id']}) for s in seeds[:3]]
    for oid,path,visited in queue:
        if len(path)>=hops:continue
        for target,edge in adj.get(oid,[])[:15]:
            if target in visited:continue
            next_path=path+[edge]
            if target not in found:
                found[target]={**byid[target],'relation_paths':[next_path],'retrieval_channels':['图谱关系'],'evidence':[],'applicability':'关联资料；工程适用性待确认','graph_backend':backend}
            elif len(found[target]['relation_paths'])<3:found[target]['relation_paths'].append(next_path)
            if len(found)>=budget:return list(found.values())
            queue.append((target,next_path,visited|{target}))
    return list(found.values())

def fuse(lexical,vectors,graph,items):
    results=semantic_search.combine(lexical,vectors,items);merged={r['id']:r for r in results}
    for rank,r in enumerate(graph,1):
        out=merged.setdefault(r['id'],{**r,'fusion_score':0,'retrieval_channels':[]})
        out['fusion_score']+=1/(60+rank);out['retrieval_channels']=list(dict.fromkeys(out['retrieval_channels']+['图谱关系']))
        out['relation_paths']=r['relation_paths'];out['graph_backend']=r['graph_backend']
    for rank,r in enumerate(lexical,1):merged[r['id']].setdefault('channel_ranks',{})['keyword']=rank
    for rank,r in enumerate(graph,1):merged[r['id']].setdefault('channel_ranks',{})['graph']=rank
    return sorted(merged.values(),key=lambda r:(-r['fusion_score'],r['id']))
