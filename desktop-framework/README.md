# 知衡仿真知识库桌面程序

当前界面：工作台 1.6。源码与打包 EXE 使用同一桌面入口；GitHub 不包含业务资料、模型权重或已打包程序。

## 下载源码后如何启动

Windows 10/11 x64 安装 **Python 3.11 x64、Node.js 22/24（含 npm）、Microsoft Edge WebView2 Runtime**。在仓库根目录执行：

```powershell
# 首次安装
powershell -NoProfile -ExecutionPolicy Bypass -File .\desktop-framework\setup-dev.ps1

# 启动桌面
powershell -NoProfile -ExecutionPolicy Bypass -File .\desktop-framework\start-dev.ps1
```

下载 ZIP 的用户先完整解压。无需激活虚拟环境，也不要求存在作者的磁盘路径。

**逐步安装、依赖说明、可选 AI 组件、更新和故障排查：[DEVELOPING.md](DEVELOPING.md)。**

## 已有完整 EXE 程序包

保留完整程序目录后运行 `知衡仿真知识库.exe`，不要只复制单个 EXE。这个方式不需要安装开发环境。源码启动脚本不会更改已有正式 EXE 或其数据。

## 功能与边界

- 工作台：本地检索、可配置的带证据问答、远端资料使用许可。
- 原始资料：分类文件、全文查找、原文侧栏及阅读位置。
- 知识卡片：材料、术语、网格策略、工况。
- 模型资产、仿真案例、二维与 Galaxy View 三维知识图谱。
- 流程与能力：流程规则、Skill、Tool、验证基准。
- 运行与验证：任务、运行记录、缺口、训练/评测登记。
- 高级查看：原文片段与索引、任务知识包。
- 授权 Agent 后台资料处理、版本引用校验与增量更新机制；依赖相应可选运行时。

源码首次创建空库。没有配置向量模型、抽取模型或派生图组件时，不应把相关功能描述为已就绪。候选、工具运行成功、自动检查和工程审核是不同状态；本程序不代替求解器或工程批准。

详细用途、操作及对 Agent 的帮助见[完整功能手册](../知衡知识库EXE功能与Agent仿真使用指南.md)。接口及安全边界见[工作台与后台处理](工作台与后台处理.md)。

## 数据与日志

源码默认使用 `desktop-framework/data`，EXE 默认使用程序目录的 `data`；启动脚本支持 `-DataRoot` 或已有的 `ZH_DATA_ROOT`。原件在 `assets`，数据库为 `knowledge.sqlite3`，日志为 `desktop.log`。停止程序后再备份，不在运行时覆盖数据库。

## 依赖与维护

- `requirements-desktop.txt`：基础桌面直接依赖。
- `requirements-desktop-lock.txt`：已解析固定版本的完整 Python 运行依赖。
- `tools/frontend/package-lock.json`：固定版本与完整性信息的浏览器依赖。
- `setup-dev.ps1`：独立环境、资源准备、自检。
- `start-dev.ps1`：预检查后从源码启动；`-Check` 仅执行隔离自检。
- `scripts/prepare-assets.mjs`：准备或比对本地前端资源和许可证。
- `scripts/check-dev.py`：临时空库、认证与资源冒烟检查。

历史 `build*.ps1` 用于维护者的打包流程，部分仍有原构建环境约束，不是首次安装入口。请先按开发者指南运行源码。历史交付与验收文件用于追溯，不代表新电脑已经具备同样的数据、模型或运行环境。
