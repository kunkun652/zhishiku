# 航空 CAE 知识工作台（本地演示）

这是 `实施方案.md` 的本地可运行实现。`D:\知识库`、用户指定的两个 D 盘 BDF 和 `D:\demo3\frame.STEP` 均只读；数据库、版本化副本、派生网格、运行状态和证据都保存在 `D:\zhishiku`。现有 `D:\CAE-AGENT-DSH` / `D:\CAE-AGENT-PI` 与全局模型配置没有被修改。

## 启动、打开与停止

```powershell
& 'D:\zhishiku\启动知识库.ps1'
```

- 知识工作台：<http://127.0.0.1:8765>
- 健康状态：<http://127.0.0.1:8765/api/health>
- DSH 监听地址：`127.0.0.1:3088`，未认证访问返回 401 是预期鉴权行为。

`启动知识库.ps1` 会自动启动或复用本项目复制版 CAE 客户端，并按其 PID 动态发现本次 API 端口。需要单独补启客户端时也可运行：

```powershell
& 'D:\zhishiku\启动CAE客户端.ps1'
```

不要把裸 `3088` 地址当作登录入口。知识工作台的“DSH 智能助手”页已经嵌入完整的原生 DSH Web；也可运行：

```powershell
& 'D:\zhishiku\打开DSH.ps1'
```

脚本会打开工作台内的助手页。知识服务仅在受控 iframe 导航时把内存中的一次性启动地址交给浏览器，由原生 DSH 换取签名 Cookie；后续 HTTP/WebSocket 直连 `127.0.0.1:3088`。令牌不进入页面正文、JSON、日志或报告，也没有代理任意地址或降低鉴权。停止：

```powershell
& 'D:\zhishiku\停止知识库.ps1'
```

知识服务只托管一个 DSH 子进程，并只在该子进程环境中设置 `HOME`、`USERPROFILE`、`DSH_HOME`、只读权限和禁用遥测标志；父 PowerShell 环境不被改写。切换工作台页面或重新载入 iframe 不会重复启动 DSH。

## 当前数据与真实能力

当前 `/api/health` 为 130 个活动知识对象、11 个登记资产：

- 5 个相互独立的案例对象：DPW-W1 STEP 浏览、用户本地 frame STEP 浏览、pyNastran plate BDF/OP2、用户本地 wingbox BDF、用户本地 framedeck BDF。
- 3 个 Pazy PDF 可提取正文页段。
- 84 张术语卡、17 张材料卡、11 张网格策略卡、10 张工况卡；整行保存，不从相似案例补造空字段。
- 浏览器以本地 OCCT WASM 读取 STEP，以 pyNastran 1.4.1 处理 BDF 续行、隐式指数、坐标系和卡片；实体单元只提取拓扑唯一外表面，不做实体扇形伪三角化。
- plate：36 节点、25 单元，关联 OP2 Subcase 1 位移模；源单位未知。
- wingbox：2,675 节点、2,657 单元、2,464 个壳面、4,928 个渲染三角形和 193 个线单元。`D:\wingbox_stitched_together-000.bdf` 与权威源 SHA-256 相同，仅登记一次。
- framedeck：318,738 节点、889,052 个 CTETRA、635,318 个唯一边界面/渲染三角形；无登记结果。

wingbox 与 framedeck 都是有限元 BDF，不称为 CAD；两者的单位、材料/属性适用性、载荷/约束工程含义、求解配置、结果和独立验证均明确为“待确认”。`frame.STEP` 与 `framedeck.bdf` 仅文件名近似，当前关系为候选/待确认；五个案例不得拼接成虚假求解链。

## 检索、来源和任务包

- FTS5 查询会把用户文本拆成安全字面 token，`DPW-W1` 等带连字符输入不会成为 FTS 语法；无命中再走转义后的字面 `LIKE`。
- 对象详情展示正文、结构化字段、定位和版本历史。PDF 原件入口带 `#page=N`；中文文件名使用 RFC 5987 `filename*`。
- 图谱中的对象和资产节点均可读取；资产可查看版本、SHA-256 并打开登记副本。
- 资产当前版本与不可变 `asset_versions`、对象当前版本与不可变 `object_versions` 分开保存。同内容重导保持版本，源内容变化生成新版本并保留旧副本。
- `cae-task-package/2` 同时收集对象 `source_asset_id` 与案例 `data.asset_ids`，锁定对象版本/内容哈希和资产版本/SHA-256。
- 类型齐全不代表可执行。案例必须有经审核的材料/工况绑定、单位、受控求解配置和验证门；当前五个演示案例均保守返回 `executable=false`。

## DSH、MCP 与模型状态

3088 内嵌 DSH 的同一 Host 进程同时挂载两个 active integration：8 个知识 MCP 工具和 68 个 Viewer MCP 工具。知识端已完成带 `type=材料卡` 的真实筛选检索；Viewer 端已对动态发现的项目 CAE API 完成只读 `model_summary`。启动不硬编码历史端口，也不连接 `D:\CAE-AGENT-DSH` 原目录实例。DSH 使用项目级 `runtime/dsh-home`、本地复制运行包和项目 MCP patch。

“DSH 智能助手”不是简化卡片或外链替代页：原生会话列表、消息区、工作区、模型配置、CAE 模式和工具入口均在工作台内直接呈现。外层只统一标题、状态、间距和边框；DSH 自身会话数据与调用链未重写。

`kb_preview_asset` 对已登记 STEP/BDF/OP2 返回对应模型视图的本机直达 URL，例如 `mesh-wingbox` 进入 `/?asset=mesh-wingbox#models`；其他格式明确返回 `preview_supported=false`，同时保留只读 `file_url`，不会假装具有三维预览。

两个项目隔离 DSH HOME 的 `agent-presets.default` 均设为 `cae`，因此新建空白会话默认进入 CAE 模式；CAE preset、两个 CAE Skill、Viewer MCP 与知识 MCP 已在本地包/运行进程中核对。既有非空会话不会被强制改换 preset，这是 DSH 的会话隔离规则。

健康接口把模型状态分为：

- `unconfigured`：未配置；
- `configured_unverified`：已配置但没有真实调用证据；
- `call_passed`：真实模型调用通过。

当前为 `unconfigured`，因此 `connected=false`。这不是永久硬编码；只有带证据的真实调用才能进入 `call_passed`。本交付没有读取、复制或打印旧凭据，也没有把 MCP 调用冒充 DeepSeek 模型回答。

## 重新导入与验证

```powershell
$python = 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $python 'D:\zhishiku\scripts\import_data.py'
& $python 'D:\zhishiku\scripts\probe_semantica.py'
& $python 'D:\zhishiku\scripts\probe_mcp.py'
& $python 'D:\zhishiku\scripts\verify.py'
```

自动回归项数以 `artifacts/test-evidence.json` 为准。pyNastran 与 Semantica 依赖分开安装，因为前者要求 NumPy `<2`，后者要求 NumPy `>=2.0.2`。

## 证据入口

- `artifacts/test-evidence.json`：49 项自动回归。
- `artifacts/browser-acceptance.json`：浏览器真实交互、模型载入、来源和 DSH 入口检查。
- `artifacts/data-cleaning-report.json`、`source-inventory.csv`：范围、哈希、重复源与导入统计。
- `artifacts/mcp-probe.json`、`dsh-runtime-evidence.json`：MCP 和隔离运行时证据。
- `artifacts/embedded-dsh-mcp-evidence.json`：同一 3088 DSH 的 CAE 会话、双 MCP 子进程、工具数量、动态 CAE 端点和只读调用证据。
- `artifacts/semantica-probe.json`：Semantica 0.6.8 `GraphBuilder` 独立探针。
- `artifacts/implementation-handoff.md`：首轮独立验收缺陷的逐项修复交接。

## 仍未闭环

- DeepSeek 凭据未在隔离 DSH 中配置，真实模型回答未验收。
- Semantica 仍是独立探针，不是本数据库的实际导入、冲突检测或推理引擎。
- `D:\知识库` 仅做路径级只读全量盘点；结构化导入、哈希和解析只覆盖 11 个明确登记资产，不是全库治理完成。
- 未启用 embedding；中文检索是 FTS5 + 字面回退。
- STEP 可浏览但不是 B-Rep 编辑器；plate 只展示首个位移表/首时间步；wingbox/framedeck 无结果；frame STEP 与 framedeck 的关系待确认。
- 当前没有自动网格、求解、正式安装器、微调训练、工程审核、适航批准或发布闭环。
