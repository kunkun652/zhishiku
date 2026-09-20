"""Chinese phrase/alias retrieval and page evidence, without generated factual answers."""
import json,re,sqlite3
from . import content_quality

def init(c):
 content_quality.init(c)
 c.executescript('''CREATE TABLE IF NOT EXISTS sources(sha TEXT PRIMARY KEY, object_id TEXT, file_id TEXT, category TEXT, paths TEXT, extraction TEXT, pages INTEGER, indexed_pages INTEGER);
 CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY, object_id TEXT, file_id TEXT, page INTEGER, text TEXT);
 CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(tokens,content='', tokenize='unicode61');
 CREATE INDEX IF NOT EXISTS chunks_object ON chunks(object_id);
 CREATE INDEX IF NOT EXISTS chunks_file_page ON chunks(file_id,page);
 CREATE TABLE IF NOT EXISTS collection_imports(key TEXT PRIMARY KEY, object_id TEXT);''')

def tokens(text):
 parts=re.findall(r'[a-z0-9_]+|[\u3400-\u9fff]+',text.casefold())
 out=[]
 for p in parts:
  if re.fullmatch(r'[\u3400-\u9fff]+',p): out.extend(p[i:i+2] for i in range(max(1,len(p)-1)))
  else: out.append(p)
 return ' '.join(out)

def groups_for(q,items):
 text=q.strip().casefold()
 text=re.sub(r'是什么意思|含义是什么|什么是|是什么|的含义|请问|请帮我|帮我|我想了解|我想做|如何进行|怎么做|问一个|查找|检索|搜一下|搜索|一个|[？?，,。！!]',' ',text).strip()
 text=text.replace('飞机机身','机身').replace('飞机机翼','机翼')
 lex=[(['静强度','静力','静态强度','static stress','static strength'],'静强度'),(['机身框','机身环框','fuselage frame','ring frame'],'机身框'),(['机身','fuselage'],'机身'),(['机翼','wing'],'机翼'),(['模态','modal'],'模态')]
 aliases=[]
 for r in items:
  if r['type']=='term' and r['status'] not in ('retired','conflict'):
   a=[r['title']]+re.split(r'[,，;；\n/|]+',r['data'].get('aliases',''))
   a=[v.strip().casefold() for v in a if 1<len(v.strip())<65]
   aliases.append(a)
 groups=[]
 for aa in sorted(aliases,key=lambda a:max(map(len,a),default=0),reverse=True):
  matches=[a for a in aa if a in text]
  if matches:
   longest=max(matches,key=len); groups.append(aa);text=text.replace(longest,' ')
 for aa,_ in lex:
  if any(a in text for a in aa):
   groups.append(aa)
   for a in aa:text=text.replace(a,' ')
 text=re.sub(r'仿真|分析|资料|案例|介绍|含义|什么|是|请|帮|我|一下|进行|怎么|如何|的',' ',text)
 groups += [[t] for t in re.split(r'\s+',text) if t]
 return groups

def retrieve(c,items,q,kind='',analysis='',status='',category='',limit=100,offset=0):
 groups=groups_for(q,items) if q.strip() else []
 hits={}
 if groups:
  clauses=[]
  for group in groups:
   variants=[]
   for a in group[:12]:
    t=tokens(a).split()
    if t: variants.append('('+' AND '.join('"'+v.replace('"','')+'"' for v in t)+')')
   if variants:clauses.append('('+' OR '.join(variants)+')')
  if clauses:
   query=' AND '.join(clauses)
   for row in c.execute('SELECT c.*,bm25(chunks_fts) rank FROM chunks_fts JOIN chunks c ON c.id=chunks_fts.rowid WHERE chunks_fts MATCH ? ORDER BY rank LIMIT 500',(query,)):
    if content_quality.eligible(c,row['id'],row['text']):hits.setdefault(row['object_id'],[]).append(dict(row))
 found=[];excluded=0
 for r in items:
  if kind and r['type']!=kind or status and r['status']!=status or category and r['data'].get('category')!=category:continue
  scope=r['data'].get('analysis_type','').strip()
  if analysis and scope and analysis not in re.split(r'[,，;；/\s]+',scope):excluded+=1;continue
  body=(r['title']+' '+json.dumps(r['data'],ensure_ascii=False)).casefold()
  direct=bool(q.strip()) and (q.strip().casefold() in body or q.strip()==r['id'])
  match=not q.strip() or direct or bool(groups and all(any(a in body for a in group) for group in groups))
  evidence=hits.get(r['id'],[])[:3]
  if not match and not evidence:continue
  title=r['title'].casefold()
  score=sum(12 for g in groups if any(a in title for a in g))+(8 if r['type']=='term' else 4 if r['type']=='case' else 0)+(20 if direct else 0)+(2 if evidence else 0)
  if len(groups)==1 and title in groups[0]:score+=60
  r={**r,'score':score,'applicability':'待确认' if not scope or not analysis else '分析类型匹配；其余条件待确认','match_reason':'正文页码命中' if evidence else '完整对象 / 术语别名匹配','evidence':[{'chunk_id':e['id'],'page':e['page'],'text':e['text'][:1800],'file_id':e['file_id'],'url':f"/api/model-assets/{e['file_id']}/file#page={e['page']}"} for e in evidence]}
  found.append(r)
 found.sort(key=lambda r:r['score'],reverse=True)
 return {'items':found[offset:offset+max(1,limit)],'total':len(found),'excluded':excluded,'expanded_terms':sorted({a for g in groups for a in g}),'status':'ok' if found else 'no_matches','message':'' if found else '未找到可引用依据；请缩短关键词或登记资料缺口。'}
