"""Graph views. All counts refer to the selected snapshot."""
def complete(nodes, edges):
    versions={n['id']:n['version'] for n in nodes}
    valid=[e for e in edges if e['source'] in versions and e['target'] in versions]
    connected={e[k] for e in valid for k in ('source','target')}
    return {'nodes':[{k:n[k] for k in ('id','type','title','version','status')} for n in nodes],
            'edges':[{**e,'stale':versions[e['source']]!=e['source_version'] or versions[e['target']]!=e['target_version']} for e in valid],
            'total_nodes':len(nodes),'total_edges':len(edges),'scope_nodes':len(nodes),
            'remaining_nodes':0,'boundary_edges':0,'isolated_nodes':len(set(versions)-connected),
            'invalid_edges':len(edges)-len(valid),'truncated':False,'aggregate':False}

def aggregate(nodes,edges):
    byid={n['id']:n for n in nodes};counts={};pairs={}
    for n in nodes:counts[n['type']]=counts.get(n['type'],0)+1
    for e in edges:
        if e['source'] not in byid or e['target'] not in byid:continue
        pair=(byid[e['source']]['type'],byid[e['target']]['type'])
        pairs[pair]=pairs.get(pair,0)+1
    return {'nodes':[{'id':'type:'+k,'type':k,'title':f'{k} · {v} 个对象','version':0,'status':'aggregate','data':{},'count':v} for k,v in sorted(counts.items())], 'edges':[{'id':a+':'+b,'source':'type:'+a,'target':'type:'+b,'type':'聚合登记关系','evidence':f'{count} 条登记关系','count':count,'stale':False} for (a,b),count in pairs.items()], 'aggregate':True,'total_nodes':len(nodes),'total_edges':len(edges),'scope_nodes':len(counts),'remaining_nodes':0,'boundary_edges':0,'isolated_nodes':len(set(byid)-{e[k] for e in edges for k in ('source','target')}),'truncated':False,'backend':'authority'}

def select(nodes, edges, focus='', hops=1, kind='', limit=200, offset=0):
    versions={n['id']:n['version'] for n in nodes}
    edges=[{**e,'stale':versions.get(e['source'])!=e['source_version'] or versions.get(e['target'])!=e['target_version']} for e in edges]
    connected={e[k] for e in edges for k in ('source','target')}
    local={n['id'] for n in nodes}
    if focus:
        local={focus}
        for _ in range(max(1,min(hops,2))):
            local |= {e[k] for e in edges if e['source'] in local or e['target'] in local for k in ('source','target')}
    eligible=sorted((n for n in nodes if n['id'] in local and (not kind or n['type']==kind)),key=lambda n:(n['id']!=focus,n['id'] not in connected,n['type'],n['id']))
    if not focus and not kind:
        # Keep real connected neighborhoods together, rather than taking one type
        # whose referenced targets all fall outside the first batch.
        byid={n['id']:n for n in eligible};adj={k:[] for k in byid}
        for e in edges:
            if e['source'] in byid and e['target'] in byid:
                adj[e['source']].append(e['target']);adj[e['target']].append(e['source'])
        ordered=[];seen=set()
        for seed in sorted(byid,key=lambda k:(-len(adj[k]),k)):
            queue=[seed]
            for oid in queue:
                if oid in seen:continue
                seen.add(oid);ordered.append(byid[oid])
                queue.extend(k for k in adj[oid] if k not in seen)
        eligible=ordered
    limit=max(1,min(limit,500));offset=max(0,offset)
    selected=eligible[offset:offset+limit];keep={n['id'] for n in selected}
    visible=[e for e in edges if e['source'] in keep and e['target'] in keep]
    boundary=[e for e in edges if (e['source'] in keep)!=(e['target'] in keep)]
    return {'nodes':selected,'edges':visible,'limit':limit,'offset':offset,'total_nodes':len(nodes),'total_edges':len(edges),'scope_nodes':len(eligible),'remaining_nodes':max(0,len(eligible)-offset-len(selected)), 'boundary_edges':len(boundary),'isolated_nodes':len(set(versions)-connected),'invalid_edges':sum(e['source'] not in versions or e['target'] not in versions for e in edges),'boundary_nodes':sorted({e[k] for e in boundary for k in ('source','target')}-keep),'truncated':len(selected)<len(eligible),'backend':'authority'}
