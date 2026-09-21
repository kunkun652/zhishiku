# 知识处理 → 混合检索 → 只读 Agent

## 本次改动的范围

在原项目上新增正式业务链路，不替换现有 FTS5、BGE-M3、v2 分片索引、三维图谱或 SQLite 参数主库。

原件登记/已有 file_id → 只读解析与 FTS5 → 独立 Semantica worker 实体/关系抽取 → 带原文位置的候选 → 人工采纳 → objects/versions/relations → Semantica 派生图与既有 BGE-M3 v2 索引 → 统一 EvidencePack → 本地 Ollama 只读问答。

打开原程序左下角“知识处理与问答”，依次执行登记、抽取、审核、更新索引、校验启用、提问。每阶段状态独立，组件缺失/索引未完成不显示为全链路就绪。新增上传并不会扫描 D:\知识库；只处理主动上传或选择的已登记资产。

**源码接通不等于你的 Windows EXE 已更新；本次没有读取或修改 D 盘业务资料，也没有安装模型。**

## 组件职责与边界

- `pipeline_parsers.py`：TXT/MD/BDF/NAS、文字型 PDF、DOCX 正文及顶层表格。20 MiB、400 万字符、4000 段上限，超限失败而非静默截断。扫描页、DOCX 未覆盖区域和 BDF INCLUDE 明确记为缺口。DOCX 不编造页码。
- `pipeline_extraction.py` + `knowledge_worker.py`：实际调用 Semantica `extract_entities_regex` 或 `extract_entities_llm`/`extract_relations_llm`，随后调用 GraphBuilder；不是自制正则冒充 Semantica。规则模式是有限 CAE 词表及显式带单位句式；本地大模型模式补充实体/关系候选。
- `pipeline_store.py`：任务、原文定位、候选、审核、冲突和版本事务。重复相同原件/配置处理幂等；采纳前验证原件与片段哈希。撤销只停用本流程创建且未被再次编辑的对象。
- `pipeline_agent.py`：统一调用现有三路检索，返回对象版本、源文件 SHA-256、片段、来源位置、关系与差异。只读问答调用真实本地模型；无模型只返回证据；虚构证据 ID/不属于原文的引用会使生成回答失败。
- `pipeline_api.py`：接口及图谱/v2 向量索引更新。图谱内容逐字段对照主库，向量索引完整一致后才能启用。未启用或失败的向量通路继续明确报告降级。

原文采纳仅是**来源级复核**，objects 仍保持 candidate；不是工程批准，置信概率没有校准，不填 0.98/1.0。`7075-T6` 不自动等同于所有“铝合金”。数值差异检查仅覆盖同一任务、同一来源的显式“主体的载荷/弹性模量/位移为数值单位”语句，统一 N/kN、Pa/MPa/GPa、m/mm 后比较。条件未明的差异是 scope_review，不自动判定工程矛盾；量纲错误不能用备注绕过。尚无跨库实体消歧或全工况冲突引擎。

BDF/NAS 首版**不解析数值字段、激活 LOAD/SPC 组合、坐标变换或单位制**。规则提及不等于当前子工况实际载荷。没有 CAE 求解器执行、仿真验收或大模型微调闭环。Agent 的逐字引用检查不证明回答在逻辑上被引文充分支持，仍应核查模型解读。

## 源码启动（先用隔离空间）

应用环境沿用现有桌面环境；Semantica 必须放在独立 Python 环境，避免既有 CAD/网格的 NumPy 依赖被升级。以下命令在仓库根目录运行；`$appPython` 改为实际已有桌面 Python。

```powershell
$appPython = 'D:\知识库\work\rag-platform\venv\Scripts\python.exe'
& $appPython -m pip install -r .\desktop-framework\requirements-pipeline-app.txt
python -m venv .\desktop-framework\knowledge-venv
$workerPython = (Resolve-Path .\desktop-framework\knowledge-venv\Scripts\python.exe).Path
& $workerPython -m pip install -r .\desktop-framework\requirements-knowledge.txt
$env:ZH_SEMANTICA_PYTHON = $workerPython
$env:ZH_DATA_ROOT = Join-Path $PWD 'desktop-framework\data-pipeline-trial'
$env:ZH_OLLAMA_URL = 'http://127.0.0.1:11434'
$env:ZH_LLM_MODEL = '填写本机 ollama list 中已有的模型名'
& $appPython .\desktop-framework\src\desktop.py
```

上述过程不下载问答模型。必须先由用户配置并启动本机 Ollama；只允许回环 HTTP 地址，不提供外部云端接口。源码环境已有 BGE-M3 worker 时沿用 `ZH_EMBEDDING_PYTHON` 与 `ZH_EMBEDDING_MODEL` 配置，不重新下载或替换模型。未配置时检索明确降级。

新的入口是 `app.pipeline_app:app`，`desktop.py` 已切换；直接运行旧 `app.main:app` 不会安装新增路由。兼容保留的旧 `/api/health` 仍含旧 Agent 标志；新增链路以 `/api/pipeline/status?probe=true` 和 `/api/pipeline/indexes` 为准，不把旧页面文字当成模型连接证据。

## Windows 打包

```powershell
.\desktop-framework\build-knowledge.ps1 -Python python -InstallDependencies
.\desktop-framework\build.ps1 -BuildPython $appPython -DistPath .\desktop-framework\release-pipeline-candidate
```

新增 worker 独立放在 `knowledge-runtime/knowledge-worker.exe`；原 `semantic-runtime` 保留。默认输出改为候选目录，并拒绝在包含 `data/knowledge.sqlite3` 的目录内重打包。更新正式程序前先使用程序备份，完成隔离验收，再按现有交付流程替换程序资源，不能把候选测试数据覆盖进真实数据库。

`requirements-knowledge.txt` 固定 Semantica 源码提交 `92c2578a142a3b1e6139e6ea69fea39601a212e6`，不是全部传递依赖的 lockfile。打包脚本先执行真实 Semantica regex API 自检；依赖或接口失败会停止。此脚本尚未在用户 Windows 环境执行。

## 验收与事实记录

```powershell
& $appPython -m unittest discover -s desktop-framework/tests -p test_knowledge_pipeline.py -v
& $appPython desktop-framework/tests/probe_knowledge_pipeline.py --out D:\zhishiku-probe-new
```

第一条是 **35 项聚焦测试**：真实 SQLite/FTS5、解析与审核、哈希/版本守卫、引用校验、API 错误语义；外部抽取与问答由显式 `TEST-FIXTURE` 替身提供。不是既有全部测试套件，也不是实际 Semantica/模型/Windows 验收。本次环境执行通过，Python 编译与新增 JS 语法检查通过。

第二条是**真实组件端到端探针**：要求全量源码及已配置的 Semantica、BGE-M3 和本地模型。`--out` 必须不存在；只写新隔离库和合成资料，不接触业务库。检查真实抽取、候选采纳、派生图内容、完整向量索引激活、三路调用记录和模型回答引用，任一步不可用都以非零退出并写 `result.json`，不会以替身冒充通过。本次未在具备这些组件的环境执行，所以不宣称真实模型全链路验收通过。

尚未完成：本地 Windows EXE 构建/部署、浏览器视觉回归、真实模型推理验收、全库资料治理及工程领域召回质量评测。原有程序界面和三维图谱代码未改。

## 新接口

| 接口 | 用途 |
|---|---|
| `GET /api/pipeline/status?probe=true` | 实际探测抽取、问答、embedding 组件 |
| `POST /api/pipeline/upload` | 受限格式原件登记，内容哈希去重 |
| `GET /api/pipeline/files` | 分页选择既有受管文件 |
| `POST /api/pipeline/jobs` | `{file_id, mode: regex或llm}`，不接受任意路径 |
| `GET /api/pipeline/jobs/{id}` | 持久化处理进度与缺口 |
| `GET /api/pipeline/candidates` | 候选、位置和数值差异 |
| `POST /api/pipeline/review` | `{ids,action,reviewer,note,conflict_note}` |
| `POST /api/pipeline/indexes/refresh` | 重建图谱、续建既有 v2 向量 |
| `GET /api/pipeline/indexes` | 查看索引状态 |
| `POST /api/pipeline/indexes/activate` | 一致性通过后切换索引 |
| `POST /api/retrieve` | `{query,filters,top_k}`，统一证据包 |
| `POST /api/agent/ask` | 相同请求结构，真实模型只读问答 |
| `GET /api/agent/runs/{id}` | 审计问答证据及结果 |

所有新增数据库表使用 `pipeline_` 前缀，不删除或重写既有表。源码回滚不等于撤销已采纳的数据；撤销使用审核入口，完整恢复使用此前备份，避免直接删除审核表造成来源链丢失。
