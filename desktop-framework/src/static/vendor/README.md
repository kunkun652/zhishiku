# 本地三维与图谱依赖

- Three.js 0.180.0：three.module.min.js、three.core.min.js、OrbitControls.js，MIT。
- occt-import-js 0.0.23：OpenCascade 的 WASM 导入器，随目录保留上游许可。
- D3 7.9.0：力导向布局、缩放与拖动，ISC。

来源为 npm 官方注册表；锁定版本记录在 `desktop-framework/tools/frontend/package-lock.json`。
新电脑运行 `desktop-framework/setup-dev.ps1` 自动准备；可用 `node desktop-framework/scripts/prepare-assets.mjs --check` 对照已安装的锁定包校验。资源与许可证自动复制，本目录生成文件不提交 Git。
运行时仅从当前平台的 /static/vendor 加载，无 CDN 请求。
模型通过本机 API 读取，CAD 在 Worker 中转换；关闭视窗时终止 Worker 并释放 WebGL 资源。

上游接口参考：
- https://github.com/kovacsv/occt-import-js/blob/main/README.md
- https://threejs.org/docs/pages/OrbitControls.html
