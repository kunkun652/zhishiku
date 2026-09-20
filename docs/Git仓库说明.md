# z1 源码快照

此仓库在 D:\zhishiku 原工作目录建立。首次提交消息为 `z1`，保存当前自有源码、前端页面、测试、构建脚本、依赖清单及设计说明，不移动或删除本地文件。

## 范围

- `desktop-framework/`：当前知衡桌面应用。包含全量动态知识图谱、后台力导向布局、右侧原信息与关系查看。
- `app/`、`server/`、`scripts/`、`integrations/`：已有知识工作台和本地集成代码。
- `collection/`：采集、整理和入库脚本，保留来源策略配置。
- `docs/`、根目录文档：接口、设计、操作说明和历史验收记录。历史记录中的路径、数量和运行状态不代表新检出仓库的实时状态。

第三方目录、node_modules、Python 环境、运行时、模型权重、EXE、构建输出、原始资料、数据库、索引、缓存及运行日志均由根目录 `.gitignore` 排除。忽略仅影响 Git 跟踪，现有文件仍留在本机。此提交不是业务数据备份，也不是可直接分发的 EXE 安装包。

## 第三方依赖恢复

根目录 `package.json` / `package-lock.json` 锁定 Three.js 0.180.0 和 occt-import-js 0.0.23，可用 `npm ci` 恢复 node_modules。桌面图谱还使用 D3 7.9.0。前端 vendor 文件不随 Git 提交，启动前需根据以下位置恢复，发布时同时保留对应上游许可证：

- `app/vendor/`：Three.js 的 three.module.js、three.core.js、OrbitControls.js，及 occt-import-js 的 JS / WASM。此处 OrbitControls 的导入路径是 `/vendor/three.module.js`。
- `desktop-framework/src/static/vendor/three/`：three.module.min.js、three.core.min.js、OrbitControls.js；OrbitControls 保持 `from 'three'`，由页面 importmap 解析。
- `desktop-framework/src/static/vendor/occt/`：occt-import-js 的 JS / WASM / Worker。
- `desktop-framework/src/static/vendor/d3/d3.min.js`：D3 7.9.0 的发行文件。

Python 依赖分别见根目录 requirements 文件、collection/requirements-lock.txt 和 desktop-framework/requirements-embedding-lock.txt。已有构建脚本引用本机 Python 和运行时路径，迁移机器时需要配置这些路径；本次提交不修改构建流程，不宣称全新机器可直接重建。

当前正式程序仍位于 `desktop-framework/release/知衡仿真知识库/知衡仿真知识库.exe`，由 Git 忽略。知识库原件与索引需单独备份。
