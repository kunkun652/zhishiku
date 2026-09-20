import json,re
from build_cards import kb,link,write_object,BASE
with kb.connect() as c:
 rows=[kb.record(r) for r in c.execute("SELECT * FROM objects WHERE type IN ('term','condition','material','mesh')")]
 legacy={}
 for r in rows:
  raw=json.loads(r['data'].get('original_record') or '{}')
  key=raw.get('card_id') or raw.get('condition_id')
  if key:legacy[key]=r['id']
 missing=[];linked=0
 for r in rows:
  raw=json.loads(r['data'].get('original_record') or '{}')
  for field,relation in [('core_condition_ids','采用工况'),('conditional_condition_ids','采用工况'),('upstream_condition_ids','载荷来自'),('mesh_relation_ids','采用网格策略'),('material_relation_ids','采用材料')]:
   for old in filter(None,re.split(r'[;；,，\s]+',raw.get(field,''))):
    if old in legacy:
     link(c,r['id'],legacy[old],relation,'原始卡片字段 '+field+' 引用 '+old+'；语义关联候选，适用性仍需核对');linked+=1
    else:missing.append({'object_id':r['id'],'field':field,'legacy_id':old})
 if missing:
  write_object(c,'gap','旧卡片引用尚未完全解析',{'summary':f'{len(missing)} 个旧卡片引用未在本批结构化卡片中找到，不自动用相似卡替换。','category':'10_任务与覆盖','source':'原CSV core/conditional/upstream/mesh/material 引用字段','missing':json.dumps(missing,ensure_ascii=False),'resolution':'导入所缺完整卡片，核对ID与适用性，再补齐关系。'},'gap:legacy-card-links')
 c.commit()
 (BASE/'card-links.json').write_text(json.dumps({'linked':linked,'unresolved':missing},ensure_ascii=False,indent=2),encoding='utf-8')
print('linked',linked,'unresolved',len(missing))
