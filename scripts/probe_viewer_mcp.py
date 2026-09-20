from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / "runtime" / "cae-dsh-app" / "runtime" / "python" / "python.exe"
SERVER = ROOT / "runtime" / "cae-dsh-app" / "tools" / "cae_viewer_mcp" / "mcp_server.py"
OUT = ROOT / "artifacts" / "viewer-mcp-probe.json"


async def main() -> None:
    port = os.environ.get("CAE_AGENT_API_PORT", "60890")
    api_url = os.environ.get("CAE_AGENT_API_URL", "").strip().rstrip("/") or f"http://127.0.0.1:{port}"
    params = StdioServerParameters(
        command=str(PYTHON),
        args=[str(SERVER)],
        cwd=str(ROOT),
        env={**os.environ, "CAE_AGENT_API_URL": api_url, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            tools = await session.list_tools()
            summary = await session.call_tool("model_summary", {})
            output = {
                "server": {"name": init.serverInfo.name, "version": init.serverInfo.version},
                "api_url": api_url,
                "tool_count": len(tools.tools),
                "tool_names": [tool.name for tool in tools.tools],
                "read_only_call": "model_summary",
                "is_error": bool(summary.isError),
                "content": [item.model_dump() for item in summary.content],
                "scope": "只读状态探针；未导入模型、未运行求解器、未调用外部模型。",
            }
            OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"tool_count": output["tool_count"], "is_error": output["is_error"]}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
