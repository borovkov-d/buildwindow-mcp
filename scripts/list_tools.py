"""Prove both MCP connections (buildwindow, openweather) answer tool
discovery with zero live weather calls -- list_tools() (the MCP
`initialize` + tool-listing handshake) never touches the OpenWeather
HTTP API at all; only call_tool("weather", ...) does. See
docs/demo-checklist.md step 4c for how this differs from replay mode's
own discovery output (which never even connects openweather).

Run with:
    uv run python scripts/list_tools.py
"""

from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from agent.main import PROJECT_ROOT, _load_mcp_servers


async def _list_tools(name: str, config: dict) -> None:
    env = dict(os.environ)
    for key, value in (config.get("env") or {}).items():
        env[key] = os.path.expandvars(value)
    params = StdioServerParameters(
        command=config["command"],
        args=config.get("args", []),
        env=env,
        cwd=str(PROJECT_ROOT),
    )
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            print(name, [tool.name for tool in tools.tools])


async def main() -> None:
    load_dotenv()
    servers = _load_mcp_servers()
    await _list_tools("buildwindow", servers["buildwindow"])
    await _list_tools("openweather", servers["openweather"])


if __name__ == "__main__":
    asyncio.run(main())
