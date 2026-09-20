import csv,json,re,uuid
from pathlib import Path
from ingest import kb,BASE,DATA,write_object,sha_file,import_file
def link(c,a,b,typ,why):
 if a==b:return
 if c.execute('SELECT 1 FROM relations WHERE source=? AND target=? AND type=?',(a,b,typ)).fetchone():return
 c.execute('INSERT INTO relations VALUES(?,?,?,?,?,?,?)',(str(uuid.uuid4()),a,b,typ,why,1,1))
def run():
 base=Path('D:/知识库/知识库');mapping={};count={}
 ledger={r['source_id']:r for r in csv.DictReader((base/'00_模板与规范/资料来源总台账.csv').open(encoding='utf-8-sig'))}
 with kb.connect() as c:
  # Public batches may finish after the bulk importer starts.
  public={}
  for line in (BASE/'public-manifest.jsonl').read_text('utf-8').splitlines():
   r=json.loads(line);public[r['url']]=r
  corrected={'19900016052':'NASA TM102681 · 复合材料与金属结构的碰撞载荷响应（扩展参考）','19940021218':'SUPERCRUISER ARROW HS-8 · 高速民机概念设计（含机翼结构）'}
  for r in public.values():
   for key,title in corrected.items():
    if key in r['url']:r['title']=title
   import_file(c,Path(r['path']),r)
  basic_sha='4d935bdccd2c6fc2789215943b402d9ba73476d24873fbed6ee34a95ee9f4998'
  basic=c.execute('SELECT object_id,file_id FROM sources WHERE sha=?',(basic_sha,)).fetchone()
  basic_terms=[('驾驶舱','Cockpit','驾驶员操纵飞机并进行飞行通信的控制区域。'),('机身','Fuselage;飞机机身','飞机的主体，连接各主要部件，使其组成完整飞行器。'),('喷气发动机','Jet engine','通过喷流产生推力的动力装置。'),('垂直安定面','Vertical stabilizer;垂尾','有助于保持飞机方向稳定的垂直尾翼部分。'),('机翼','Wing;飞机机翼','飞机上产生主要升力的翼面。机翼与气流的相对运动产生气动力，其中升力支撑飞机。'),('扰流板','Spoiler','机翼上表面的可动板，用于减小升力并协助减速。'),('方向舵','Rudder','垂直安定面上的可动操纵面，用于控制偏航。'),('水平安定面','Horizontal stabilizer;平尾','有助于保持飞机俯仰稳定的水平尾翼部分。'),('起落架','Landing gear','飞机在地面和着陆时的支承装置，包含机轮、支柱和减震部件。'),('前缘缝翼','Slat','机翼前缘的可动增升装置。'),('襟翼','Flap','机翼后缘的可动增升装置，常在起飞和着陆阶段使用。'),('升降舵','Elevator','水平尾翼上的可动操纵面，用于控制俯仰。'),('副翼','Aileron','位于机翼外侧后缘的操纵面，用于控制滚转。'),('翼梢小翼','Winglet','机翼端部的翼面装置，可减小翼梢相关阻力。')]
  if basic:
   for n,(title,aliases,definition) in enumerate(basic_terms,1):
    oid=write_object(c,'term',title,{'definition':definition,'summary':definition,'aliases':aliases,'source':'NASA Parts of an Airplane, LG-2010-04-027-HQ，PDF第2页，第'+str(n)+'项；https://www.nasa.gov/wp-content/uploads/2015/04/parts_of_an_airplane_eng_span.pdf','category':'01_力学与结构基础','scope':'常规固定翼飞机部件入门','limitations':'中文释义为原文概括；具体构型和工程用途需要查看模型与专用资料。','rights':'NASA公开科普资料；训练与再分发许可仍需按用途核对','verification':'已核对原件第2页对应部件条目；待独立复核'},'basic-term:'+title)
    link(c,oid,basic[0],'来源于','NASA图解原件PDF第2页第'+str(n)+'项')
    # Keep the source accessible directly from the card as well as the graph.
    f=c.execute('SELECT * FROM files WHERE id=?',(basic['file_id'],)).fetchone()
    fid=str(uuid.uuid5(uuid.NAMESPACE_URL,oid+basic_sha))
    c.execute('INSERT OR IGNORE INTO files VALUES(?,?,?,?,?,?)',(fid,oid,f['name'],f['sha256'],f['size'],f['path']))
  for name,kind in [('术语卡.csv','term'),('主材料卡.csv','material'),('网格策略卡.csv','mesh'),('工况卡.csv','condition'),('综合工况卡.csv','condition'),('工况派生卡.csv','condition')]:
   for p in base.rglob(name):
    source=c.execute('SELECT object_id FROM sources WHERE sha=?',(sha_file(p),)).fetchone()
    for i,row in enumerate(csv.DictReader(p.open(encoding='utf-8-sig'))):
     row={k:v or '' for k,v in row.items() if k}
     cid=row.get('card_id') or row.get('condition_id') or str(i)
     title=row.get('name') or row.get('condition_name_cn') or cid
     data={'summary':row.get('statement_or_value',''),'source':str(p)+f'；数据行 {i+2}；'+row.get('source_ids','')+'；'+row.get('source_locator',''),'category':{'term':'01_力学与结构基础','material':'04_材料','mesh':'03_网格','condition':'05_载荷与边界'}[kind],'rights':'沿用本地资料；训练与再分发权限待确认','scope':row.get('applicability',''),'units':row.get('unit_system',''),'limitations':row.get('limitations','')+' 导入候选，历史执行就绪标记不作为本库授权。','verification':row.get('evidence',''),'original_record':json.dumps(row,ensure_ascii=False)}
     if kind=='term':data.update(definition=row.get('definition') or data['summary'],aliases=';'.join(filter(None,[row.get('aliases'),row.get('term_cn'),row.get('term_en'),row.get('synonyms')])),confusions=row.get('ambiguities',''))
     elif kind=='material':
      props=json.loads(row.get('properties_json') or '{}');out=[]
      if isinstance(props,dict):
       for key,v in props.items():
        if isinstance(v,dict):out.append({'name':key,'value':v.get('value') if isinstance(v.get('value'),(int,float)) else None,'unit':v.get('unit',''),'source':v.get('source_locator') or row.get('source_locator',''),'original':v})
      data.update(designation=row.get('grade',''),state=row.get('condition_or_heat_treatment',''),temperature=row.get('temperature',''),direction=row.get('direction',''),properties=out,solver_card=row.get('solver_card_mapping','') if row.get('solver_card_mapping','') in ('MAT1','MAT8') else '')
     elif kind=='mesh':data.update(geometry=row.get('geometry_features',''),element_type=row.get('element_types',''),method=row.get('statement_or_value',''),quality=row.get('acceptance_basis','')+'（旧卡原文，阈值来源待复核）',convergence=row.get('inspection_method',''),analysis_type=row.get('analysis_types',''))
     else:data.update(level=row.get('structure_object',''),core=row.get('required_inputs',''),conditional=row.get('environment_conditions',''),upstream=row.get('load_card_ids',''),mesh='',material='',loads=row.get('load_card_ids',''),constraints=row.get('constraint_card_ids',''),analysis_type=row.get('analysis_type',''))
     oid=write_object(c,kind,title,data,'card:'+name+':'+cid);mapping[cid]=oid;count[kind]=count.get(kind,0)+1
     if source:link(c,oid,source[0],'来源于',f'完整CSV数据行 {i+2}；保留原记录')
     for sid in re.split(r'[;；,，\s]+',row.get('source_ids','')):
      original=ledger.get(sid)
      if not original:continue
      target=c.execute('SELECT object_id FROM sources WHERE sha=?',(original.get('sha256',''),)).fetchone()
      if target:link(c,oid,target[0],'来源于',sid+'；'+row.get('source_locator','')+'；哈希与来源总台账相符，内容适用性待复核')
  # Report cases refer to actual documents; no manufactured simulation outputs.
  for r in c.execute("SELECT s.*,o.title FROM sources s JOIN objects o ON o.id=s.object_id WHERE s.paths LIKE '%PDF案例报告%' OR (s.paths LIKE '%案例库%' AND o.type='document')").fetchall():
   if not re.search('静|强度|结构|机翼|机身|frame|wing|stress|modal|模态',r['title'],re.I):continue
   data={'summary':'文献案例候选：已收录原始报告，尚未完成方法与参数的工程复核。','source':r['paths'],'category':'06_仿真方法与案例','goal':r['title'],'inputs':'原文见关联资料；可运行输入文件关联待确认','logs':'待补充','results':'原始报告不等于本地求解结果；待核对','checks':'原件哈希与正文索引；工程验证待补充','limitations':'不得将报告标题或相似案例参数当作当前模型事实。'}
   oid=write_object(c,'case','文献案例 · '+r['title'],data,'report-case:'+r['sha']);link(c,oid,r['object_id'],'来源于','原始报告登记，非自动复现结果')
  # Task workbook preserved verbatim, with engineering values kept out of validated fields.
  refs=json.loads((BASE/'reference-sheets.json').read_text('utf-8'))
  for path,sheets in refs.items():
   if '飞机结构仿真任务' not in path:continue
   for sheet,rows in sheets.items():
    for i,row in enumerate(rows[1:],2):
     if len(row)<9 or not row[1]:continue
     raw=dict(zip(rows[0],row));title=f'{row[1]} · {row[3]} {row[4]} · {row[8]}'
     write_object(c,'task',title,{'goal':row[8],'summary':'来源任务清单；用于采集覆盖规划，未核准载荷和适航要求。','source':path+f'；{sheet}；第{i}行','category':'10_任务与覆盖','original_record':json.dumps(raw,ensure_ascii=False),'limitations':'原始单元格为计划数据；载荷、条款版本、适用性均待确认。','acceptance':'取得当前任务原始依据、模型、输入、日志、结果、显示证据及复核记录后再验收。'},'task-row:'+sheet+':'+row[1])
  # Explicit method card requested by the user, linked to collected term/mesh/condition records.
  selected=[dict(r) for r in c.execute("SELECT * FROM objects WHERE type IN ('term','mesh','condition') AND (title LIKE '%机身框%' OR title LIKE '%环框%')")]
  case=write_object(c,'case','机身框静强度仿真 · 方法与资料包',{'summary':'检索机身框定义、模型、材料、载荷和网格依据的准备案例；不是已求解案例。','source':'用户采集目标 + 旧库机身框相关卡片；关联依据见图谱','category':'06_仿真方法与案例','analysis_type':'静强度 静力 STATIC_STRESS','goal':'评估给定机身框在线弹性、小变形且边界条件已确定时的应力与位移；许用值与判据需另有来源。','assumptions':'线弹性与小变形适用性待确认；不能用本流程替代屈曲、疲劳、损伤容限或接触分析。','card_ids':'\n'.join(x['id'] for x in selected),'steps':'1.读取当前框几何、单位、坐标与截面/厚度来源。\n2.检索匹配材料和工况，核对上游载荷与接口传递。\n3.按几何与分析目标选梁/壳/实体策略，验证连接与网格收敛。\n4.冻结输入、材料、载荷和边界版本。\n5.有执行授权后求解并保留输入/日志/结果。\n6.检查载荷平衡、刚体运动、收敛和应力位置；独立复核。','differences':'可复用资料选择与检查顺序；几何、材料、厚度、载荷、约束与许用值必须按当前模型取得。','inputs':'待提供当前模型及求解输入','logs':'待运行','results':'待运行','visual_evidence':'待运行后显示并核对','checks':'原始依据、单位、载荷平衡、连接、收敛、结果位置、人员复核均需留证','limitations':'准备级候选；不可直接执行，不能宣称强度合格。'},'curated:fuselage-frame-static')
  for s in selected:link(c,case,s['id'],{'term':'来源于','mesh':'采用网格策略','condition':'采用工况'}[s['type']],'语义匹配候选，执行前检查适用性')
  ds=write_object(c,'dataset','知识卡片与案例 · 微调候选数据登记',{'summary':'完整卡片JSONL + 案例JSONL + 检索评测问题；未执行微调。','category':'11_训练与评测','source':'本库版本化对象与原件哈希','rights':'逐来源训练许可待确认','family':'按原始来源 / 几何家族隔离；同一原件的卡片与切片不得跨训练评测集合','split':'未划分；复核与许可通过后冻结','selection':'只纳入来源可定位且人工复核的行为、工具选择与缺口处理样本；易变工程参数继续检索','review':'未复核；training_ready=false','limitations':'当前导出是候选索引，不是可直接训练的数据集。'},'dataset:candidate-v1')
  c.commit()
  export=BASE/'exports';export.mkdir(exist_ok=True)
  for name,types in [('cards',('term','material','mesh','condition')),('cases',('case',)),('tasks',('task',))]:
   with (export/(name+'.jsonl')).open('w',encoding='utf-8') as f:
    for r in c.execute('SELECT * FROM objects'):
     if r['type'] in types:f.write(json.dumps({**kb.record(r),'schema':'zhiheng-object/1','training_ready':False},ensure_ascii=False)+'\n')
  (BASE/'card-report.json').write_text(json.dumps({'imported_cards':count,'counts':kb.health()['counts'],'frame_case':case},ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__':run()
