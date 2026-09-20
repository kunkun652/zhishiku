# Semantica 集成核对与试验

核对日期：2026-09-20。

## 结论

现有 `release/知衡仿真知识库/知衡仿真知识库.exe` 已部分集成 Semantica 0.6.8，通过配套 `semantic-runtime/semantic-worker.exe` 执行 GraphBuilder。不是完整 Semantica 平台集成，也不是 Palantir 官方产品。

目标 EXE SHA-256：`00a64b598f3553e2c58d80f4b3691912d6faf204bf73270f3db85d73161cd098`。

GitHub 源码已下载至 `D:/zhishiku/semantica`，上游 https://github.com/semantica-agi/semantica ，版本 0.7.0，提交 `92c2578a142a3b1e6139e6ea69fea39601a212e6`。本轮未替换正式 EXE 或业务数据库。

## 实际验证

使用目标 EXE 的 `--server-only` 模式和独立 `ZH_DATA_ROOT`，建立两个合成对象及一条有依据的关系，调用 `/api/semantica/rebuild` 成功。主库增加对象后，health 中派生图状态变为 stale，再次重建恢复成功。

将同一份输入交给 GitHub 0.7.0 源码与现有 `src/semantic_worker.py`，输出 entities、relationships 与打包组件完全相同。新版测试复用了现有隔离依赖目录，仅证明本次 GraphBuilder 接口兼容，不代表全部依赖或模块兼容。测试没有进行浏览器视觉验收。

可复跑脚本：`tests/probe_semantica_github.py`。本次证据：`evidence/semantica-github-20260920-101626/result.json`，同目录保留输入、派生图、日志和隔离数据库。测试结束已关闭本次启动的 EXE。

## 当前融合方式与下一步

当前链路：结构化 SQLite 主库 → EXE 的重建 API → 独立 Semantica worker → graph-derived.json。对象版本、哈希、关系依据和过期标记通过适配器保留；Semantica 不代替参数主库。前端已有“知识图谱 → Semantica 重建”按钮。

当前未接入 Semantica 自动实体抽取、向量语义检索、推理或 Agent 决策。已有检索与关系展示不能因此宣称由 Semantica 驱动。

建议继续保留独立 worker：桌面模型解析和 Semantica 的 NumPy 依赖存在版本边界。升级时先在独立构建目录打包 0.7.0，并把固定的引擎版本状态改为实际组件版本，再复测目标打包件。

有价值的下一步是让检索结果按有依据的关系补充关联卡片和来源，并明确展示哪些结果来自图谱；随后再为原文抽取增加候选对象与人工确认流程。不能直接把自动抽取的参数写成已复核材料卡，也不应自动合并工程上含义不同的同名对象。
