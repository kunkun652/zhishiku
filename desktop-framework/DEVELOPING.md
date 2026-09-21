# 开发者安装与源码启动（Windows）

本指南针对 GitHub 下载的源码，**不需要已有 EXE，也不需要作者电脑上的任何目录**。先运行基础桌面，再按需配置 AI 组件。

## 1. 新电脑准备

安装以下软件后重新打开 PowerShell：

| 软件 | 本安装流程要求 | 用途 |
| --- | --- | --- |
| Windows | Windows 10/11，64 位 | 当前开发者桌面支持范围；不承诺 macOS/Linux 桌面兼容 |
| [Python](https://www.python.org/downloads/windows/) | Python **3.11 x64**，包含 Python Launcher 和 pip | 桌面后端；安装时启用 launcher，建议勾选加入 PATH |
| [Node.js](https://nodejs.org/en/download) | 22 或 24，包含 npm | 安装时下载固定版本前端资源，程序运行时不依赖 Node 服务 |
| [Microsoft Edge WebView2 Runtime](https://developer.microsoft.com/en-us/microsoft-edge/webview2/) | Evergreen x64 | pywebview 的现代浏览器内核；已安装时不必重复安装 |
| [Git](https://git-scm.com/downloads/win) | 可选，克隆和更新源码时需要 | Download ZIP 用户可先不安装；可选 Semantica 安装需要 Git |

网络需能够访问 PyPI 和 npm 官方注册表；默认安装不下载业务资料、Embedding 权重或 LLM，不需要 API Key。Python 环境和前端依赖会占用额外磁盘空间。

先检查命令：

```powershell
py -3.11 --version
node --version
npm.cmd --version
```

基础桌面固定 Python 3.11，是为了使用已经验证的依赖组合；不要混用系统其他项目的 Python 环境。

## 2. 下载源码

有 Git：

```powershell
git clone https://github.com/kunkun652/zhishiku.git
cd zhishiku
```

也可以在 GitHub 点击 **Code → Download ZIP**，完整解压后，在包含根目录 `README.md` 和 `desktop-framework` 的文件夹中打开 PowerShell。文件夹可以放在其他磁盘，不要求叫 `D:\zhishiku`。不要直接在 ZIP 内启动。

## 3. 首次安装：一条命令准备环境和资源

在仓库根目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\desktop-framework\setup-dev.ps1
```

脚本依次完成：

1. 检查 Python 与 Node。
2. 在 `desktop-framework/.venv` 创建独立环境，不安装到全局或其他项目。
3. 按 `requirements-desktop-lock.txt` 安装完整固定版本依赖，并执行 `pip check`。
4. 在 `desktop-framework/tools/frontend` 执行 `npm ci --ignore-scripts`，使用锁文件下载 Three.js、D3、OCCT 及传递依赖。
5. 将明确列出的浏览器文件、WASM 和许可证复制到 `src/static/vendor`，按 SHA-256 与安装包比对。
6. 使用临时空数据库检查模块导入、静态文件、身份认证、页面和搜索接口；不打开或改变已有知识库。

下载失败可以修复网络后重跑。脚本不清空业务数据，不覆盖 EXE，不下载用户知识文件。它会重新准备指定的生成资源，因此不要直接修改 `static/vendor` 中的第三方文件。

如果没有 `py` 命令，但已安装正确 Python：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\desktop-framework\setup-dev.ps1 -Python "C:\你的Python目录\python.exe"
```

`ExecutionPolicy Bypass` 只针对这次 PowerShell 进程，不会永久修改机器策略；组织策略禁止脚本时，请联系管理员，不绕过组织管理。

## 4. 每次启动

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\desktop-framework\start-dev.ps1
```

启动后应出现“知衡 · 仿真知识库”桌面窗口。首次是自己的空白库，不包含作者的原件、卡片、模型或案例。关闭桌面窗口即可结束这次运行；不要对同一数据目录重复启动多个实例。

源码启动会自动使用仓库内虚拟环境，无需手动 activate。它通过正式桌面入口建立本机所有者会话；**不要双击 `index.html`，也不要只用裸 `uvicorn` 或 `--server-only` 后直接打开地址**，否则无法得到正常桌面认证流程。

只检查安装、不打开窗口：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\desktop-framework\start-dev.ps1 -Check
```

这个检查不等于 WebView2 原生窗口、真实 LLM、CAD 文件或仿真求解已经验收。

### 数据目录与日志

默认使用 `desktop-framework/data`；如果当前会话已有 `ZH_DATA_ROOT`，启动脚本会保留该设置。也可以明确指定独立目录：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\desktop-framework\start-dev.ps1 -DataRoot "D:\MyZhihengData"
```

这里保存 `knowledge.sqlite3`、`assets`、运行状态和日志。故障先看该目录的 `desktop.log`。不要指向另一实例正在使用的目录，更不要拿正式库测试开发代码。更新源码不应删除这些数据；源码仓库不是业务备份。

## 5. 初次进入后怎么使用

1. “工作台”可进行本地检索；空库没有命中是正常现象。
2. “模型设置”填写兼容 Chat Completions 的 URL、model 和 API Key，按服务能力配置思考参数，再测试连接。
3. 授权资料处理 Agent 后，可通过后台资料接口提交自己的文件；处理接口与凭据说明见[工作台与后台处理](工作台与后台处理.md)。不要把空模板当成已完成知识，也不要复制作者电脑路径。
4. “原始资料”用于查看分类文件和原文，其余模块分别保存卡片、模型、案例及运行依据。
5. 完整功能说明见[EXE 功能与 Agent 仿真使用指南](../知衡知识库EXE功能与Agent仿真使用指南.md)，基础源码版使用同一套界面与后端。

远端问答仍需全局许可和命中文件当前版本的使用许可；填写 Key 不代表允许上传资料。开发模式不关闭安全检查。

## 6. 基础依赖与可选 AI 组件

### 基础桌面：默认已经安装

直接依赖在 `requirements-desktop.txt`，完整传递依赖固定在 `requirements-desktop-lock.txt`。用途包括 FastAPI/Uvicorn 服务、pywebview 桌面、httpx 模型 HTTP 客户端、multipart 上传、pypdf/PyMuPDF 文档读取、pyNastran/meshio/NumPy 模型解析。

前端独立清单和完整性锁文件在 `tools/frontend/package.json` 与 `package-lock.json`。运行时全部从本机提供资源，不临时访问 CDN；Three.js 0.180.0、D3 7.9.0、occt-import-js 0.0.23。Galaxy View 的适配代码及许可证已在源码中。

基础安装支持桌面、管理、全文关键词检索、已登记关系浏览和工作台模型配置。它**不声称已启用完整向量检索、自动知识抽取或 Semantica 派生图**。缺少可选组件时，相关状态显示未安装、等待或降级；不能把“桌面启动成功”当作所有后台功能就绪。

### 本地 BGE-M3 向量检索（可选、独立环境）

历史完整版本清单见 `requirements-embedding-lock.txt`，其中 Torch 是 CUDA 12.4 构建，不适合不加判断地装入任意电脑。不要将它安装到基础桌面的 `.venv`，也不要因为没有 NVIDIA 显卡就修改主环境依赖。

需要在独立 Python 环境准备 NumPy、PyTorch、Transformers、tokenizers、sentencepiece 及模型下载依赖，按对应机器选择 CPU/CUDA 运行时，并准备完整 BGE-M3 权重。运行时要求：

- 模型：`BAAI/bge-m3`。
- 固定 revision：`5617a9f61b028005a4858fdac845db406aefb181`。
- 本地模型目录包含 tokenizer/config/权重，以及 `revision.json`，其中 `model` 和 `revision` 与上述值一致。只创建这个 JSON 不能代替真实权重。
- 配置 `ZH_EMBEDDING_PYTHON` 为独立环境的 Python 可执行文件，`ZH_EMBEDDING_MODEL` 为完整模型目录。

在同一 PowerShell 会话设置后启动：

```powershell
$env:ZH_EMBEDDING_PYTHON = "D:\你的独立环境\Scripts\python.exe"
$env:ZH_EMBEDDING_MODEL = "D:\你的模型目录\bge-m3"
powershell -NoProfile -ExecutionPolicy Bypass -File .\desktop-framework\start-dev.ps1
```

这部分是扩展运行契约，不是默认脚本已经替你下载和验证的模型。大文件下载、不同显卡运行时、向量构建与切换需单独验收。未安装时仍可先使用基础桌面。

### 本地知识抽取（可选、独立 Python 3.12 环境）

需要额外安装 Python 3.12 和 Git，并准备本机 Ollama 服务与已经下载的本地模型。依赖使用 `requirements-knowledge-worker.txt` 中固定的 Semantica Git 提交，不安装进桌面环境：

```powershell
py -3.12 -m venv .\desktop-framework\.venv-knowledge
.\desktop-framework\.venv-knowledge\Scripts\python.exe -m pip install -r .\desktop-framework\requirements-knowledge-worker.txt
$env:ZH_PIPELINE_PYTHON = (Resolve-Path .\desktop-framework\.venv-knowledge\Scripts\python.exe).Path
$env:ZH_PIPELINE_MODEL = "替换成你已下载的本地Ollama模型名"
$env:ZH_PIPELINE_OLLAMA_URL = "http://127.0.0.1:11434"
powershell -NoProfile -ExecutionPolicy Bypass -File .\desktop-framework\start-dev.ps1
```

该清单固定 Semantica 源版本，但不是所有传递依赖的跨平台锁定文件。独立环境仍需实际安装与探针验收；模型名必须真实存在，不能直接使用占位符。工作台问答 Key 不会自动用于全文抽取，未配置则保留 `waiting_model`。

Semantica 的知识抽取进程与派生图进程也是两个组件。源码当前派生图重建查找 `semantic-dist/semantic-worker/semantic-worker.exe`；仅安装上述 Python 包不会自动提供这个文件。现有 `build-semantic.ps1` 是历史打包流程，不能当作新电脑的一键安装入口。缺少派生图组件时使用主库登记关系，完整后台索引发布可能处于 blocked，不能称为全部完成。

## 7. 更新代码与重新准备

先关闭源码桌面，确认自己的修改已妥善保存，然后：

```powershell
git pull --ff-only
powershell -NoProfile -ExecutionPolicy Bypass -File .\desktop-framework\setup-dev.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\desktop-framework\start-dev.ps1
```

ZIP 下载用户建议解压到新目录安装，再通过明确的 `-DataRoot` 选择自己的数据；先备份，不在运行时覆盖数据库。不要使用强制重置来解决本地修改冲突。

## 8. 常见启动问题

| 现象 | 排查方法 |
| --- | --- |
| 找不到 Python / 版本不对 | 安装 Python 3.11 x64；执行 `py -3.11 --version`，或使用 `-Python` 指定路径 |
| 找不到 npm | 安装包含 npm 的 Node.js，重新打开 PowerShell；脚本使用 npm.cmd，避免 npm.ps1 策略问题 |
| pip/npm 下载失败 | 检查网络、代理和注册表访问；修复后重跑安装，不禁用 TLS 校验 |
| 窗口空白、3D 模块加载失败 | 重跑安装；运行 `node .\desktop-framework\scripts\prepare-assets.mjs --check` 核对资源 |
| 原生窗口不能打开 | 安装/修复 WebView2 Runtime，检查 desktop.log；`-Check` 通过不代表 WebView2 可用 |
| API 返回 401 | 从 start-dev.ps1 打开桌面；Agent 使用显式签发凭据，不直接打开无会话 API |
| 索引未安装 / 等待模型 | 默认没有配置可选 AI 组件；按第 6 节准备，不能用假状态消除提示 |
| 页面没有作者的知识数据 | 正常。源码发布不包含私有知识库，使用自己的明确授权资料 |

## 9. 验证范围

安装自检在临时数据空间运行，不访问正式 EXE 数据；验证 Python 导入、静态资源、数据库初始化、认证和基本 HTTP 路由。实际模型推理、首次全量向量构建、不同 GPU 与工程仿真结果不在基础启动验收范围内。

2026-09-21 验证：在本机创建仅包含待发布源码的独立目录（路径含空格，不带 `.venv`、`node_modules`、生成资源或业务数据），从零执行安装脚本成功；47 项 Python 运行依赖的 `pip check` 通过，12 个前端资源及许可证校验通过。另通过真实 WebView2 隐藏窗口加载正式源码入口，确认工作台、10 个导航入口及原始资料页加载成功。测试使用本机已有 Python、Node 和 WebView2，不等于在全新 Windows 虚拟机上完成系统安装验收。

维护者可在交互式 Windows 会话显式运行原生窗口冒烟测试（临时空库，自动关闭测试窗口）：

```powershell
.\desktop-framework\.venv\Scripts\python.exe .\desktop-framework\tests\smoke_source_window.py
```

不要把 `.venv`、`node_modules`、生成的 vendor 文件、业务 data、Key、模型权重或运行会话提交到 Git。发布源码时提交依赖清单、锁文件、准备脚本和说明即可。
