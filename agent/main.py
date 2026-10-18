"""BuildWindow agent: fetches and normalizes a real weather forecast for a
city (via a direct, deterministic MCP client call to the OpenWeather MCP
server -- not via the LLM), then asks the model to plan weather-dependent
works against it using the BuildWindow MCP server. Which works exist, and
their weather limits, come from the server's dataset (the built-in
construction example, or a file named by BUILDWINDOW_DATASET -- the server
subprocess inherits this process's environment).

Two modes:
- **Live** (default): the model ALSO connects to the openweather server
  itself and may call its one `weather` tool for current-conditions
  color commentary -- the daily forecast that drives scheduling always
  comes from this module's own deterministic fetch+parse, never from the
  model's own call, so both servers are genuinely incorporated into the
  agent's own flow without weakening the parsing guarantee.
- **Replay/offline** (`--forecast-from-file`): both the daily forecast
  AND the current-conditions note come from the same recorded file, via
  the same deterministic parsers (`normalize_forecast`,
  `parse_current_conditions`); `openweather` is not connected at all in
  this mode, so the whole run needs no network access and no API key.

Run with:
    uv run python -m agent.main
    uv run python -m agent.main "Kyiv"
    uv run python -m agent.main "Kyiv" '[{"work_code": "excavation", ...}]'
    uv run python -m agent.main "Kyiv" --forecast-from-file fixtures/weather_kyiv.txt

Requires OWM_API_KEY in the environment (or a .env file) and the
mcp-openweather binary reachable via the "command" in mcp_config.json --
see README.md for build/setup instructions (including the
MCP_OPENWEATHER_PATH environment variable, an alternative to putting the
binary on PATH) -- for live mode only; --forecast-from-file needs
neither. Without a usable forecast (missing key, invalid key,
unrecognized city, or the binary being unreachable -- see
agent/normalize.py for why this tool can't tell those apart), this
program reports that plainly and exits before ever starting an LLM
session; it never fabricates a schedule.
"""

from __future__ import annotations

import argparse
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

from agent.normalize import normalize_forecast, parse_current_conditions

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MCP_CONFIG_PATH = Path(__file__).resolve().parent / "mcp_config.json"

_SHARED_HARD_RULES = """Hard rules:
- Weather suitability verdicts and the final schedule come EXCLUSIVELY
  from the buildwindow tools (validate_work_window / plan_work_schedule /
  estimate_curing_time), evaluated against the supplied daily forecast.
  You never judge, by your own reasoning, whether a temperature or wind
  speed is acceptable for a work type -- always call a buildwindow tool
  and report exactly what it returns.
- Every work that gets rescheduled, delayed, or marked unschedulable must
  be explained by citing the exact constraint and value from the tool
  response that caused it (e.g. "wind 17 m/s exceeds the 15 m/s limit"),
  not a vague summary."""

_SHARED_PROCEDURE_TAIL = """\
2. Call plan_work_schedule with the requested works and the supplied daily
   forecast.
3. For every work reported unschedulable with reason no_suitable_window,
   call validate_work_window for that same work against the first day of
   the supplied forecast, so you can hand the user the specific
   breached constraint and its numbers, not just the reason code.
4. For every scheduled work whose type has a curing stage (check with
   lookup_work_requirements if unsure -- base_curing_hours is not null),
   call estimate_curing_time using the daily temperatures for the days it
   occupies, so you can report when it will actually be ready, not just
   when the work itself finishes.
5. Report: the one-sentence current-conditions note from step 1, the
   schedule, every rescheduled/unschedulable work with its specific cited
   reason (including the validate_work_window detail from step 3 where
   applicable), and curing-adjusted readiness dates."""

# Live mode: the model genuinely connects to openweather and may call its
# "weather" tool itself (see run()'s allowed_tools/mcp_servers) -- the
# procedure and hard rules are unchanged from the version verified live in
# an earlier phase; only construction-specific wording was neutralized
# (phase 10), since the works now come from whatever dataset is loaded.
SYSTEM_PROMPT_LIVE = f"""You are BuildWindow's weather-window scheduling assistant.

You have two MCP connections: a "buildwindow" server with four
deterministic weather-window planning tools, and an "openweather" server
with one "weather" tool. You may call "weather" yourself, but ONLY for
the narrow purpose described in step 1 below -- the daily forecast that
drives all scheduling has already been fetched and aggregated into daily
figures by the surrounding program, and is given to you directly in the
user message below. That supplied daily forecast is the sole
authoritative source for scheduling; the weather tool's own result must
NEVER be used to build, validate, or influence the schedule, and never
overrides the supplied daily forecast.

{_SHARED_HARD_RULES}

Procedure:
1. Call the weather tool once for the requested city to get its CURRENT
   conditions. Use this only to write one descriptive sentence in your
   final report (city, current temperature, current conditions) -- purely
   informational color for the user, never an input to any scheduling
   decision.
{_SHARED_PROCEDURE_TAIL}
"""

# Offline/replay mode: openweather is not connected in this session at
# all (see run()) -- current conditions are supplied directly instead of
# fetched, and the model is told plainly there is no weather tool to call.
SYSTEM_PROMPT_OFFLINE = f"""You are BuildWindow's weather-window scheduling assistant.

You have one MCP connection: a "buildwindow" server with four
deterministic weather-window planning tools. There is no weather tool
connected in this session. The daily forecast that drives all scheduling,
and a current-conditions snapshot for the requested city, have both
already been fetched and are given to you directly in the user message
below. The supplied daily forecast is the sole authoritative source for
scheduling.

{_SHARED_HARD_RULES}

Procedure:
1. Current conditions for the requested city are already given directly
   in the user message below (city, temperature, conditions) -- use them
   only to write one descriptive sentence in your final report. Do NOT
   attempt to call a weather tool; none is connected in this session.
{_SHARED_PROCEDURE_TAIL}
"""

# Tried first, in place of permission_mode="bypassPermissions": an
# explicit allowlist naming exactly the tools a session should ever
# call. Confirmed live to be sufficient on its own in live mode (see
# DECISIONS.md). BUILDWINDOW_TOOLS is always allowed; OPENWEATHER_TOOL is
# added only in live mode (see run()) -- omitted entirely in offline mode
# so the model has no way to attempt a live call even if it tried.
BUILDWINDOW_TOOLS = [
    "mcp__buildwindow__lookup_work_requirements",
    "mcp__buildwindow__validate_work_window",
    "mcp__buildwindow__estimate_curing_time",
    "mcp__buildwindow__plan_work_schedule",
]
OPENWEATHER_TOOL = "mcp__openweather__weather"

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


async def _call_weather_tool_live(city: str, server_config: dict) -> str:
    """Call the openweather MCP server's `weather` tool directly and
    return its raw text response. Raises on any connection/protocol
    failure or a tool-reported error."""
    env = dict(os.environ)
    for key, value in (server_config.get("env") or {}).items():
        env[key] = os.path.expandvars(value)

    params = StdioServerParameters(
        command=server_config["command"],
        args=server_config.get("args", []),
        env=env,
        cwd=str(PROJECT_ROOT),
    )

    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(
                "weather", {"city": city, "units": "c", "lang": "en"}
            )

    raw_text = "".join(block.text for block in result.content if hasattr(block, "text"))
    if result.is_error:
        raise RuntimeError(
            f"weather tool reported an error ({raw_text or 'no detail'})"
        )
    return raw_text


async def _get_raw_weather_text(
    city: str, server_config: dict, forecast_file: str | None
) -> str:
    """Get the weather tool's raw text response -- from a live, direct
    MCP call to the openweather server (not via the LLM), or, when
    `forecast_file` is given, from a previously-captured real response
    file (replay mode: no network or API key needed). Raises on any
    connection/protocol failure or file-read error; the caller is
    responsible for turning that into a user-facing message."""
    if forecast_file is not None:
        return Path(forecast_file).read_text(encoding="utf-8")
    return await _call_weather_tool_live(city, server_config)


def _daily_forecast_from_text(raw_text: str) -> tuple[list[dict], str | None]:
    """Normalize raw weather-tool text into a daily forecast via the
    standard parsing path (agent.normalize.normalize_forecast) -- the
    exact same call regardless of whether the text came from a live call
    or a replay file; there is no separate "fixture" parsing branch.

    Returns (daily_forecast, failure_reason). `failure_reason` is None on
    success; `daily_forecast` is always [] whenever `failure_reason` is
    set.
    """
    daily = normalize_forecast(raw_text)
    if not daily:
        return [], (
            "the weather tool returned no usable forecast data for this "
            "city (through this upstream tool, a missing/invalid API key, "
            "an unrecognized city, and an unreachable provider are all "
            "indistinguishable -- none of them produce a distinct error)"
        )
    return daily, None


def _build_prompt(
    city: str,
    works: list[dict],
    forecast: list[dict],
    current_conditions: dict | None = None,
) -> str:
    parts = [
        f"Plan the following works in {city} using the "
        "buildwindow tools. The daily weather forecast (already fetched "
        "and aggregated from the raw provider data) is given below.\n\n"
    ]
    if current_conditions is not None:
        parts.append(
            "Current conditions for this city have already been fetched "
            "-- no weather tool is connected in this session, so use "
            "these figures directly for the descriptive sentence in your "
            f"final report:\n{json.dumps(current_conditions, indent=2)}\n\n"
        )
    parts.append(f"Works:\n{json.dumps(works, indent=2)}\n\n")
    parts.append(f"Daily forecast:\n{json.dumps(forecast, indent=2)}\n")
    return "".join(parts)


def _print_discovery(status: dict) -> None:
    print("--- MCP server discovery ---", file=sys.stderr)
    for server in status.get("mcpServers", []):
        if server["name"] not in ("buildwindow", "openweather"):
            continue  # skip unrelated servers configured elsewhere in this environment
        tool_names = [t["name"] for t in server.get("tools", [])]
        detail = f" (tools: {', '.join(tool_names)})" if tool_names else ""
        print(f"  {server['name']}: {server['status']}{detail}", file=sys.stderr)
    print("-----------------------------", file=sys.stderr)


async def run(city: str, works: list[dict], forecast_file: str | None = None) -> None:
    offline = forecast_file is not None
    servers = _load_mcp_servers()

    try:
        raw_text = await _get_raw_weather_text(
            city, servers["openweather"], forecast_file
        )
    except Exception as exc:
        reason = (
            f"could not read forecast fixture '{forecast_file}' ({exc})"
            if offline
            else f"could not connect to the weather server ({exc})"
        )
        print(
            f"Forecast unavailable for '{city}' ({reason}). "
            "Scheduling requires a forecast; no schedule was produced.",
            file=sys.stderr,
        )
        return

    daily_forecast, failure = _daily_forecast_from_text(raw_text)
    if failure is not None:
        print(
            f"Forecast unavailable for '{city}' ({failure}). "
            "Scheduling requires a forecast; no schedule was produced.",
            file=sys.stderr,
        )
        return
    source = f"replay file '{forecast_file}'" if offline else "a live call"
    print(
        f"--- weather: fetched and normalized {len(daily_forecast)} day(s) "
        f"of forecast for '{city}' (source: {source}) ---",
        file=sys.stderr,
    )

    current_conditions = None
    mcp_servers = {"buildwindow": servers["buildwindow"]}
    allowed_tools = list(BUILDWINDOW_TOOLS)
    system_prompt = SYSTEM_PROMPT_LIVE
    if offline:
        # Current conditions come from the same recorded text; openweather
        # is deliberately absent from both mcp_servers and allowed_tools
        # so no live call is even possible in this mode, not just
        # discouraged by the prompt.
        current_conditions = parse_current_conditions(raw_text)
        system_prompt = SYSTEM_PROMPT_OFFLINE
    else:
        mcp_servers["openweather"] = servers["openweather"]
        allowed_tools.append(OPENWEATHER_TOOL)

    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        mcp_servers=mcp_servers,
        allowed_tools=allowed_tools,
        cwd=str(PROJECT_ROOT),
    )

    async with ClaudeSDKClient(options=options) as client:
        await client.query(
            _build_prompt(city, works, daily_forecast, current_conditions)
        )
        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(block.text)
                    elif isinstance(block, ToolUseBlock) and block.name.startswith(
                        "mcp__"
                    ):
                        # Only real MCP tool calls are printed -- internal
                        # SDK mechanisms (e.g. ToolSearch) are omitted so
                        # the trace is unambiguous.
                        print(
                            f"[tool call] {block.name}({json.dumps(block.input)})",
                            file=sys.stderr,
                        )
            elif isinstance(message, ResultMessage) and message.is_error:
                print(f"[agent error] {message.result}", file=sys.stderr)

        _print_discovery(await client.get_mcp_status())


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BuildWindow agent")
    parser.add_argument("city", nargs="?", default=DEMO_CITY)
    parser.add_argument("works_json", nargs="?", default=None)
    parser.add_argument(
        "--forecast-from-file",
        default=None,
        metavar="PATH",
        help=(
            "Replay mode: read the weather tool's raw text response from "
            "this file (e.g. fixtures/weather_longyearbyen.txt) instead of "
            "calling the live OpenWeather MCP server. The exact same "
            "normalize_forecast parsing path is used either way."
        ),
    )
    return parser.parse_args()


def main() -> None:
    # The model's output may contain characters outside the console's
    # active codepage (observed: a Windows console on cp1251 crashing on
    # a plain Unicode hyphen). Never let output encoding crash the run.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    load_dotenv()
    args = _parse_args()
    if args.works_json is None and os.environ.get("BUILDWINDOW_DATASET", "").strip():
        # DEMO_WORKS uses codes from the built-in example dataset, which a
        # user-supplied dataset almost certainly doesn't define -- stop
        # before starting an LLM session rather than let every tool call
        # fail with unknown_work_code.
        print(
            "BUILDWINDOW_DATASET is set, so the built-in demo work list "
            "doesn't apply. Pass a works list using codes from your dataset, "
            'e.g. \'[{"work_code": "<code>", "duration_days": 1, '
            '"depends_on": []}]\'.',
            file=sys.stderr,
        )
        sys.exit(2)
    works = json.loads(args.works_json) if args.works_json else DEMO_WORKS
    asyncio.run(run(args.city, works, args.forecast_from_file))


if __name__ == "__main__":
    main()
