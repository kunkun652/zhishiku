# 知识处理与 Agent 主链路（1.4）

基于 `main@1e2146d7d75b9a350e0cf8c310bffc0ad713f433` 增量接入，复用现有 SQLite、BGE-M3、混合检索和 Galaxy View。
代码提交不等于已经替换 Windows 正式 EXE、完成全库处理或通过真实模型验收。

## 实际代码调用链

```text
显式上传 / 已登记 file_id
→ 原件 SHA256、受管保存、解析、带位置的 chunks + FTS5
→ 隔离 knowledge-worker：Semantica 0.7.0 provider.generate_structured（本机 Ollama）
→ schema 与逐字引文校验 → Semantica GraphBuilder 实际返回值
→ Semantica ConflictDetector：潜在冲突提示，不自动解决
→ kp_candidates / kp_segments 检查点 → 人工采纳或拒绝
→ 现有 objects / versions / relations + kp_facts
→ 持久化索引刷新请求 → 现有 Semantica 派生图 / BGE-M3 v2 索引
→ /api/retrieve → 原 main.search(mode=hybrid, graph_backend=semantica)
→ EvidencePack（出处、哈希、版本、渠道、降级信息）
→ /api/agent/ask → 本机模型 → 引用校验 → 再核对来源 → 回答与审计记录
```

生产组合入口是 `app.service:app`，`desktop.py` 已改用此入口。
直接启动旧 `app.main:app` 仍只包含旧接口，不会安装新链路。
新页面 `/knowledge-pipeline` 从左侧“知识加工与问答”打开。
没有修改原三维图谱 JS、二维切换或节点详情组件；采纳后的关系写入同一张 relations 表。

## 覆盖范围与边界

* 只处理显式提交的文件，不扫描 `D:\知识库`，不把目录盘点写成全库治理完成。
* 支持有文本层的 PDF、DOCX、TXT、Markdown、CSV、JSON 和 BDF/NAS/DAT 原文。
  单文件 20 MiB、100 万正文字符、PDF 2000 页。超过限额明确失败，不截断后报成功。
  无 OCR；DOCX 页眉、批注、图片不解析；DOCX 用正文字符位置，不虚构页码。
* BDF 是**原文抽取入口**，不是完整 pyNastran 工况解释器。拒绝外部 INCLUDE。
  不推断实际激活的 LOAD/SPC、组合倍率、坐标变换、单位制或适用性。
* 实体名称、数值、单位、引文可逐字定位。引文存在不等于语义正确，必须人工审核。
  不生成 0.98、1.0 等未经校准的“真实性置信度”；候选 confidence 为 null。
* 采纳后仍为 `candidate`，不是 `reviewed` 或工程参数认证。数值材料属性映射到
  properties 并保留原始值、单位、引文；其他属性可在 kp_facts 与 original_record 查看。
* 潜在冲突只比较当前批次及本链路已采纳的 kp_facts，不覆盖全部旧库字段。
  按类型、名称、属性、单位、工况文本分组，不做跨单位自动换算或实体自动合并。
  采纳时还会安全复查新出现的数值差异，避免先后审核漏掉已知冲突。
  同名可能是不同工程对象，因此这些只是待核实提示。确认后仍为 conflict，对 Agent 默认排除。
* Agent 为固定“检索—证据核验—回答”工作流，没有任意 SQL、Shell、求解器或知识写入工具。
  不执行 CAE、不自动解决冲突、不微调模型。答案引用校验不等于自动证明结论成立。
* 原文已经可以经关键词检索查看；提取出来的实体与关系未经审核不会进入对象主库。
  同一文件跨片段的实体不自动合并；当前版没有自动领域本体对齐。

## Windows 隔离启用

先检出功能分支，然后使用真实 Python 路径。示例创建临时数据空间，不覆盖正式库。

```powershell
cd D:\zhishiku
$desktopPython = 'D:\知识库\work\rag-platform\venv\Scripts\python.exe'
& $desktopPython -m pip install -r desktop-framework\requirements-pipeline.txt

# 单独 Semantica 环境，不与旧图谱 0.6.8 / 桌面 / BGE-M3 环境混装。
py -3.11 -m venv desktop-framework\.venv-knowledge
$knowledgePython = "$PWD\desktop-framework\.venv-knowledge\Scripts\python.exe"
& $knowledgePython -m pip install -r desktop-framework\requirements-knowledge-worker.txt

$env:ZH_PIPELINE_PYTHON = $knowledgePython
$env:ZH_PIPELINE_MODEL = '替换为 ollama list 中已经下载的本地模型名称'
$env:ZH_PIPELINE_OLLAMA_URL = 'http://127.0.0.1:11434'
$env:ZH_DATA_ROOT = "$env:TEMP\zhiheng-pipeline-$([guid]::NewGuid())"
& $desktopPython desktop-framework\src\desktop.py --server-only
```

需要已运行的本机 Ollama 和可用模型；程序不自动下载模型，仅向配置的本机服务发送请求。
请选择能稳定生成 JSON、支持至少 32768 上下文的本地模型。远程/云模型配置被拒绝。
输入超过保守上下文预算时明确失败，可以减少 top_k；不会把截断输出当作完整处理。
原有 BGE-M3 与 Semantica 派生图运行时也必须齐备，否则显示降级或未就绪。
源码运行沿用 `ZH_EMBEDDING_PYTHON`、`ZH_EMBEDDING_MODEL` 和
`desktop-framework/semantic-dist/semantic-worker/semantic-worker.exe`。

页面操作：**检查知识模型 → 上传/登记原件 → 运行抽取 → 检查并采纳候选 → 检查索引 → 提问**。
模型探测有效期五分钟。模型未配置时只保留已解析资料，不伪装成抽取完成。
检查点可恢复；改模型配置后需要新处理版本，不混用不同模型的分段结果。
程序运行期间驱动待处理索引，退出后可以恢复；运行时缺失则明确 blocked，可手动重试。
原件和正文的哈希或质量标记变化时，旧候选不能采纳，旧出处不能继续支撑答案。

## 构建与保护

```powershell
.\desktop-framework\build-knowledge.ps1 -Python $knowledgePython -DistPath "$PWD\desktop-framework\knowledge-dist"
.\desktop-framework\build.ps1 -BuildPython $desktopPython -DistPath "$PWD\desktop-framework\release-candidate"
```

默认构建目标改为 release-candidate，发现业务数据库时拒绝覆盖。
新增 knowledge-runtime 不替换旧 semantic-runtime；原 BGE-M3 代码不变。
Semantica 源提交固定；构建时用 pip freeze 保存解析后的依赖清单到本地 evidence。
这不代表已在 Windows 打包验证。正式部署前请备份原 EXE、数据库及受管原件。
本补丁不改本机快捷方式、不更新正式 EXE、不上传知识原件和模型权重到 GitHub。

## 主要接口

| 接口 | 功能 |
|---|---|
| POST /api/pipeline/upload | multipart 上传并登记解析结果 |
| POST /api/pipeline/files/{file_id} | 已登记受管资产进入处理流程 |
| POST /api/pipeline/jobs/{id}/run | 开始或恢复抽取，返回 202 |
| GET /api/pipeline/jobs/{id} | 状态、出处、候选与错误 |
| POST /api/pipeline/jobs/{id}/review | accept/reject、reviewer、note；可明确 acknowledge_conflicts |
| POST /api/pipeline/indexes/refresh | 刷新真实派生图和 v2 向量 |
| POST /api/retrieve | query、filters、top_k（1–20）→ EvidencePack |
| POST /api/agent/ask | 统一检索 → 带引用答案或明确缺口 |
| GET /api/agent/runs/{id} | 审计回放，不再次生成 |

health 区分 `agent_path_wired`（代码连接）与 `agent_connected`（最近真实探测成功）。
图谱/向量失败的关键词回退不会被描述为三路全部成功。旧 `/api/answer` 保留原摘录行为。

## 验证方式

新增 38 项处理/检索合同测试、5 项生产 HTTP 集成测试，以及原有 13 项框架回归。
测试直接使用项目 SQLite、FTS5、模板校验、检索代码；生成模型是明确标记的测试替身。
CI 不下载模型，因此 CI 通过不能证明真实 Semantica、BGE、Ollama 或 Windows EXE 已验收。
每个测试文件独立进程、强制临时数据目录，不能将测试空间指向业务数据。

```powershell
& $desktopPython desktop-framework\tests\test_knowledge_pipeline.py
& $desktopPython desktop-framework\tests\test_pipeline_main_integration.py
& $desktopPython desktop-framework\tests\test_framework.py
```

运行时齐备后，再执行严格真实验收：

```powershell
& $desktopPython desktop-framework\tests\probe_pipeline_live.py --out "$env:TEMP\pipeline-live-$([guid]::NewGuid()).json"
```

严格脚本使用合成资料与临时库，实际调用 Semantica 抽取、GraphBuilder、ConflictDetector、
BGE-M3、派生图、问答模型，要求三种实际命中渠道、真实图谱后端和带引用答案。
模型缺失、空关系、索引未就绪、图谱回退均失败，不以 mock 或跳过充当通过。
该验收仍不等于全库治理完成或航空工程正确性证明。
