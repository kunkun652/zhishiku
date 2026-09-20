import json,runpy,shutil,hashlib
from pathlib import Path
root=Path(__file__).resolve().parent
release=root/'release/知衡仿真知识库'
templates=runpy.run_path(str(root/'src/app/templates.py'))['TEMPLATES']
(release/'templates').mkdir(exist_ok=True)
for key,t in templates.items():
    data={'schema':'zhiheng-object/1','type':key,'title':'','status':'candidate','data':{f['key']:[] if f['kind']=='json' else '' for f in t['fields']}}
    (release/'templates'/(t['label'].replace('/','-')+'.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
for name in ['README.md','接口与架构映射.md']:
    shutil.copy2(root/name,release/name)
lic=release/'licenses';lic.mkdir(exist_ok=True)
sem=Path(r'D:\zhishiku\runtime\semantica-packages\semantica-0.6.8.dist-info')
shutil.copy2(sem/'licenses/LICENSE',lic/'Semantica-LICENSE.txt')
shutil.copy2(sem/'METADATA',lic/'Semantica-METADATA.txt')
for base,label in [(Path(r'D:\知识库\work\rag-platform\venv\Lib\site-packages'),'desktop'),(Path(r'D:\zhishiku\runtime\semantica-packages'),'semantic')]:
    for info in base.glob('*.dist-info'):
        for p in info.rglob('*'):
            if p.is_file() and ('license' in p.name.lower() or 'copying' in p.name.lower()) and p.stat().st_size<2_000_000:
                dest=lic/label/info.name/p.relative_to(info);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
files=[]
for p in sorted(release.rglob('*')):
    if p.is_file() and 'data' not in p.relative_to(release).parts:
        files.append({'path':p.relative_to(release).as_posix(),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
(root/'evidence/release-manifest.json').write_text(json.dumps(files,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'files':len(files),'bytes':sum(f['bytes'] for f in files),'templates':len(templates),'exe_sha256':next(f['sha256'] for f in files if f['path']=='知衡仿真知识库.exe')},ensure_ascii=False))
