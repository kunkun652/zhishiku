# API 与 MCP 契约

REST 仅绑定 loopback：

- `GET /api/health`：活动对象/资产统计及 DeepSeek 三态状态。
- `GET /api/search?q=&type=`：安全字面 FTS5 + 转义 LIKE 回退；返回对象版本、内容哈希、来源和 locator。
- `GET /api/objects/{id}`：完整正文、数据字段和版本历史。
- `GET /api/assets`、`GET /api/assets/{id}`：资产当前版本与历史。
- `GET /api/assets/{registered_id}/file?version=N`：只允许数据库登记副本；中文文件名用 RFC 5987；响应含 `X-Content-SHA256`。
- `GET /api/graph?seed={object_id}`：对象/资产节点和带 method/evidence/status 的关系。
- `GET /api/mesh/{plate|wingbox|framedeck}`；`GET /api/result/plate`。
- `POST /api/package`，JSON `{ "object_ids": [...] }`：`cae-task-package/2`，收集 `source_asset_id` 和 `data.asset_ids`，锁定对象版本/内容哈希与资产版本/SHA-256，保守返回 gaps/executable。
- `POST /api/dsh/open`：只接受知识工作台同源 Origin；触发本机 DSH 安全打开流程，不返回 launch token。

MCP stdio 位于 `integrations/dsh/kb_mcp_server.py`：

- `kb_search`
- `kb_get_object`
- `kb_neighbors`
- `kb_trace_sources`
- `kb_list_assets`
- `kb_preview_asset`
- `kb_build_package`
- `kb_report_gap`

MCP 搜索和任务包规则与 REST 对齐。DSH 中工具名形如 `mcp__cae_kb__kb_search`。

安全边界：不接受任意本地文件路径；正文只作为数据；没有导入写工具；凭据/launch token 不进入参数、响应、报告或 MCP；任务包 `executable=true` 必须通过显式执行就绪与经审核绑定检查。
