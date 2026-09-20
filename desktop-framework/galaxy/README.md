# Galaxy View 三维图谱适配

复用 [Longwind1984/galaxy-view](https://github.com/Longwind1984/galaxy-view) 0.6.1 的 MIT 开源组件，固定提交 `b49b60cb04687783153f24ff7f9b0a0af59334af`。这是面向知衡的适配集成，不是 Obsidian 插件宿主；没有引入 Obsidian 的 Vault、笔记编辑器及插件市场。

使用原项目 AggregateRenderer、WorkerForceLayout、确定性初始位置、星空、节点着色器、辉光和聚合连线。Three.js 0.184.0 与其 OrbitControls 随组件独立打包，避免影响既有模型查看器的 Three.js 版本。许可证位于 `src/static/plugins/galaxy-view`。

## 使用

进入“知识图谱”后，图谱占满左侧导航以外的整个区域。右上角齿轮是折叠的设置入口：三维开关、自动旋转、星空、节点大小、连线亮度、辉光、斥力、距离、扁平程度、适应窗口和恢复默认。设置保存于当前本地站点的 localStorage；服务端口改变时浏览器会视为另一个站点。

三维左键旋转、右键平移、滚轮缩放、F 适应窗口；点击节点沿用原详情侧栏，双击打开原信息，Esc 关闭详情。二维开关复用原画布。星空是不可点击的装饰，真实节点与连接来自 `/api/graph?full=true`，不将装饰星点或推测关系写入数据库。状态、来源、关系依据仍由原详情接口展示。

## 重建

从仓库根目录执行：

```powershell
git clone https://github.com/Longwind1984/galaxy-view.git artifacts/galaxy-view-upstream
git -C artifacts/galaxy-view-upstream checkout b49b60cb04687783153f24ff7f9b0a0af59334af
npm --prefix artifacts/galaxy-view-upstream ci --ignore-scripts --no-audit --no-fund
node desktop-framework/galaxy/build.mjs
```

构建文件随本仓库保存，运行时不访问 CDN。现有 `build.ps1` 会将其一并打包。

## 本次验证

2026-09-21：正式库隔离快照 6,978 对象、2,391 连接；8 项原工作区测试通过。Edge 无头浏览器检查全高画布、默认收起、真实节点拾取、二维/三维切换时详情 DOM 保持一致、全部设置项、刷新保存、恢复默认、离页 Worker 释放与重入；未出现脚本或组件资源错误。截图在 `desktop-framework/evidence/galaxy-full.png` 和 `galaxy-detail.png`。这是浏览器视觉与行为检查，不等同于用户对桌面窗口的视觉验收。

浏览器检查脚本：`tests/check_galaxy.cjs`，需在 `artifacts/graph-tests` 安装 Playwright 并准备独立测试服务，默认读取 `evidence/galaxy-test-data/runtime.json`。
