# BuildWindow

MCP lab project: an agent plans construction work against a real weather
forecast using two MCP servers.

## Overview

BuildWindow is an MCP (Model Context Protocol) lab project built around a
concrete scheduling problem: given a list of construction works with
dependencies between them, and a weather forecast for a city, produce a
schedule that respects both. The agent that does this planning holds two
separate MCP connections at once. The first is the external, Go-based
OpenWeather MCP server (github.com/mschneider82/mcp-openweather), which the
agent calls once per run to get live current conditions and a 5-day
forecast for the requested city — this is the only place in the whole
project where a network call happens. The second is this repository's own
BuildWindow MCP server: a local, fully deterministic server with no network
calls at runtime, backed by a local JSON dataset of construction work
types and their weather limits, that exposes four tools encoding the
construction-domain rules (weather-suitability verdicts, curing-time
estimation, and multi-work scheduling).

The two servers deliberately do not overlap in responsibility. OpenWeather
MCP is the only source of anything that changes day to day — the weather
itself. BuildWindow MCP owns everything that is a fixed rule instead: what
temperature, wind, humidity and precipitation a given work type tolerates,
how long concrete takes to cure at a given temperature, and how to place
several dependent works into the earliest non-prohibited windows across a
multi-day forecast. The BuildWindow server is built with the official
Python MCP SDK (package `mcp`, v2.0.0+), using its `MCPServer` class — note
that this class was named `FastMCP` in older SDK versions and was renamed
to `MCPServer` as of SDK v2.0.0. The agent that drives both connections is
built with the Claude Agent SDK (`claude-agent-sdk` on PyPI).

The OpenWeather connection is deliberately **not** made by the LLM. The
upstream tool's actual output (confirmed by reading its source — see
`docs/tool-contracts.md`) is a plain-text report, not JSON, and the only
signal it gives for *any* failure (bad key, unrecognized city, unreachable
provider) is a syntactically successful but empty response — there is no
error text to react to. So `agent/main.py` calls it directly via a
low-level MCP client, parses it with a small, unit-tested function
(`agent/normalize.py`), and only then starts an LLM session — handing the
model already-clean daily figures instead of asking it to interpret raw
provider text.

```
engineer input (city + work list)
  -> agent/main.py calls OpenWeather MCP directly (not via the LLM)
  -> agent/normalize.py parses the plain-text response into daily figures
  -> (if no usable forecast: report plainly, stop -- no LLM session started)
  -> LLM session starts, given the daily forecast + works as plain JSON
  -> BuildWindow MCP  (plan_work_schedule, estimate_curing_time, ...)
  -> schedule + explanation
```

## Prerequisites

- **Python 3.12+** — this repo was built and tested against 3.12.3.
- **[uv](https://docs.astral.sh/uv/)** — used as the dependency manager
  for this project.
- **Go 1.24+** — only needed if you want to build the OpenWeather MCP
  server yourself (installed here via `winget install --id GoLang.Go`,
  currently Go 1.26.7). Not required to use the BuildWindow server or to
  run its tests.
- **An OpenWeather API key** — only needed for a live agent run against
  real weather. Free tier available at
  [openweathermap.org/api](https://openweathermap.org/api).

## Installation

From the repo root:

```powershell
uv sync
```

This creates a `.venv` and installs both the runtime dependencies (`mcp`,
`pydantic`, `claude-agent-sdk`, `python-dotenv`) and the dev dependencies
(`pytest`, `ruff`, `black`).

## Configuration

Copy the example environment file and fill in your key:

```powershell
Copy-Item .env.example .env
```

bash: `cp .env.example .env`

Then edit `.env` and set `OWM_API_KEY` to a real key from
[openweathermap.org/api](https://openweathermap.org/api) (free tier).
`.env` is gitignored — it is never committed.

`agent/mcp_config.json` is the single source of truth for both MCP server
configurations. Its `openweather` entry references `${OWM_API_KEY}` as a
placeholder, which `agent/main.py` substitutes from the process
environment at startup. Note that `agent/main.py` does not read `.env`
itself — its `main()` calls `python-dotenv`'s `load_dotenv()` first, and
that call is what actually makes the values in `.env` reach the process
environment before the substitution happens.

**Building the OpenWeather MCP server** (only needed if you want a live
run against real weather). These are the exact commands used to build and
verify it in this repo's own development environment:

```powershell
winget install --id GoLang.Go -e --accept-source-agreements --accept-package-agreements
# open a new shell so PATH picks up the Go toolchain, then:
go install github.com/mschneider82/mcp-openweather@latest
```

This installs to `$(go env GOPATH)\bin\mcp-openweather.exe` — on Windows
that's typically `%USERPROFILE%\go\bin\mcp-openweather.exe`. **Important:**
the Go MSI installer adds the Go *toolchain* (`C:\Program Files\Go\bin`)
to `PATH`, but does **not** add `%USERPROFILE%\go\bin` — where `go
install` actually places built binaries. A bare `"command":
"mcp-openweather"` in `agent/mcp_config.json` will silently fail to
resolve even in a brand-new shell unless you separately add that
directory to `PATH` yourself. This repo's checked-in
`agent/mcp_config.json` sidesteps that entirely by using the absolute
path (`C:\Users\main\go\bin\mcp-openweather.exe`) directly — if your
`go env GOPATH` differs, update that one path.

`go install ...@latest` resolves to tag `v1.0.0` (verified by checking out
that tag and reading its source — it's one commit behind the repository's
`HEAD`). One behavior worth knowing about this pinned version: its
`weather` tool reads the optional `units`/`lang` arguments with no
fallback when they're omitted entirely, so an omitted `lang` fails with
`language unavailable` even though the tool's own schema declares a
default. `agent/main.py` always passes `city`, `units="c"`, and
`lang="en"` explicitly to avoid this — nothing you need to do here, just
documented in case you call the tool directly yourself.

Do **not** use the `-o mcp-weather` flag shown in some of the upstream
README's own examples — that produces a binary name inconsistent with its
own config example. Build with the default name, `mcp-openweather`.

## Running the MCP server

```powershell
uv run python -m server.main
```

This runs the BuildWindow MCP server over stdio, independent of the agent
process — it can be started and exercised entirely on its own. On success
it prints exactly this line to stderr:

```
BuildWindow MCP server ready: 4 tools, 12 work types loaded
```

## Running the agent

```powershell
uv run python -m agent.main
```

With no arguments, this uses a built-in demo city ("Kyiv") and a built-in
demo work list: `excavation`, then `concrete_pour` (depending on it), then
`concrete_finishing` (depending on that).

Both can be overridden:

```powershell
uv run python -m agent.main "CityName"
uv run python -m agent.main "CityName" '[{"work_code": "excavation", "duration_days": 1, "depends_on": []}]'
```

The optional second argument is a JSON array of works in the same shape as
the demo list.

A full live run against real weather requires a genuinely valid
`OWM_API_KEY` (see Configuration above). Without one, `agent/main.py`
fetches the forecast directly (not via the LLM), gets an empty result,
prints `Forecast unavailable for '<city>' (...)`, and exits *before*
starting any LLM session — no wasted model call, no fabricated schedule.
This was verified with three real failure modes in this repo's own
development environment: the `mcp-openweather` binary unreachable at all,
no `OWM_API_KEY` set, and an invalid city name — the last two are
actually indistinguishable through this upstream tool (see
`docs/tool-contracts.md` for why) and were both confirmed to fail the
same clean way.

## Project structure

```
D:\INDIVIDUAL PROJECT\
├── README.md, DECISIONS.md, pyproject.toml, uv.lock, .env.example, .gitignore
├── docs/
│   ├── tool-contracts.md
│   ├── design-rationale.md
│   └── demo-checklist.md
├── server/
│   ├── main.py            # MCP server entry point, registers the 4 tools
│   ├── schemas.py         # Pydantic input/output models
│   ├── rules.py           # deterministic verdict/curing/planner logic
│   ├── dataset.py         # loads and validates work_types.json
│   ├── errors.py          # domain exceptions and error codes
│   └── data/work_types.json
├── agent/
│   ├── main.py             # agent entry point (Claude Agent SDK)
│   ├── normalize.py        # deterministic OpenWeather text -> daily figures
│   └── mcp_config.json     # config for both MCP servers
└── tests/
    ├── conftest.py
    ├── test_dataset.py, test_lookup.py, test_validate.py
    ├── test_curing.py, test_planner.py, test_errors.py
    └── test_normalization.py
```

## Tool overview

| Tool | Summary |
|---|---|
| `lookup_work_requirements` | Look up a work type's, or an entire category's, weather limits. |
| `validate_work_window` | Check one work type against one day of weather and get back an itemized verdict. |
| `estimate_curing_time` | Estimate when a curing work type will actually be ready, given a sequence of daily temperatures. |
| `plan_work_schedule` | Place several dependent works across a multi-day forecast in one call. |

The full contracts — exact JSON Schemas and real captured examples for
every tool, including the external `weather` tool as used by this project
— live in [`docs/tool-contracts.md`](docs/tool-contracts.md).

## Testing

```powershell
uv run pytest -v
uv run ruff check .
uv run black --check .
```

All three currently pass cleanly in this repo: 47 tests pass (covering
the 38 spec-required cases, a few supplementary assertions, and 4 tests
for the `agent/normalize.py` weather-parsing module), and both `ruff` and
`black` report no issues.

## Limitations

The full reasoning behind each of these lives in
[`docs/design-rationale.md`](docs/design-rationale.md) — this list is
intentionally brief:

- Dataset thresholds are illustrative, not derived from real ДБН/ДСТУ
  standards.
- The planner has no resource/crew constraints — works can overlap dates.
- The real planning horizon is capped at 5 days by the OpenWeather
  provider.
- Curing time uses a simplified Nurse-Saul maturity model.
- One work occupies one continuous block — there is no split scheduling.
- The OpenWeather MCP server's `weather` tool (confirmed by reading its
  source, not assumed) exposes only temperature per 3-hour forecast
  entry — wind speed and humidity are only available in a single
  current-conditions snapshot, applied here as a constant across every
  forecast day, and precipitation isn't exposed at all, so
  `precipitation_mm` is always `0.0` through this integration. The same
  tool also can't distinguish a bad API key from an unrecognized city
  from an unreachable provider — all three come back as the same
  syntactically-successful-but-empty response, which is why
  `agent/main.py` can only report "no forecast available," not a specific
  cause, for any of those three cases. See `docs/tool-contracts.md` for
  the full, source-verified detail.
- No genuinely valid `OWM_API_KEY` was available in this development
  environment, so a fully successful live schedule against real weather
  was not run here — everything up to and including that point (Go
  install, binary build, real tool discovery, both failure paths, and the
  normalization logic against the tool's confirmed real output format)
  was verified live. This is the one remaining open item; see
  `DECISIONS.md`.

## Documentation

- [`docs/tool-contracts.md`](docs/tool-contracts.md) — the exact JSON
  Schema contracts for all four BuildWindow tools, and for the external
  OpenWeather `weather` tool as used by this project, each with a real
  captured example.
- [`docs/design-rationale.md`](docs/design-rationale.md) — why each tool
  exists, how the tool set maps onto the workflow, the boundaries between
  components, the trade-offs made, and the project's limitations in full.
- [`docs/demo-checklist.md`](docs/demo-checklist.md) — a step-by-step
  checklist for running a live demo of the project.
- [`DECISIONS.md`](DECISIONS.md) — a dated log of implementation
  decisions, each with its rationale and the alternative that was
  rejected.
