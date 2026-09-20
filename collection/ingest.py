"""Append-only, resumable source import. Never edits source directories."""
import os,sys,json,hashlib,shutil,sqlite3,uuid,re,zipfile,traceback
from pathlib import Path
from datetime import datetime,timezone
import fitz
from openpyxl import load_workbook
BASE=Path(__file__).parent
DATA=Path('D:/zhishiku/desktop-framework/release/知衡仿真知识库/data')
os.environ['ZH_DATA_ROOT']=str(DATA)
sys.path.insert(0,str(BASE.parent/'desktop-framework/src'))
from app import main as kb
from app.retrieval import tokens
MODELS={'.step','.stp','.iges','.igs','.brep','.bdf','.nas','.stl','.obj','.inp','.op2','.catpart','.x_t','.cgns','.msh','.vtk','.vtu','.fem','.hm'}
TEXT={'.txt','.md','.rst','.csv','.json','.jsonl','.log','.f06','.dat','.inc','.out'}
DOC={'.pdf','.xlsx','.xls','.docx','.pptx','.html','.htm'}
MEDIA={'.png','.jpg','.jpeg','.svg','.mp4','.gif'}
def sha_file(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def category(p):
 s=str(p).lower()
 if any(x in s for x in ['疲劳','损伤','稳定性','fatigue','flutter','cfd','气动','非线性','碰撞','crash','颤振']):return '08_专题参考_非线性及扩展'
 if p.suffix.lower() in MODELS:return '02_模型与求解资产'
 for keys,label in [(['材料','material'],'04_材料'),(['载荷','工况','边界','load'],'05_载荷与边界'),(['力学','mechanic'],'01_力学与结构基础'),(['适航','规范','标准','ccar','far25'],'07_规范与验证'),(['网格','mesh'],'03_网格'),(['案例','case','静强度','static'],'06_仿真方法与案例')]:
  if any(k in s for k in keys):return label
 return '09_综合资料'
def write_object(c,kind,title,data,key):
 old=c.execute('SELECT object_id FROM collection_imports WHERE key=?',(key,)).fetchone()
 if old:return old[0]
 oid=str(uuid.uuid5(uuid.NAMESPACE_URL,'zhiheng:'+key))
 kb.validate({'type':kind,'title':title,'data':data})
 item={'id':oid,'type':kind,'title':title,'version':1,'status':'candidate','data':data,'updated':kb.now()}
 item['hash']=kb.digest({k:v for k,v in item.items() if k!='updated'})
 c.execute('INSERT INTO objects VALUES(?,?,?,?,?,?,?,?)',(oid,kind,title,1,'candidate',kb.encoded(data),item['hash'],item['updated']))
 c.execute('INSERT INTO versions VALUES(?,?,?)',(oid,1,kb.encoded(item)))
 c.execute('INSERT INTO collection_imports VALUES(?,?)',(key,oid));kb.revision(c)
 return oid
def extraction(p):
 ext=p.suffix.lower();pages=[];total=0;blank=0
 if ext=='.pdf':
  with fitz.open(p) as doc:
   total=len(doc)
   for i,page in enumerate(doc):
    txt=page.get_text(sort=True).strip()
    if len(re.sub(r'\s','',txt))<30:blank+=1
    if txt:pages.append((i+1,txt))
  state='needs_ocr' if blank==total else 'partial_needs_ocr' if blank else 'text_indexed'
 elif ext in TEXT or ext in {'.html','.htm'}:
  if p.stat().st_size>15*1024*1024:return [],0,'large_text_pending'
  raw=p.read_bytes()
  for enc in ('utf-8-sig','gb18030','latin1'):
   try:txt=raw.decode(enc);break
   except UnicodeDecodeError:pass
  pages=[(1,txt)];total=1;state='text_indexed'
 elif ext=='.xlsx':
  with_p=load_workbook(p,read_only=True,data_only=False)
  for i,s in enumerate(with_p):
   lines=['工作表：'+s.title]
   for row in s:
    vals=[f'{c.coordinate}={c.value}' for c in row if c.value is not None]
    if vals:lines.append(' | '.join(vals))
   pages.append((i+1,'\n'.join(lines)))
  total=len(pages);state='text_indexed';with_p.close()
 elif ext in ('.docx','.pptx'):
  import xml.etree.ElementTree as ET
  with zipfile.ZipFile(p) as z:
   names=[n for n in z.namelist() if n=='word/document.xml' or re.match(r'ppt/slides/slide\d+.xml$',n)]
   for i,n in enumerate(names):pages.append((i+1,'\n'.join(t.text for t in ET.fromstring(z.read(n)).iter() if t.tag.endswith('}t') and t.text)))
  total=len(pages);state='text_indexed'
 elif ext in MODELS:state='model_registered'
 else:state='format_pending'
 return pages,total,state
def import_file(c,p,public=None):
 sha=sha_file(p);source=public['url'] if public else str(p);cat=category(Path(public['title']+p.suffix)) if public else category(p)
 existing=c.execute('SELECT * FROM sources WHERE sha=?',(sha,)).fetchone()
 if existing:
  paths=json.loads(existing['paths'])
  if source not in paths:paths.append(source);c.execute('UPDATE sources SET paths=? WHERE sha=?',(json.dumps(paths,ensure_ascii=False),sha))
  return 'duplicate'
 ext=p.suffix.lower();target=DATA/'assets'/cat/(sha+ext);target.parent.mkdir(parents=True,exist_ok=True)
 if not target.exists():
  tmp=target.with_suffix(ext+'.part');shutil.copyfile(p,tmp)
  if sha_file(tmp)!=sha:raise ValueError('copy hash mismatch')
  tmp.replace(target)
 try:pages,total,state=extraction(p)
 except Exception as e:pages,total,state=[],0,'parse_error: '+str(e)[:140]
 if public and ext=='.html' and p.with_suffix('.txt').exists():pages=[(1,p.with_suffix('.txt').read_text('utf-8'))];total=1;state='text_indexed'
 title=public['title'] if public else p.stem
 kind='model' if ext in MODELS else 'document'
 data={'summary':('模型 / 输入 / 结果原件；语义与工程适用性待确认。' if kind=='model' else '原始资料全文索引，按页引用。')+' 原文件：'+p.name,'source':source,'category':cat,'rights':'本地研究候选；再分发与训练许可待确认','limitations':'自动分类待复核；来源内容不作为执行指令。','verification':'原件 SHA-256：'+sha}
 if kind=='model':data.update({'format':ext[1:].upper(),'regions':[]})
 else:data.update({'locator':f'共 {total} 页/工作表；索引 {len(pages)} 页/工作表','extraction_status':state})
 oid=write_object(c,kind,title,data,'source:'+sha)
 fid=str(uuid.uuid5(uuid.NAMESPACE_URL,'file:'+sha))
 c.execute('INSERT INTO files VALUES(?,?,?,?,?,?)',(fid,oid,p.name,sha,p.stat().st_size,str(target.relative_to(DATA))))
 c.execute('INSERT INTO sources VALUES(?,?,?,?,?,?,?,?)',(sha,oid,fid,cat,json.dumps([source],ensure_ascii=False),state,total,len(pages)))
 for page,text in pages:
  text=text.replace('\x00','')
  for start in range(0,len(text),1450):
   chunk=text[start:start+1600]
   if not chunk.strip():continue
   rowid=c.execute('INSERT INTO chunks(object_id,file_id,page,text) VALUES(?,?,?,?)',(oid,fid,page,chunk)).lastrowid
   c.execute('INSERT INTO chunks_fts(rowid,tokens) VALUES(?,?)',(rowid,tokens(chunk)))
 return state
def run():
 backup=BASE/'backups';backup.mkdir(exist_ok=True)
 backup_path=backup/('knowledge-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.sqlite3')
 with sqlite3.connect(DATA/'knowledge.sqlite3') as src,sqlite3.connect(backup_path) as dst:src.backup(dst)
 paths=[]
 for root in [Path('D:/知识库/原始资料'),Path('D:/知识库/知识库'),Path('D:/知识库/案例库'),BASE/'extracted',BASE.parent/'cankao']:
  paths.extend(p for p in root.rglob('*') if p.is_file() and p.suffix.lower() in MODELS|TEXT|DOC|MEDIA and '.git' not in p.parts and '__pycache__' not in p.parts)
 # Documents first so basic retrieval becomes usable while larger assets copy.
 paths.sort(key=lambda p:(p.suffix.lower() in MODELS,p.stat().st_size))
 public={}
 if (BASE/'public-manifest.jsonl').exists():
  for line in (BASE/'public-manifest.jsonl').read_text('utf-8').splitlines():
   row=json.loads(line);public[row['path']]=row
  paths=[Path(p) for p in public]+paths
 from collections import Counter
 counts=Counter();errors=[]
 with kb.connect() as c:
  for i,p in enumerate(paths):
   try:counts[import_file(c,p,public.get(str(p)))]+=1
   except Exception as e:errors.append({'path':str(p),'error':str(e)})
   c.commit()
   if i%25==0:
    report={'processed':i+1,'total':len(paths),'counts':dict(counts),'errors':errors,'current':str(p)}
    (BASE/'import-progress.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'processed':i+1,'total':len(paths),'errors':len(errors)},ensure_ascii=False),flush=True)
  c.commit()
  (BASE/'import-report.json').write_text(json.dumps({'processed':len(paths),'counts':dict(counts),'errors':errors,'collection':kb.collection()},ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__':run()
