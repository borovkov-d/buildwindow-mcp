"""BuildWindow agent: connects to the OpenWeather MCP server and the
BuildWindow MCP server (agent/mcp_config.json), and asks the model to plan
a week of construction work against the real forecast.

Run with:
    uv run python -m agent.main
    uv run python -m agent.main "Kyiv"
    uv run python -m agent.main "Kyiv" '[{"work_code": "excavation", ...}]'

Requires OWM_API_KEY in the environment (or a .env file) and the
mcp-openweather binary reachable via the "command" in mcp_config.json —
see README.md for build/setup instructions. Without them, the
buildwindow connection still works; the openweather connection fails and
the agent reports that plainly instead of guessing at weather.
"""

from __future__ import annotations

import asyncio
import json
import os
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

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MCP_CONFIG_PATH = Path(__file__).resolve().parent / "mcp_config.json"

SYSTEM_PROMPT = """You are BuildWindow's construction scheduling assistant.

You have two MCP connections: a "weather" server that reports current
conditions and a 5-day forecast for a city, and a "buildwindow" server
with four deterministic construction-planning tools.

Hard rules:
- Weather suitability verdicts and the final schedule come EXCLUSIVELY
  from the buildwindow tools (validate_work_window / plan_work_schedule /
  estimate_curing_time). You never judge, by your own reasoning, whether a
  temperature or wind speed is acceptable for a work type -- always call a
  buildwindow tool and report exactly what it returns.
- If the weather tool fails or returns no usable forecast (an
  unrecognized city, a connection error, a missing API key), say so
  plainly and stop. Never invent or guess weather data, and never produce
  a schedule without a real forecast behind it.
- Every work that gets rescheduled, delayed, or marked unschedulable must
  be explained by citing the exact constraint and value from the tool
  response that caused it (e.g. "wind 17 m/s exceeds the 15 m/s limit"),
  not a vague summary.

Procedure:
1. Call the weather tool for the requested city to get the 5-day
   forecast. Its data arrives as 3-hour interval entries.
2. Aggregate those entries into one daily weather window per calendar
   date: temp_min_c = minimum temperature among that day's entries,
   temp_max_c = maximum temperature among that day's entries, wind_ms =
   maximum wind speed among that day's entries, humidity_pct = average
   humidity among that day's entries (rounded to the nearest whole
   percent), precipitation_mm = sum of precipitation among that day's
   entries. Do this for every date the forecast covers.
3. Call plan_work_schedule with the requested works and this daily
   forecast.
4. For every scheduled work whose type has a curing stage (check with
   lookup_work_requirements if unsure -- base_curing_hours is not null),
   call estimate_curing_time using the daily temperatures for the days it
   occupies, so you can report when it will actually be ready, not just
   when construction activity finishes.
5. Report: the schedule, every rescheduled/unschedulable work with its
   specific cited reason, and curing-adjusted readiness dates.
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


def _load_mcp_servers() -> dict:
    """Load agent/mcp_config.json (the single source of truth for MCP
    server config) and substitute ${VAR} placeholders in each server's
    env block from the current process environment."""
    raw = json.loads(MCP_CONFIG_PATH.read_text(encoding="utf-8"))
    servers = raw["mcpServers"]
    for server in servers.values():
        env = server.get("env")
        if env:
            server["env"] = {
                key: os.path.expandvars(value) for key, value in env.items()
            }
    return servers


def _build_prompt(city: str, works: list[dict]) -> str:
    return (
        f"Plan the following construction works in {city} using the real "
        "weather forecast and the buildwindow tools:\n\n"
        f"{json.dumps(works, indent=2)}\n"
    )


def _print_discovery(status: dict) -> None:
    print("--- MCP server discovery ---", file=sys.stderr)
    for server in status.get("mcpServers", []):
        if server["name"] not in ("buildwindow", "openweather"):
            continue  # skip unrelated servers configured elsewhere in this environment
        tool_names = [t["name"] for t in server.get("tools", [])]
        detail = ""
        if tool_names:
            detail = f" (tools: {', '.join(tool_names)})"
        elif server.get("error"):
            detail = f" ({server['error']})"
        print(f"  {server['name']}: {server['status']}{detail}", file=sys.stderr)
    print("-----------------------------", file=sys.stderr)


async def run(city: str, works: list[dict]) -> None:
    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        mcp_servers=_load_mcp_servers(),
        cwd=str(PROJECT_ROOT),
    )

    async with ClaudeSDKClient(options=options) as client:
        await client.query(_build_prompt(city, works))
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
    load_dotenv()
    city = sys.argv[1] if len(sys.argv) > 1 else DEMO_CITY
    works = json.loads(sys.argv[2]) if len(sys.argv) > 2 else DEMO_WORKS
    asyncio.run(run(city, works))


if __name__ == "__main__":
    main()
