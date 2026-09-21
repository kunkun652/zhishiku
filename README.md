# 知衡仿真知识库

一个面向航空 CAE 工作的本地知识平台。

它把技术资料、知识卡片、模型、仿真案例和它们之间的关系放在同一个工作空间里，帮助工程人员更快地找资料、看懂依据，并为后续仿真任务准备可追溯的知识。

## 能做什么

- 检索原始资料和正文，结果可以返回原文件与来源位置。
- 管理材料、术语、网格策略和工况等结构化知识卡片。
- 查看 STEP、BDF 等模型资料及其登记信息。
- 用二维知识图谱浏览关系，也可切换 Galaxy View 三维星系图谱。
- 将任务所需的对象、版本、来源和缺口整理成任务知识包。
- 明确区分候选知识、自动检查、人工工程复核、发布和批准。

## 适合谁

适合需要管理 CAE 资料、模型、方法、案例和知识关联的个人或团队，尤其适用于航空结构仿真知识的本地整理与检索。

## 项目组成

- [`desktop-framework`](desktop-framework/)：桌面知识库程序、二维/三维图谱、模型查看、构建脚本和测试。
- [`collection`](collection/)：公开资料采集、正文提取、分类、知识卡片构建和入库流程。
- [`docs`](docs/)：来源与第三方依赖说明。
- [`scripts`](scripts/)：当前构建或数据检查所需的辅助脚本。

## 使用说明

### 没有 EXE？从源码启动（Windows）

先安装 **Python 3.11 x64、Node.js 22/24（含 npm）、Microsoft Edge WebView2 Runtime**。下载并解压仓库，在包含本 README 的目录中打开 PowerShell：

```powershell
# 首次安装：独立 Python 环境 + 固定版本前端资源 + 基础自检
powershell -NoProfile -ExecutionPolicy Bypass -File .\desktop-framework\setup-dev.ps1

# 每次启动：打开知衡桌面窗口，关闭窗口即可退出
powershell -NoProfile -ExecutionPolicy Bypass -File .\desktop-framework\start-dev.ps1
```

完整操作、软件下载入口、数据目录、模型配置和故障排查见 **[开发者安装与启动说明](desktop-framework/DEVELOPING.md)**。首次是空白知识库；基础安装不下载向量/LLM 权重，不包含作者的资料。可选 AI 组件需另外配置，不影响先启动基础桌面。

完整功能手册：[`知衡知识库 EXE 功能与 Agent 仿真使用指南`](知衡知识库EXE功能与Agent仿真使用指南.md)。按每个界面模块说明用途、操作方式、对人的帮助、对仿真 Agent 的帮助，以及引用、权限和增量更新的实际边界。

本仓库目前提供源码，不包含知识库业务数据、模型权重、原始资料或已经打包的 Windows 程序。开发和构建说明见 [`desktop-framework/README.md`](desktop-framework/README.md)，采集与入库格式见 [`collection/接口与数据说明.md`](collection/接口与数据说明.md)。

知识图谱展示的是已登记关系，相似检索表示内容相关程度；两者都不自动代表工程适用性、求解正确性或适航批准。
