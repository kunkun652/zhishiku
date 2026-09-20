import json,html,re
from pathlib import Path
from ingest import kb,DATA,BASE
def run():
 with kb.connect() as c:
  for r in c.execute('SELECT s.category,f.path FROM sources s JOIN files f ON f.id=s.file_id').fetchall():
   old=(DATA/r['path']).resolve();dest=(DATA/'assets'/r['category']/old.name).resolve()
   assert old.is_relative_to(DATA/'assets') and dest.is_relative_to(DATA/'assets')
   if old==dest:continue
   dest.parent.mkdir(parents=True,exist_ok=True)
   if not dest.exists():old.rename(dest)
   c.execute('UPDATE files SET path=? WHERE path=?',(str(dest.relative_to(DATA)),r['path']))
  c.commit()
  catalog=BASE.parent/'资料分类目录';catalog.mkdir(exist_ok=True)
  cats={}
  for r in c.execute('SELECT s.*,o.title,f.path,f.name FROM sources s JOIN objects o ON o.id=s.object_id JOIN files f ON f.id=s.file_id'):
   cats.setdefault(r['category'],[]).append(dict(r))
  for cat,rows in cats.items():
   d=catalog/cat;d.mkdir(exist_ok=True)
   (d/'资料清单.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
   body=''.join('<tr><td>'+html.escape(r['title'])+'</td><td>'+html.escape(r['extraction'])+'</td><td><a href="'+(DATA/r['path']).as_uri()+'">打开原件</a></td></tr>' for r in rows)
   (d/'浏览资料.html').write_text('<!doctype html><meta charset="utf-8"><title>'+cat+'</title><style>body{font:16px Microsoft YaHei;margin:40px;background:#f5f7fc}td{padding:12px;border-bottom:1px solid #ddd}a{color:#6849bd}</style><h1>'+cat+'</h1><p>按内容哈希去重保存；名称分类是候选分类，正文与工程适用性仍需复核。</p><table>'+body+'</table>',encoding='utf-8')
  (catalog/'打开分类目录.html').write_text('<!doctype html><meta charset="utf-8"><title>知衡资料分类</title><h1>原始资料分类目录</h1>'+''.join('<p><a href="'+cat+'/浏览资料.html">'+cat+'</a> · '+str(len(rows))+' 份</p>' for cat,rows in cats.items()),encoding='utf-8')
if __name__=='__main__':run()
