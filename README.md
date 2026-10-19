# BuildWindow

BuildWindow is a deterministic engine for planning work that depends on
the weather, served as an MCP (Model Context Protocol) server. You give it
the weather limits for your activities: minimum and maximum temperature,
maximum wind, maximum humidity, and whether precipitation is allowed. You
also give it a daily forecast. Four tools then tell an AI agent whether
each activity may go ahead on each day, which limit is breached and by how
much, and the earliest schedule that respects both the weather and the
dependencies between activities. The same tools work for any activity with
a weather window, for example concrete pours, roofing, exterior painting,
drone flights or crop spraying.

**The verdict is computed by code, not by the model.** Every verdict,
schedule and curing estimate comes from pure functions in
[`server/rules.py`](server/rules.py). The same limits and the same weather
always give the same answer, down to the exact margin of each breach. The
agent only passes data in and reports what comes back. It never decides
for itself whether 4 m/s of wind is acceptable.

**You bring the thresholds.** The limits live in a JSON dataset that you
point the server at with `BUILDWINDOW_DATASET`. A construction dataset
with 12 work types is built in, but it is an **illustrative example only**,
not a normative source. Its numbers are plausible, not taken from any
standard. Use your own limits from your standards, product data sheets,
equipment manuals or regulations.

```
your limits (JSON)  ─┐
                     ├─> BuildWindow MCP server ──> verdicts, violations, schedule
daily forecast  ─────┘   (deterministic, offline)
     ▲
any weather source: a weather MCP server, an API, a file, the user
```

## Quick start

Requirements: **[uv](https://docs.astral.sh/uv/)**, which fetches a
suitable Python by itself, and **git**.

Add the server to Claude Code with one command:

```bash
claude mcp add buildwindow -- uvx --from git+https://github.com/borovkov-d/buildwindow-mcp@v0.2.2 buildwindow-server
```

With your own limits:

```bash
claude mcp add buildwindow -e BUILDWINDOW_DATASET="/full/path/to/your_limits.json" -- uvx --from git+https://github.com/borovkov-d/buildwindow-mcp@v0.2.2 buildwindow-server
```

Then restart the Claude Code session so the tools appear. `uvx` downloads
that tagged release from GitHub once and runs it in an isolated
environment. It installs only the server and its two dependencies, `mcp`
and `pydantic`; the reference agent's Claude Agent SDK is not included.
Leave out `-e BUILDWINDOW_DATASET=…` to start with the built-in example.
Any other MCP client takes the same command (`uvx`, arguments
`--from git+https://github.com/borovkov-d/buildwindow-mcp@v0.2.2 buildwindow-server`) and the same environment variable in
its stdio server config.

To check what the server loads, run it once by hand. It runs over stdio
and prints one line to stderr; stop it with Ctrl+C:

```bash
BUILDWINDOW_DATASET="/full/path/to/your_limits.json" uvx --from git+https://github.com/borovkov-d/buildwindow-mcp@v0.2.2 buildwindow-server
```

```
BuildWindow MCP server ready: 4 tools, 5 work types loaded from /full/path/to/your_limits.json
```

At runtime the server makes no network calls (`uvx` only downloads it on
first use), reads only the one dataset file, and needs no API keys. It does
not fetch weather itself. The [agent skill](#use-as-an-agent-skill) has the
agent obtain a forecast and always name its source.

### From a clone (to edit the code)

Requirements: **Python 3.12+** and **uv**.

```bash
git clone https://github.com/borovkov-d/buildwindow-mcp.git
cd buildwindow-mcp
uv sync
uv run python -m server.main
```

`uv sync` also installs the dev tools and the reference agent's
dependencies (dependency groups `dev` and `agent`). To register a clone
instead of the released package:

```bash
claude mcp add buildwindow -e BUILDWINDOW_DATASET="/full/path/to/your_limits.json" -- uv --directory "/full/path/to/buildwindow-mcp" run python -m server.main
```

## Bring your own dataset

Set `BUILDWINDOW_DATASET` to the path of a JSON file with this shape:

```json
{
  "schema_version": "1.0",
  "work_types": [
    {
      "code": "crop_spraying",
      "name": "Crop spraying by drone",
      "category": "agriculture",
      "temp_min_c": 5,
      "temp_max_c": 28,
      "wind_max_ms": 4,
      "humidity_max_pct": 95,
      "precipitation_allowed": false,
      "base_curing_hours": null,
      "reference_note": "Product label section 4 and our spray-drift procedure."
    }
  ]
}
```

| Field | Type and range | Meaning |
|---|---|---|
| `code` | snake_case string, unique | The `work_code` used in every tool call |
| `name` | string | Human-readable name |
| `category` | snake_case string | Group for `lookup_work_requirements(category=…)` |
| `temp_min_c`, `temp_max_c` | number, −30…50, min < max | Allowed air temperature band, °C |
| `wind_max_ms` | number, 0…40 | Highest allowed wind speed, m/s |
| `humidity_max_pct` | integer, 0…100 | Highest allowed relative humidity, % |
| `precipitation_allowed` | boolean | `false`: any precipitation is a hard violation |
| `base_curing_hours` | positive integer or `null` | Nominal curing time at 20 °C, for `estimate_curing_time`. `null` means no curing stage. |
| `reference_note` | string | Where the limits come from. It is shown to the user, so cite your source. |

All fields are required (`base_curing_hours` may be `null`), and no extra
fields are accepted.

- **Unset or empty** `BUILDWINDOW_DATASET` → the built-in example
  ([`server/data/work_types.json`](server/data/work_types.json)).
- Prefer an **absolute path**. A relative one is resolved against the
  server's working directory.
- The file is read **once at startup**. Restart the server after changing
  it.
- The tools' input schemas list the loaded dataset's codes and categories
  as an `enum`, so the agent sees your activities, not the example's.

An invalid file stops the server with every problem listed:

```
[dataset_error] Dataset file …/limits.json is invalid. 2 problems found:
  - work_types[0] (code 'windy_flight').wind_max_ms: Input should be less than or equal to 40 (got 55)
  - work_types[1] (code 'Bad Code').code: String should match pattern '^[a-z][a-z0-9_]*$' -- use lowercase snake_case such as 'survey_mapping' (got 'Bad Code')
```

**A different domain, same engine:**
[`examples/drone_operations.json`](examples/drone_operations.json) defines
five drone missions: aerial photography, LiDAR survey, thermal inspection,
crop spraying and parcel delivery. Each has its own wind, temperature,
humidity and rain limits. Run the server on it with no code changes:

```bash
BUILDWINDOW_DATASET=examples/drone_operations.json uv run python -m server.main
```

These limits are illustrative too. Each record's `reference_note` says
what to check them against.

## Tools

| Tool | Summary |
|---|---|
| `lookup_work_requirements` | Look up the limits of one work type, or of every work type in a category. |
| `validate_work_window` | Check one work type against one day of weather. Returns `allowed`, `conditional` or `prohibited`, with every breached limit, its value and its margin. |
| `plan_work_schedule` | Place several works, with dependencies, across a forecast of up to 14 days in one call. Works that can't be placed come back with a reason. |
| `estimate_curing_time` | For work types with a curing stage: when the work is actually ready, given the daily temperatures (Nurse-Saul maturity method). |

A breach within a small tolerance band of the limit is reported as a
**warning**, and the verdict is `conditional`. The bands are 2 °C, 1 m/s
and 5 % humidity. A breach beyond the band is a **violation**, and the
verdict is `prohibited`. Errors come back as `[code] message`
(`unknown_work_code`, `unknown_category`, `cyclic_dependency`,
`no_curing_stage`, …). For unknown values, the message lists the valid
ones, so the agent can correct itself. `lookup_work_requirements` also
reports whether the limits come from the built-in example or from your own
file (`dataset_is_builtin_example`, `dataset_file`). Full contracts, with real captured
examples, are in [`docs/tool-contracts.md`](docs/tool-contracts.md).

## Use as an agent skill

[`skill/buildwindow/`](skill/buildwindow/) is a ready `SKILL.md` package.
It tells an agent when to reach for these tools and how to use them. It
covers the call order, how to read verdicts, how to react to each error,
and the rule that verdicts are never the model's own judgement. It also
says where the forecast comes from, in order: the user's own figures, a
weather connector, the agent's web search, and finally asking the user.
The agent always names the source, and it asks for a missing value rather
than invent it or treat it as zero. Its
[`references/dataset-format.md`](skill/buildwindow/references/dataset-format.md)
documents the dataset format for the agent. To install it, zip the
`skill/buildwindow` folder for a skill marketplace, or copy it into your
agent's skills directory. The skill expects the MCP server above to be
registered.

## Reference agent: OpenWeather + Claude Agent SDK

The repository also contains a complete example client in
[`agent/`](agent/). It connects to two MCP servers: BuildWindow, and the
external Go-based OpenWeather MCP server
([mschneider82/mcp-openweather](https://github.com/mschneider82/mcp-openweather)).
It then plans a list of works for a city. The agent is optional: the
BuildWindow server does not depend on it, and you can feed the server
forecasts from any other source.

It works with your own limits too. The BuildWindow server subprocess
inherits `BUILDWINDOW_DATASET` from the agent's environment, so pass work
codes from your dataset as the agent's work list.

### Prerequisites (agent only)

- **Go 1.24+**, only to build the OpenWeather MCP server yourself.
- **An OpenWeather API key**, only for a live run against real weather.
  A free tier is available at
  [openweathermap.org/api](https://openweathermap.org/api).
- **A logged-in Claude Code / Claude Agent SDK session**: the agent drives
  the model through `claude-agent-sdk`.

Replay mode (`--forecast-from-file`, below) needs neither Go nor an API key.

### How the agent uses the two servers

The *schedule-critical* OpenWeather call is deliberately **not** made by
the LLM. The upstream tool's actual output (confirmed by reading its
source — see `docs/tool-contracts.md`) is a plain-text report, not JSON,
and the only signal it gives for *any* failure (bad key, unrecognized
city, unreachable provider) is a syntactically successful but empty
response — there is no error text to react to. So `agent/main.py` calls
it directly via a low-level MCP client, parses it with a small,
unit-tested function (`agent/normalize.py`), and only then starts an LLM
session — handing the model already-clean daily figures instead of
asking it to interpret raw provider text. The LLM session is connected to
*both* MCP servers (`get_mcp_status()` discovery shows both connections),
and the model genuinely *is* allowed to call the weather tool itself
(`allowed_tools` lists it explicitly) — but only for one current-
conditions sentence in its final report, per the system prompt; the daily
forecast that drives `plan_work_schedule` always comes from the
deterministic pre-session fetch, never from the model's own call.

```
user input (city + work list)
  -> agent/main.py calls OpenWeather MCP directly (not via the LLM) for
     the schedule-critical daily forecast
  -> agent/normalize.py parses the plain-text response into daily figures
  -> (if no usable forecast: report plainly, stop -- no LLM session started)
  -> LLM session starts, connected to BOTH MCP servers; may itself call
     the weather tool once for current-conditions color commentary only
  -> given the daily forecast + works as plain JSON (the only input that
     ever drives scheduling)
  -> BuildWindow MCP  (plan_work_schedule, validate_work_window,
     estimate_curing_time, ...)
  -> schedule + explanation
```

### Configuration

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

Its `openweather.command` field is itself a placeholder,
`${MCP_OPENWEATHER_PATH}` — `agent/main.py` resolves it from the
`MCP_OPENWEATHER_PATH` environment variable if set, or falls back to the
bare command `mcp-openweather` (relying on `PATH`) if not. Set
`MCP_OPENWEATHER_PATH` in `.env` (see `.env.example`) to the binary's
absolute path if you don't want to add its directory to `PATH` — both
were verified to work live.

**Building the OpenWeather MCP server** (only needed if you want a live
run against real weather). These are the exact commands used to build and
verify it during development:

```powershell
winget install --id GoLang.Go -e --accept-source-agreements --accept-package-agreements
# open a new shell so PATH picks up the Go toolchain, then:
go install github.com/mschneider82/mcp-openweather@main
```

This installs to `$(go env GOPATH)\bin\mcp-openweather.exe` — on Windows
that's typically `%USERPROFILE%\go\bin\mcp-openweather.exe`. **Important:**
the Go MSI installer adds the Go *toolchain* (`C:\Program Files\Go\bin`)
to `PATH`, but does **not** add `%USERPROFILE%\go\bin` — where `go
install` actually places built binaries. Either add that directory to
`PATH` yourself, or set `MCP_OPENWEATHER_PATH` to the binary's full path
(see above) — this repo's own setup uses the latter.

**Why `@main` and not `@latest`:** `go install ...@latest` resolves to
tag `v1.0.0`, which is one real commit ("Fix #5") behind the repository's
`main` branch. Both were built and compared live: `v1.0.0`
reads the optional `units`/`lang` arguments with no fallback when
they're omitted entirely, so an omitted `lang` fails with `language
unavailable` even though the tool's own schema declares a default;
`main`'s "Fix #5" commit adds defensive handling and the same call
succeeds. The forecast template itself is otherwise identical between
the two (confirmed by reading both versions' source) — building from
`main` doesn't add per-day wind/humidity/precipitation, it only fixes
the argument bug. `agent/main.py` always passes `city`, `units="c"`, and
`lang="en"` explicitly regardless, so this bug can't actually surface
through this project either way — but `main` is the more robust binary
to depend on if you ever call the tool a different way.

Do **not** use the `-o mcp-weather` flag shown in some of the upstream
README's own examples — that produces a binary name inconsistent with its
own config example. Build with the default name, `mcp-openweather`.

### Running the agent

```powershell
uv run python -m agent.main
```

With no arguments, this uses a default city ("Kyiv") and a default work
list from the built-in example dataset: `excavation`, then `concrete_pour` (depending on it), then
`concrete_finishing` (depending on that).

Both can be overridden:

```powershell
uv run python -m agent.main "CityName"
uv run python -m agent.main "CityName" '[{"work_code": "excavation", "duration_days": 1, "depends_on": []}]'
```

The optional second argument is a JSON array of works in the same shape as
the default list. With your own dataset, use its codes:

```powershell
$env:BUILDWINDOW_DATASET = "examples/drone_operations.json"
uv run python -m agent.main "Longyearbyen" '[{"work_code": "lidar_survey", "duration_days": 1, "depends_on": []}, {"work_code": "crop_spraying", "duration_days": 2, "depends_on": []}]' --forecast-from-file fixtures/weather_longyearbyen.txt
```

**Replay mode** — `--forecast-from-file <path>` is fully offline: it
replaces *both* the daily forecast and the current-conditions note with
data read from a recorded file, via the same deterministic parsers
(`normalize_forecast`, `parse_current_conditions`) used for a live call.
`openweather` is not connected at all in this mode (confirmed via
`get_mcp_status()` — only `buildwindow` appears), so a run needs no
network access and no API key whatsoever — verified live with a
deliberately broken `OWM_API_KEY` and an unreachable
`MCP_OPENWEATHER_PATH` at the same time; the run still completed
normally:

```powershell
uv run python -m agent.main "Longyearbyen" '[{"work_code": "excavation", "duration_days": 1, "depends_on": []}, {"work_code": "exterior_painting", "duration_days": 2, "depends_on": []}]' --forecast-from-file fixtures/weather_longyearbyen.txt
```

`fixtures/weather_kyiv.txt` and `fixtures/weather_longyearbyen.txt` are
real responses captured live (trimmed to 3 full real
calendar days each, no key inside either) — not synthetic, not
fabricated examples. Useful for a reproducible run that doesn't
depend on today's weather, or when there's no network at all.

A full live run against real weather requires a genuinely valid
`OWM_API_KEY` (see Configuration above) — confirmed working in this
repo's own development environment: `uv run python -m agent.main "Kyiv"`
produces a real schedule from a real forecast, and
`uv run python -m agent.main "Longyearbyen" '[...]'` demonstrates real
weather actually forcing a reschedule (see `docs/demo-checklist.md` step
4). Without a working key, `agent/main.py` fetches the forecast directly
(not via the LLM), gets an empty result, prints
`Forecast unavailable for '<city>' (...)`, and exits *before* starting
any LLM session — no wasted model call, no fabricated schedule. This was
verified with three real failure modes: the `mcp-openweather` binary
unreachable at all, an invalid `OWM_API_KEY`, and an invalid city name —
the last two are actually indistinguishable through this upstream tool
(see `docs/tool-contracts.md` for why) and were both confirmed to fail
the same clean way, even with a genuinely valid key active elsewhere in
the same environment.

**OpenWeather rate limits:** one successful live run makes exactly
**two** real calls to the `weather` tool (confirmed live, by counting) —
the deterministic pre-session fetch, plus the model's own single
current-conditions call (see Overview above). A failed live run (no
usable forecast) makes exactly one, since the LLM session never starts.
Replay mode (`--forecast-from-file`) makes **zero** — both the daily
forecast and the current-conditions note come from the recorded file,
and `openweather` isn't connected at all in this mode (confirmed live:
`get_mcp_status()` shows only `buildwindow`). OpenWeather's free tier is
documented at 60 calls/minute and 1,000,000 calls/month — comfortably
enough for any number of manual runs; this project doesn't
stress-test that published figure itself.

## Project structure

```
.
├── README.md, DECISIONS.md, LICENSE, pyproject.toml, uv.lock, .env.example, .gitignore
├── server/                 # the engine: MCP server, no network, no I/O beyond the dataset
│   ├── main.py             # entry point, registers the 4 tools
│   ├── schemas.py          # Pydantic input/output models
│   ├── rules.py            # deterministic verdict/curing/planner logic
│   ├── dataset.py          # resolves BUILDWINDOW_DATASET, loads and validates the dataset
│   ├── errors.py           # domain exceptions and error codes
│   └── data/work_types.json  # built-in construction example dataset
├── examples/
│   └── drone_operations.json # example dataset from another domain
├── skill/buildwindow/      # SKILL.md package for agents
│   ├── SKILL.md
│   └── references/dataset-format.md
├── agent/                  # optional reference agent (OpenWeather + Claude Agent SDK)
│   ├── main.py
│   ├── normalize.py        # deterministic OpenWeather text -> daily figures
│   └── mcp_config.json     # config for both MCP servers
├── fixtures/               # real captured OpenWeather responses, for replay mode
├── scripts/
│   └── list_tools.py       # lists both MCP connections' tools, no weather call
├── docs/
│   ├── tool-contracts.md
│   ├── design-rationale.md
│   ├── demo-checklist.md   # step-by-step end-to-end verification walkthrough
│   └── sample-runs/        # real captured agent and skill-session transcripts
└── tests/
    ├── conftest.py
    ├── test_dataset.py, test_custom_dataset.py, test_lookup.py, test_validate.py
    ├── test_curing.py, test_planner.py, test_errors.py
    └── test_normalization.py
```

## Testing

```bash
uv run pytest -v
uv run ruff check .
uv run black --check .
```

All 63 tests pass. They cover the rules, the four tools, every error code,
custom datasets (loading, readable validation errors, the
`BUILDWINDOW_DATASET` fallback, and the schema enum), and the reference
agent's weather parsing. `ruff` and `black` report no issues.

## Limitations

The engine:

- **Thresholds are yours.** The engine applies whatever limits the
  dataset contains and does not check them against any standard. The
  built-in construction dataset and the drone example are illustrative.
- **Five fixed weather dimensions:** temperature band, wind, humidity and
  precipitation, one value each per day. There is no hourly resolution,
  and no gusts, visibility, UV or other dimensions.
- **Tolerance bands are global**, not set per work type: 2 °C, 1 m/s,
  5 % humidity, none for precipitation.
- **The planner is greedy.** Each work goes into the earliest feasible
  window, in dependency order. There are no resource or crew limits
  (works may overlap), no optimisation, and one work occupies one
  continuous block. The forecast is limited to 14 days per call.
- **Curing uses a simplified Nurse-Saul maturity model**, meant for
  cementitious materials. It applies only to work types with
  `base_curing_hours` set.

The reference agent's weather source. These limitations belong to the
specific external OpenWeather MCP tool, not to the engine. If you connect
another forecast source, you won't have them:

- That tool returns only temperature per 3-hour forecast entry. Wind and
  humidity come from a single current-conditions snapshot, which the agent
  applies as a constant across every forecast day. Precipitation is not
  exposed at all, so `precipitation_mm` is always `0.0` through that
  integration, and a precipitation rule can never trigger in a live run.
  The engine itself evaluates precipitation fully, as the unit tests show
  (`tests/test_validate.py`).
- Its forecast covers about 5 days, so live runs are capped there. The
  engine accepts up to 14.
- It cannot distinguish a bad API key, an unrecognised city and an
  unreachable provider. All three return the same empty response, so the
  agent can only report "no forecast available". It never invents a
  schedule.

See [`docs/design-rationale.md`](docs/design-rationale.md) and
[`docs/tool-contracts.md`](docs/tool-contracts.md) for the full,
source-verified detail.

## Documentation

- [`docs/tool-contracts.md`](docs/tool-contracts.md): the exact contracts
  for all four tools, and for the external OpenWeather `weather` tool as
  the reference agent uses it, each with a real captured example.
- [`docs/design-rationale.md`](docs/design-rationale.md): why each tool
  exists, the component boundaries, and the trade-offs.
- [`docs/demo-checklist.md`](docs/demo-checklist.md): a step-by-step
  end-to-end walkthrough of the server and the reference agent, including
  failure scenarios.
- [`docs/sample-runs/`](docs/sample-runs/): real captured output: the
  reference agent planning drone missions from
  `examples/drone_operations.json`, and a fresh Claude Code session in which
  the installed skill was picked up from its description alone.
- [`DECISIONS.md`](DECISIONS.md): a dated log of implementation decisions,
  each with its rationale and the rejected alternative.

## Origin

BuildWindow started as a course project for the KSE AI Agentic School, an
MCP integration assignment. The task was to build a custom MCP server for
a real domain problem and connect it, alongside an existing third-party
MCP server, to an agent. The first version was a construction scheduler
with its work types hard-coded. It was later generalised into the
dataset-agnostic engine described above. `DECISIONS.md` records each step
of that history.

## License

[MIT](LICENSE).
