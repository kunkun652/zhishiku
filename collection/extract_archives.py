import json, subprocess
from pathlib import Path, PurePosixPath
root=Path(__file__).parent
report=[]
for a in json.loads((root/'inventory.json').read_text('utf-8'))['archives']:
 p=Path(a['path']); dest=root/'extracted'/p.stem
 entries=a.get('entries',[])
 assert entries and len(entries)<10000 and sum(e['size'] for e in entries)<10_000_000_000
 for e in entries:
  name=e['name'].replace('\\','/'); q=PurePosixPath(name)
  assert not q.is_absolute() and '..' not in q.parts and ':' not in name
 dest.mkdir(parents=True,exist_ok=True)
 result=subprocess.run(['C:/Program Files/WinRAR/WinRAR.exe','x','-ibck','-y','-o-',str(p),str(dest)+'\\'],timeout=900)
 report.append({'archive':str(p),'destination':str(dest),'exit':result.returncode,'expected':len(entries),'actual':sum(1 for f in dest.rglob('*') if f.is_file())})
 (root/'extraction-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(report[-1],ensure_ascii=False),flush=True)
