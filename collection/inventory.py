import json, zipfile, collections
from pathlib import Path
ROOT=Path(__file__).parent
roots=[Path('D:/知识库/原始资料'),Path('D:/知识库/知识库'),Path('D:/知识库/案例库'),Path('D:/zhishiku/资料收集部分-王月壮')]
rows=[]; archives=[]
for root in roots:
 for p in root.rglob('*'):
  if p.is_file():
   rows.append({'path':str(p),'size':p.stat().st_size,'suffix':p.suffix.lower(),'root':str(root)})
   if p.suffix.lower()=='.zip' and '王月壮' in str(p):
    try:
     with zipfile.ZipFile(p) as z:
      entries=[{'name':i.filename,'size':i.file_size,'compressed':i.compress_size} for i in z.infolist() if not i.is_dir()]
      archives.append({'path':str(p),'entries':entries})
    except Exception as e: archives.append({'path':str(p),'error':str(e)})
(ROOT/'inventory.json').write_text(json.dumps({'files':rows,'archives':archives},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'files':len(rows),'bytes':sum(r['size'] for r in rows),'archives':[{'path':a['path'],'count':len(a.get('entries',[])),'bytes':sum(e['size'] for e in a.get('entries',[])),'sample':a.get('entries',[])[:3],'error':a.get('error')} for a in archives]},ensure_ascii=False))
