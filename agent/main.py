"""BuildWindow agent: fetches and normalizes a real weather forecast for a
city (via a direct, deterministic MCP client call to the OpenWeather MCP
server -- not via the LLM), then asks the model to plan a week of
construction work against it using the BuildWindow MCP server.

The LLM session connects to BOTH MCP servers -- "buildwindow" and
"openweather" -- so that both are visible via get_mcp_status() discovery,
but the model is both instructed and structurally blocked
(disallowed_tools) from ever calling the weather tool itself: the
forecast is always fetched and normalized by this module's own direct
client call beforehand, never by the model.

Run with:
    uv run python -m agent.main
    uv run python -m agent.main "Kyiv"
    uv run python -m agent.main "Kyiv" '[{"work_code": "excavation", ...}]'

Requires OWM_API_KEY in the environment (or a .env file) and the
mcp-openweather binary reachable via the "command" in mcp_config.json --
see README.md for build/setup instructions (including the
MCP_OPENWEATHER_PATH environment variable, an alternative to putting the
binary on PATH). Without a usable forecast (missing key, invalid key,
unrecognized city, or the binary being unreachable -- see
agent/normalize.py for why this tool can't tell those apart), this
program reports that plainly and exits before ever starting an LLM
session; it never fabricates a schedule.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from agent.normalize import normalize_forecast

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MCP_CONFIG_PATH = Path(__file__).resolve().parent / "mcp_config.json"

SYSTEM_PROMPT = """You are BuildWindow's construction scheduling assistant.

You have two MCP connections: a "buildwindow" server with four
deterministic construction-planning tools, and an "openweather" server.
The openweather connection is visible to you, but you must NEVER call its
weather tool yourself -- any attempt is blocked. The weather forecast for
the requested city has already been fetched and aggregated into daily
figures by the surrounding program, and is given to you directly in the
user message below.

Hard rules:
- Weather suitability verdicts and the final schedule come EXCLUSIVELY
  from the buildwindow tools (validate_work_window / plan_work_schedule /
  estimate_curing_time). You never judge, by your own reasoning, whether a
  temperature or wind speed is acceptable for a work type -- always call a
  buildwindow tool and report exactly what it returns.
- Every work that gets rescheduled, delayed, or marked unschedulable must
  be explained by citing the exact constraint and value from the tool
  response that caused it (e.g. "wind 17 m/s exceeds the 15 m/s limit"),
  not a vague summary.

Procedure:
1. Call plan_work_schedule with the requested works and the supplied daily
   forecast.
2. For every work reported unschedulable with reason no_suitable_window,
   call validate_work_window for that same work against the first day of
   the supplied forecast, so you can hand the engineer the specific
   breached constraint and its numbers, not just the reason code.
3. For every scheduled work whose type has a curing stage (check with
   lookup_work_requirements if unsure -- base_curing_hours is not null),
   call estimate_curing_time using the daily temperatures for the days it
   occupies, so you can report when it will actually be ready, not just
   when construction activity finishes.
4. Report: the schedule, every rescheduled/unschedulable work with its
   specific cited reason (including the validate_work_window detail from
   step 2 where applicable), and curing-adjusted readiness dates.
"""

# Demo input (spec section 13.2 step 1) -- swap the city and/or works for
# a different run, or pass them as command-line arguments.
DEMO_CITY = "Kyiv"
DEMO_WORKS = [
    {"work_code": "excavation", "duration_days": 1, "depends_on": []},
    {
        "work_code": "concrete_pour",
        "duration_days": 2,
        "depends_on": ["excavation"],
    },
    {
        "work_code": "concrete_finishing",
        "duration_days": 1,
        "depends_on": ["concrete_pour"],
    },
]


# Fallback when a "${VAR}" command placeholder's environment variable is
# unset: rely on PATH instead, rather than fail outright.
_OPENWEATHER_COMMAND_FALLBACK = "mcp-openweather"


def _resolve_command(command: str) -> str:
    """Resolve a "${VAR}" command placeholder from the environment,
    falling back to a bare command name (relying on PATH) if the variable
    is unset. A plain command with no placeholder is returned unchanged."""
    match = re.fullmatch(r"\$\{(\w+)\}", command)
    if match is None:
        return command
    return os.environ.get(match.group(1), _OPENWEATHER_COMMAND_FALLBACK)


def _load_mcp_servers() -> dict:
    """Load agent/mcp_config.json (the single source of truth for MCP
    server config), substitute ${VAR} placeholders in each server's env
    block from the current process environment, and resolve a ${VAR}
    command placeholder the same way (see _resolve_command)."""
    raw = json.loads(MCP_CONFIG_PATH.read_text(encoding="utf-8"))
    servers = raw["mcpServers"]
    for server in servers.values():
        server["command"] = _resolve_command(server["command"])
        env = server.get("env")
        if env:
            server["env"] = {
                key: os.path.expandvars(value) for key, value in env.items()
            }
    return servers


async def _fetch_daily_forecast(
    city: str, server_config: dict
) -> tuple[list[dict], str | None]:
    """Fetch and normalize a daily forecast for `city` from the openweather
    MCP server, called directly (not via the LLM) so the aggregation step
    is deterministic Python, not model reasoning.

    Returns (daily_forecast, failure_reason). `failure_reason` is None on
    success; `daily_forecast` is always [] whenever `failure_reason` is
    set.
    """
    env = dict(os.environ)
    for key, value in (server_config.get("env") or {}).items():
        env[key] = os.path.expandvars(value)

    params = StdioServerParameters(
        command=server_config["command"],
        args=server_config.get("args", []),
        env=env,
        cwd=str(PROJECT_ROOT),
    )

    try:
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(
                    "weather", {"city": city, "units": "c", "lang": "en"}
                )
    except Exception as exc:
        return [], f"could not connect to the weather server ({exc})"

    raw_text = "".join(block.text for block in result.content if hasattr(block, "text"))
    if result.is_error:
        return [], f"weather tool reported an error ({raw_text or 'no detail'})"

    daily = normalize_forecast(raw_text)
    if not daily:
        return [], (
            "the weather tool returned no usable forecast data for this "
            "city (through this upstream tool, a missing/invalid API key, "
            "an unrecognized city, and an unreachable provider are all "
            "indistinguishable -- none of them produce a distinct error)"
        )
    return daily, None


def _build_prompt(city: str, works: list[dict], forecast: list[dict]) -> str:
    return (
        f"Plan the following construction works in {city} using the "
        "buildwindow tools. The daily weather forecast (already fetched "
        "and aggregated from the raw provider data) is given below.\n\n"
        f"Works:\n{json.dumps(works, indent=2)}\n\n"
        f"Daily forecast:\n{json.dumps(forecast, indent=2)}\n"
    )


def _print_discovery(status: dict) -> None:
    print("--- MCP server discovery ---", file=sys.stderr)
    for server in status.get("mcpServers", []):
        if server["name"] not in ("buildwindow", "openweather"):
            continue  # skip unrelated servers configured elsewhere in this environment
        tool_names = [t["name"] for t in server.get("tools", [])]
        detail = f" (tools: {', '.join(tool_names)})" if tool_names else ""
        print(f"  {server['name']}: {server['status']}{detail}", file=sys.stderr)
    print("-----------------------------", file=sys.stderr)


async def run(city: str, works: list[dict]) -> None:
    servers = _load_mcp_servers()

    daily_forecast, failure = await _fetch_daily_forecast(city, servers["openweather"])
    if failure is not None:
        print(
            f"Forecast unavailable for '{city}' ({failure}). "
            "Scheduling requires a forecast; no schedule was produced.",
            file=sys.stderr,
        )
        return
    print(
        f"--- weather: fetched and normalized {len(daily_forecast)} day(s) "
        f"of forecast for '{city}' ---",
        file=sys.stderr,
    )

    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        mcp_servers={
            "buildwindow": servers["buildwindow"],
            "openweather": servers["openweather"],
        },
        disallowed_tools=["mcp__openweather__weather"],
        permission_mode="bypassPermissions",
        cwd=str(PROJECT_ROOT),
    )

    async with ClaudeSDKClient(options=options) as client:
        await client.query(_build_prompt(city, works, daily_forecast))
        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(block.text)
                    elif isinstance(block, ToolUseBlock):
                        print(
                            f"[tool call] {block.name}({json.dumps(block.input)})",
                            file=sys.stderr,
                        )
            elif isinstance(message, ResultMessage) and message.is_error:
                print(f"[agent error] {message.result}", file=sys.stderr)

        _print_discovery(await client.get_mcp_status())


def main() -> None:
    # The model's output may contain characters outside the console's
    # active codepage (observed: a Windows console on cp1251 crashing on
    # a plain Unicode hyphen). Never let output encoding crash the run.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    load_dotenv()
    city = sys.argv[1] if len(sys.argv) > 1 else DEMO_CITY
    works = json.loads(sys.argv[2]) if len(sys.argv) > 2 else DEMO_WORKS
    asyncio.run(run(city, works))


if __name__ == "__main__":
    main()
