import json,collections,sqlite3,html
from pathlib import Path
BASE=Path(__file__).parent
a=json.loads((BASE/'acceptance.json').read_text('utf-8'));imp=json.loads((BASE/'import-report.json').read_text('utf-8'));cards=json.loads((BASE/'card-report.json').read_text('utf-8'))
public={r['url']:r for line in (BASE/'public-manifest.jsonl').read_text('utf-8').splitlines() if (r:=json.loads(line))}
stats=a['collection'];counts=a['health']['counts']
lines=['# 本次资料收集与知识构建报告','', '日期：2026-09-20。实际 EXE 已更新，原数据目录保留，旧程序文件见 desktop-framework/backups/pre-collection-20260920。','',
'## 实际结果','',f'- 处理文档及工程资产路径 {imp["processed"]:,} 个；本轮重复内容 {imp["counts"].get("duplicate",0):,} 个。',f'- 去重原件 {stats["sources"]:,} 份；正文片段 {stats["chunks"]:,} 个；有文字页/表 {stats["indexed_pages"]:,} / {stats["pages"]:,}。',f'- 术语卡 {counts.get("term",0)}、材料卡 {counts.get("material",0)}、网格策略卡 {counts.get("mesh",0)}、工况卡 {counts.get("condition",0)}。',f'- 模型/输入/结果资产 {counts.get("model",0):,} 个；候选案例 {counts.get("case",0):,} 个；任务定义 {counts.get("task",0):,} 个。',f'- Scrapy 实际成功采集 {len(public)} 个不同公开URL，原始响应与哈希已保存。',f'- 重新计算校验了 {a["managed_files_verified"]:,} 份受管文件的 SHA-256，共 {a["managed_bytes"]/1024**3:.2f} GiB，差异 {len(a["hash_errors"])}。','',
'## 怎么使用','', '1. 双击 D:\\zhishiku\\新版知衡知识库.lnk，进入“资料与检索”。','2. 输入“什么是飞机机身”“机翼是什么意思”或“机身框静强度仿真”。','3. 查看定义、完整卡片和正文命中，点页码打开原件。','4. 模型搜索 frame 或 wingbox，查看记录后点击预览；支持旋转、缩放和线框。','5. “导入与质量”可查看解析缺口并下载卡片/案例/任务 JSONL；16类模板仍可新建和编辑。','',
'分类目录：../资料分类目录/打开分类目录.html。完整接口与格式说明：接口与数据说明.md。继续采集按接口说明依次运行 collection 中的采集与入库脚本。','',
'## 真实 EXE 检索测试','', '| 问题 | 命中数 | 耗时（秒） | 首条 |','|---|---:|---:|---|']
for q,r in a['queries'].items():lines.append(f'| {q} | {r["total"]} | {r["seconds"]} | {r["top"][0]["title"]} |')
lines+=['','无关问题返回未命中；正文引用可打开实际原件。真实 wingbox BDF 解析结果：'+str(a['mesh'])+'。','自动检查：原有13项回归与新增4项采集检索回归通过。浏览器显示检查单独记录于 browser-acceptance.json。','', '## 未闭合项（不算完成）','', '| 状态 | 数量 |','|---|---:|']
for r in stats['extraction']:lines.append(f'| {r["extraction"]} | {r["count"]} |')
lines+=['','扫描/低文字页未全部OCR，格式待解析与大文本待处理项只保证原件可查，不保证内容级检索。模型预览只覆盖支持格式，不代表所有模型可运行；CATPart、INP、OP2等尚需专用解析器。','',
'当前是全文词法、术语别名与自然语言关键词检索，没有启用embedding或大模型生成问答；不承诺任意问题都正确。','',
'文献案例、任务清单和机身框方法包均为候选；没有新执行CAE求解，没有捏造BDF/F06/OP2链或工程合格结论。未做微调；训练许可、复核和来源家族分组仍待确认，导出 training_ready=false。','',
'本轮登记文档、卡片与工程资产；源仓库程序代码、嵌套归档等未全部作为正文入库。源路径范围见 inventory.json，未改写 D:\\知识库 原件。','',
'## 工具与公开来源','', '[Scrapy GitHub](https://github.com/scrapy/scrapy)；实际版本与依赖见 requirements-lock.txt。']
for url,r in public.items():lines.append('- ['+r['title']+']('+url+')')
lines+=['','## 可核查证据','', 'acceptance.json：真实EXE、查询结果、原件校验与网格解析。','import-report.json / card-report.json / extraction-report.json：导入、完整卡片与压缩包结果。','public-manifest.jsonl / crawl-failures.jsonl：成功来源与失败请求。','exports/*.jsonl：完整卡片、案例、任务离线数据。','', 'EXE SHA-256：`'+a['exe_sha256']+'`。']
(BASE/'本次构建报告.md').write_text('\n'.join(lines),encoding='utf-8')
data=BASE.parent/'desktop-framework/release/知衡仿真知识库/data'
with sqlite3.connect(data/'knowledge.sqlite3') as db:
 db.row_factory=sqlite3.Row
 pending=[dict(r) for r in db.execute("SELECT o.title,s.extraction,s.pages,s.indexed_pages,s.paths,f.path FROM sources s JOIN objects o ON o.id=s.object_id JOIN files f ON f.id=s.file_id WHERE s.extraction NOT IN ('text_indexed','model_registered')")]
(BASE/'待处理资料.json').write_text(json.dumps(pending,ensure_ascii=False,indent=2),encoding='utf-8')
body=''.join('<tr><td>'+html.escape(r['title'])+'</td><td>'+html.escape(r['extraction'])+'</td><td><a href="'+(data/r['path']).as_uri()+'">打开原件</a></td></tr>' for r in pending)
(BASE/'待处理资料.html').write_text('<!doctype html><meta charset="utf-8"><title>待处理资料</title><style>body{font:15px Microsoft YaHei;margin:35px}td{padding:12px;border-bottom:1px solid #ddd;overflow-wrap:anywhere}table{width:100%;table-layout:fixed}</style><h1>正文提取缺口与非文本原件</h1><p>疑似扫描/低文字量图页需OCR核对；非文本图片、视频及未支持格式仅登记原件。原件保留，不自动补造正文。</p><table>'+body+'</table>',encoding='utf-8')
print('report written')
