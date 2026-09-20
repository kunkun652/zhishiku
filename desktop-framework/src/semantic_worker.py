"""Actual Semantica graph construction; no extraction, LLM or network calls."""
import json,sys
from importlib.metadata import version
from pathlib import Path
def main():
    from semantica.kg import GraphBuilder
    source=json.loads(Path(sys.argv[1]).read_text('utf-8'))
    payload={'entities':[{'id':n['id'],'type':n['type'],'name':n['title'],'properties':{'version':n['version'],'hash':n['hash']}} for n in source['nodes']], 'relationships':[{'id':e['id'],'source':e['source'],'target':e['target'],'type':e['type'],'properties':{'relation_id':e['id'],'evidence':e['evidence'],'source_version':e['source_version'],'target_version':e['target_version']}} for e in source['edges']]}
    graph=GraphBuilder(merge_entities=False,resolve_conflicts=False).build(payload)
    canonical={'nodes':sorted([{'id':n['id'],'type':n['type'],'title':n['name'],'version':n['properties']['version'],'hash':n['properties']['hash']} for n in graph['entities']],key=lambda n:n['id']),'edges':sorted([{'id':e['properties']['relation_id'],'source':e['source'],'target':e['target'],'type':e['type'],'evidence':e['properties']['evidence'],'source_version':e['properties']['source_version'],'target_version':e['properties']['target_version']} for e in graph['relationships']],key=lambda e:e['id'])}
    graph={'canonical':canonical,'graph':graph,'semantica_version':version('semantica')}
    Path(sys.argv[2]).write_text(json.dumps(graph,ensure_ascii=False,default=str,indent=2),encoding='utf-8')
if __name__=='__main__': main()
