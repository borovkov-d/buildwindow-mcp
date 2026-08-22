# Decisions log

Format: `- <question> — <decision> — <why> — <alternative rejected>`.

- Language for non-README docs and this log — English throughout — the
  spec only mandates English for README.md, but every code comment,
  docstring, and model-facing tool description is already English; mixing
  languages across the repo would hurt readability for no benefit —
  writing DECISIONS.md/design-rationale.md/demo-checklist.md in Ukrainian
  to mirror the spec itself, which would fragment the project's language.
- Repository root layout — treat `D:\INDIVIDUAL PROJECT` itself as the
  project root (no nested `buildwindow/` folder) — the directory was
  already empty and dedicated to this project, and the spec's file tree
  under `buildwindow/...` reads as "this is the repo," not "nest one more
  level" — an extra wrapper folder that config files, `uv`, and IDEs would
  all have to be pointed at for no benefit.
- MCP Python SDK class name — used `from mcp.server import MCPServer`
  (package `mcp==2.0.0`) instead of the historically-documented
  `FastMCP` — as of SDK v2.0.0 (2026-07-28), `FastMCP` was renamed to
  `MCPServer`; verified directly against the PyPI project page and the
  GitHub README (not taken on a single research pass's word, since it
  contradicted what I expected) before committing to it — pinning to the
  old v1 `FastMCP` API, which is now maintenance-only.
- `WorkCode` representation — declared explicitly as a 12-member `StrEnum`
  in schemas.py, with `dataset.py` cross-validating **bidirectionally** at
  load time (every dataset record's code must be a valid `WorkCode`, and
  every `WorkCode` must have a matching dataset record) — this turns an
  unknown code into a Pydantic validation failure at the MCP input
  boundary rather than a runtime `KeyError` deep in business logic, and
  the bidirectional check catches dataset/enum drift in either direction
  — generating `WorkCode` dynamically from the dataset file at import
  time, which is harder to reason about and to type-check.
- Where lookup-by-code/category logic lives — in `dataset.py`, not
  `rules.py` — `rules.py` is reserved for the three decision functions
  (verdict, curing, planner) per spec §5; looking up a record is a plain
  data query with no decision logic in it — putting it in `rules.py` to
  keep decision logic in one file regardless of whether a given function
  actually decides anything.
- MCP error boundary shape — one shared wrapper in `server/main.py`: a
  `BuildWindowError` propagates unchanged (its `__str__` already yields
  `[code] message`); any other exception is caught, its full traceback
  printed to stderr only, and it's re-raised as `InternalError` with a
  short message — matches spec §11.3's "no raw traceback ever leaves the
  server" literally while keeping all four tools on one code path —
  wrapping every `BuildWindowError` into a generic `Exception` too, which
  would have thrown away the `.code` attribute for no reason.
- Realizing `invalid_weather_window` / `invalid_lookup_criteria` — both
  are enforced by a Pydantic `model_validator` on the relevant input
  model (`WeatherWindow`, `LookupWorkRequirementsInput`), each raising
  `ValueError(str(SomeBuildWindowError(...)))` so the `[code] message`
  text survives inside the resulting `pydantic.ValidationError` — these
  two checks happen automatically before a tool function body even runs
  (there's no `main.py`-level call site to wrap the way there is for
  dataset lookups), so the code has to be embedded at the model level to
  guarantee it reaches the caller.
- Realizing `invalid_weather_window` on the dataset-loading side
  differently — `WorkRequirements`'s own `temp_min_c < temp_max_c`
  validator raises a **plain, unbranded** `ValueError` (no `[code]`
  prefix) — `WorkRequirements` doubles as the general-purpose output
  model for `lookup_work_requirements`, not just a dataset-loading
  artifact, so baking dataset-specific error framing into it would be
  misleading in that second context; instead `dataset.py`'s `Dataset.load()`
  is the one place that catches *any* `pydantic.ValidationError` arising
  from parsing the file and uniformly wraps it as `DatasetError` — giving
  every dataset-loading failure, whatever triggered it, the same clear
  code, instead of duplicating dataset-flavored wording into a model used
  elsewhere too.
- Dataset uniqueness / `WorkCode` cross-check — implemented as plain
  Python in `Dataset.load()` after `.model_validate()` succeeds, not as a
  Pydantic `model_validator` on a wrapping file-level model — keeps
  dataset-loading-specific checks out of `schemas.py`'s reusable models,
  consistent with the previous decision.
- `unknown_work_code` in practice — realized as a defensive branch in
  `Dataset.get_by_code()`, unreachable through normal MCP tool calls once
  `load()` has verified every `WorkCode` has a record (Pydantic already
  rejects an invalid code string at the input-schema boundary) — matches
  spec §11.1's own parenthetical, "insurance outside the enum"; tested
  directly by calling `get_by_code()` with a raw string that bypasses the
  type hint, which Python allows at runtime.
- `horizon_exceeded` vs `no_suitable_window` — spec §10.1's literal
  wording ties `horizon_exceeded` only to "earliest start already past
  the forecast," which doesn't cover a dependency-free work whose
  duration alone exceeds the horizon length (its earliest start *is* the
  horizon start, not past it) — resolved to the broader reading:
  `horizon_exceeded` fires whenever the required duration cannot fit
  anywhere in `[earliest_allowed_start, horizon_end]` regardless of
  weather; `no_suitable_window` fires when a window of sufficient size
  exists but every candidate window contains a prohibited day — the
  narrow literal reading, which left a real case (a too-long work with no
  dependency) unclassifiable.
- `estimate_curing_time`'s `daily_breakdown` when `capped=true` — includes
  every supplied day, since there's no ready day to truncate at; the
  "truncate at the ready day" behavior in spec §9.2 only applies once a
  ready date is actually found.
- `ConstraintViolation.margin`'s conditional-band check — uses
  `abs(margin)` against the band threshold, even though `margin =
  actual - limit` flips sign meaning between `temperature_min` (violation
  ⇒ negative) and the other four kinds (violation ⇒ positive) — spec §8.2
  states the margin formula but doesn't spell out that the comparison
  must be on the absolute value; implemented and documented explicitly
  rather than left implicit.
- Precipitation's `ConstraintViolation` shape — `limit_value=0.0`,
  `actual_value=precipitation_mm`, `margin=precipitation_mm`; never enters
  `warnings` (spec §8.2 states no conditional band exists for
  precipitation) — implemented as its own branch in `evaluate_window`
  rather than forcing it through the shared banded-constraint helper,
  which would have required a fake "band" value to keep it always a hard
  violation.
- Tool input parameter naming — each of the four tools takes a single
  Pydantic model parameter named `request` — the model shape itself is
  already named `XyzInput`, so `request` reads clearly at call sites — the
  more common `input`, which shadows the Python builtin of the same name.
- Test suite build order — `tests/conftest.py`'s fixtures (including the
  arithmetic-sensitive edge cases, with the arithmetic shown in comments)
  were written and hand-verified first; the six `test_*.py` files were
  then written in parallel by independent agents, each handed the same
  locked fixtures/constants — avoids six independent re-derivations of
  the same boundary numbers (e.g. the 2.0 °C conditional-band edge)
  landing on six subtly different values.
- OpenWeather 3-hour → daily aggregation — implemented as an explicit,
  fully-specified recipe in the agent's system prompt (min/max/max/avg/sum
  per field, spelled out precisely) that the model executes itself within
  one autonomous Claude Agent SDK tool-calling turn — hand-orchestrating a
  multi-turn pipeline in Python (fetch weather myself, aggregate in code,
  then prompt the model only for the scheduling step) would be more
  "provably correct" but is a materially more complex integration for a
  lab assignment, and isn't how the Agent SDK is normally used; giving the
  model an unambiguous formula (rather than "aggregate sensibly") keeps
  the risk of sloppy arithmetic low. This still respects the hard rule
  that weather *suitability* judgments come only from the buildwindow
  tools — aggregation is data transformation, not a suitability
  judgment.
- `agent/mcp_config.json` as the single source of truth — written as a
  static, human-readable `mcpServers` JSON file with
  `"env": {"OWM_API_KEY": "${OWM_API_KEY}"}` as a placeholder; `agent/main.py`
  loads this file at startup and substitutes `${VAR}` from the process
  environment itself before constructing `ClaudeAgentOptions` — avoids a
  second, independently-maintained hardcoded copy of the same config
  drifting out of sync with the file.
- Anchoring the stdio subprocess launch directory — passed
  `ClaudeAgentOptions(cwd=PROJECT_ROOT)` so the `buildwindow` server's
  relative `"command": "uv"` resolves correctly regardless of where
  `agent/main.py` is invoked from — confirmed via direct testing that
  `cwd` is a real, effective field on `ClaudeAgentOptions`, rather than
  mutating the agent process's own working directory with `os.chdir`.
- Go toolchain / `mcp-openweather` binary — **not** installed or built
  automatically. Go is not present on this machine; installing a
  system-wide compiler toolchain is a larger, less reversible footprint
  than any project-local file edit, and spec §19 already exempts the
  live-forecast check from blocking completion. README documents the
  exact build/install steps; this is flagged in the final report as a
  deferred live-check item, the same way spec §19 already treats
  `OWM_API_KEY` alone — attempting an unattended system-wide install,
  which oversteps what full autonomy was asked to cover.
- Build execution strategy — core code (dataset, schemas, rules, errors,
  main) was written directly and sequentially rather than delegated to
  parallel subagents, since ~90% of the repo's content is already fully
  dictated by the spec (exact values, formulas, docstrings) and the
  dominant risk was cross-file drift, not missing coverage; the Workflow
  tool was used narrowly, only for the six independent test files (after
  fixtures were locked) and could be used again for parallel doc
  drafting — heavy multi-agent fan-out across the whole build, which
  would have added coordination risk without adding real coverage.

## Phase 2 — live OpenWeather verification and normalization rework

- Scope interpretation of the "stop if `OWM_API_KEY` is missing" rule —
  read as gating only the sub-steps that need a genuinely valid key (a
  full live schedule against real weather, and a true city-not-found
  response), not a blanket halt on the whole phase — Go install, binary
  build, source-code contract verification, discovery, dummy-key error
  capture, the normalization rewrite and its tests, the full spec-vs-
  tests audit, and most of the docs sync are all independent of it and
  were completed. This mirrors phase 1's own precedent for the same key
  and the phase-2 brief's own step 4 being listed as independent — logged
  here rather than asked about, per this project's established autonomy
  policy.
- Go install method — `winget install --id GoLang.Go -e` (system-wide),
  as the user's own brief explicitly specified this exact approach — not
  re-litigated as a risk, since it was pre-authorized in writing for this
  phase, unlike phase 1 where the same action was deliberately avoided in
  the absence of that authorization.
- **Ground-truthing the OpenWeather MCP server by reading its actual
  source, not its README.** `go install github.com/mschneider82/
  mcp-openweather@latest` resolves to tag `v1.0.0`, which is *older* than
  the repository's default-branch `HEAD` (`HEAD` is one commit — "Fix
  #5" — ahead of the tag). The two versions behave differently; the
  installed one is the tag, so it — not `HEAD` — is what was verified
  against, by checking it out explicitly (`git checkout v1.0.0`) inside a
  scratch clone and reading `main.go` directly, then confirming behavior
  live against the actual built binary. Trusting `HEAD` (what a plain
  `git clone` shows by default) would have documented a tool that isn't
  actually what gets installed.
- **The `weather` tool's output is plain text, not JSON — a load-bearing
  discovery, not an assumption.** Confirmed from the v1.0.0 source: the
  handler renders a Go `text/template` into a single text content block
  (`mcp.NewToolResultText`); `CallToolResult.structured_content` is
  always `None`. The original design (spec §1/§13.2, phase 1's
  implementation) assumed a raw JSON 5-day/3-hour forecast needing
  aggregation — that assumption was reasonable given the spec's own
  framing but turned out to be wrong once the actual server was run;
  `agent/normalize.py` parses this fixed text template with regular
  expressions instead of `json.loads`.
- **The forecast section carries only date/time + temperature per 3-hour
  entry — wind, humidity and precipitation are absent from every forecast
  entry**, confirmed from the template source
  (`forecastTemplateTxt` only references `.DtTxt`, `.Main.Temp`,
  `.Main.TempMax`, `.Main.TempMin`). Only the single "current conditions"
  snapshot carries wind speed and humidity, and even that snapshot never
  carries precipitation. Resolved as: `wind_ms`/`humidity_pct` per day use
  the current snapshot's values as a constant proxy applied to every
  forecast day (documented as a real limitation of the upstream tool, not
  hidden); `precipitation_mm` is always `0.0` through this integration,
  since the tool exposes it nowhere at all — modifying the upstream Go
  server to add these fields, which is out of scope (spec explicitly
  treats OpenWeather MCP as an existing, unmodified external server).
- **`humidity_pct` aggregation changed from "average" (phase 1) to "max"
  (this phase's explicit instruction)** — implemented as specified,
  though in practice it is a constant per run anyway (see previous
  entry), since only one current-conditions reading exists per call.
- **This upstream tool cannot distinguish failure causes.** `getCurrent`/
  `getForecast5` discard the error return of `CurrentByName`/`DailyByName`
  entirely (confirmed in source); a missing API key, an invalid key, an
  unrecognized city, or an unreachable OpenWeather API all render the
  *same* way — `is_error=false` with the text template executed against a
  zero-valued struct (empty city name, all-zero readings, zero forecast
  entries) — verified live by calling the real binary with no key and
  with an obviously-fake key and observing byte-identical output.
  `normalize_forecast` therefore has exactly one failure signal available
  — an empty result — and `agent/main.py` treats that uniformly as
  "forecast unavailable," rather than attempting to string-match a
  distinct reason that does not exist. This also means failure-scenario 1
  (invalid city) and failure-scenario 2 (bad/missing key) are
  **observationally identical** through this tool once the binary itself
  is reachable; the only distinguishable failure mode is the binary being
  unreachable at all (a real `[WinError 2]`/connection-refused style
  failure, verified separately). Documented plainly rather than implying
  a distinction that doesn't exist.
- **A real bug in the pinned v1.0.0 release**: `weatherHandler` reads
  `units`/`lang` from the call arguments with a bare type assertion
  (`request.Params.Arguments["lang"].(string)`, discarding the `ok`) and
  no fallback, so an *omitted* `lang` argument becomes `""`, which the
  underlying `owm` library rejects as `language unavailable` — even
  though the tool's own advertised JSON Schema declares a default of
  `"en"`. `HEAD`'s later fix guards against this, but the pinned release
  doesn't. Worked around by always passing `city`, `units="c"`, and
  `lang="en"` explicitly on every call from `agent/main.py`, rather than
  relying on the schema-declared defaults — reproducible and confirmed
  live (the same call without `lang` fails; with it, it succeeds).
- **Normalization moved from LLM-prompt instructions to a pure, unit-
  tested Python function** (`agent/normalize.py`). This phase's brief
  required deterministic, pytest-assertable edge-case behavior (a full
  day computed correctly, a day with no precipitation defaulting to 0, an
  incomplete day dropped) — not achievable if aggregation stays inside
  free-form model reasoning. This is a genuine architecture change from
  phase 1, and a deliberate one: it extends this project's own
  established principle (quantitative logic belongs in code, not model
  reasoning, already applied to `evaluate_window`/`estimate_curing`/
  `plan_schedule`) to the weather-ingestion step too. As a consequence,
  `agent/main.py` now calls the `openweather` MCP server directly via the
  low-level `mcp.client.stdio.stdio_client` + `mcp.ClientSession` API
  (confirmed working via direct introspection and a live call against
  this project's own `buildwindow` server before being trusted), *before*
  ever starting a Claude Agent SDK session — the LLM session's
  `mcp_servers` now contains only `buildwindow`; `openweather` is never
  exposed to the model at all. This makes the "no forecast → no schedule"
  hard rule structurally guaranteed (enforced by a plain early return in
  Python) rather than dependent on the model noticing and complying, and
  it removes a wasted model turn on failure. `agent/mcp_config.json`
  remains the single source of truth for both servers' configuration —
  `agent/main.py` reads the `openweather` entry itself for the direct
  client call and passes the `buildwindow` entry through to
  `ClaudeAgentOptions` unchanged.
- **`agent/mcp_config.json`'s `openweather` command is a hardcoded
  absolute path** (`C:\Users\main\go\bin\mcp-openweather.exe`), not the
  bare command name relied on in phase 1's draft. Confirmed live: the Go
  MSI installer adds `C:\Program Files\Go\bin` (the toolchain) to `PATH`,
  but does **not** add `$(go env GOPATH)\bin` (`%USERPROFILE%\go\bin`,
  where `go install` actually places binaries) — a real, common Go-on-
  Windows gotcha, not a guess. A relative command name would silently
  fail to resolve even in a fresh shell unless the user separately adds
  that directory to `PATH` themselves. Documented in README as either
  fix; the absolute path is the more reliable default for this specific
  machine's setup, since this is a personal lab project, not distributed
  software with an unknown install location.
- Test audit against the phase-1 spec (this phase's step 4) — re-derived
  the Nurse-Saul nominal-curing figure and the 2.0 °C/2.1 °C conditional
  boundary independently from the formula and re-ran them live against
  the actual code (not just read the existing tests); both matched
  exactly, and the full 38-requirement-to-test mapping was confirmed
  against `pytest --collect-only`. No discrepancy between any test and
  the spec was found — nothing needed to change on either side.

## Phase 3 — dual-connection visibility, portability, demo depth

- **`openweather` restored to `ClaudeAgentOptions.mcp_servers`, paired
  with `disallowed_tools=["mcp__openweather__weather"]`.** Phase 2's
  decision to fetch weather directly in Python (not via the LLM) was
  correct and stays; dropping the server from the LLM session entirely
  was the wrong way to express that, since it hid a required connection
  from `get_mcp_status()` discovery. Both connections are now visible,
  but the model is structurally blocked from calling the weather tool
  (not just told not to in the prompt) — belt and suspenders, verified
  live: `get_mcp_status()` now lists `buildwindow` (4 tools) and
  `openweather` (tool `weather`) both `connected`.
- **Found and fixed a latent permission bug while verifying the above,
  not something this phase set out to look for.** `ClaudeAgentOptions`
  defaults to an interactive permission mode; a non-interactive script
  (no human present to approve a tool call) silently got its
  `plan_work_schedule` call denied — this had never surfaced before
  because no prior phase had gotten far enough (a normalized forecast in
  hand) to reach an actual buildwindow tool call in a real run. Fixed
  with `permission_mode="bypassPermissions"`. Caught by the synthetic
  forecast test built for step 5 below, not by luck — a real reason
  every architecture change here has ended in a live re-verification,
  not just a read-through.
- **Found and fixed a Unicode console-encoding crash while verifying the
  same test.** Printing the model's response text crashed with
  `UnicodeEncodeError` on this machine's console codepage (cp1251) the
  first time a response contained a character outside it. Fixed by
  reconfiguring `sys.stdout`/`sys.stderr` to UTF-8 with
  `errors="replace"` at the top of `main()` — cheap, general, and
  prevents the agent from crashing on arbitrary model output regardless
  of the terminal's locale.
- **`validate_work_window` given a real call site**: the system prompt's
  procedure now calls it for any work reported `unschedulable` with
  reason `no_suitable_window`, against the first day of the supplied
  forecast, to surface the specific breached constraint and its numbers
  to the engineer. Verified live with a synthetic forecast that
  guarantees this condition (bypassing the still-unavailable real
  weather key): the model called `plan_work_schedule`, then
  `validate_work_window`, then reported the exact `temperature_min`
  violation with limit/actual/margin values, unprompted beyond the new
  instruction.
- **Switched the documented/built OpenWeather version from `@latest`
  (tag `v1.0.0`) to `@main`** (commit `e032683`, "Fix #5"). Live
  comparison, not just re-reading source: built both, called each with
  `lang` omitted — `v1.0.0` fails (`language unavailable`, a real bug:
  the tool's own schema declares a default but the handler doesn't
  apply one when the argument is entirely absent), `main` succeeds
  (defensive argument handling added by "Fix #5"). Also confirmed the
  forecast template itself is byte-identical between the two versions —
  `main` does not add per-day wind/humidity/precipitation, so
  `agent/normalize.py`'s constant-current-conditions-proxy design needed
  no changes. `agent/main.py` still passes `lang`/`units` explicitly on
  every call regardless of which version is installed, since that costs
  nothing and removes any dependency on the fix being present.
- **Portable `mcp_config.json`**: the hardcoded absolute path from phase
  2 is now `${MCP_OPENWEATHER_PATH}`, resolved by a small dedicated
  helper (`agent/main.py`'s `_resolve_command`) that falls back to the
  bare command `mcp-openweather` (relying on `PATH`) if the variable is
  unset — not a generic templating mechanism, since this project has
  exactly one config value that needs this pattern. Verified both
  branches live: once with `MCP_OPENWEATHER_PATH` set to the known
  absolute path, once relying on the bare-command fallback with the
  binary's directory added to `PATH` instead.
- **`session-export.txt`** — added to `.gitignore` rather than deleted;
  it's the user's own `/export` output sitting in the repo root, not
  this project's file to remove.

## Phase 4 — live run with a real OpenWeather API key

- **A real key was obtained and confirmed genuinely active** (city
  `Kyiv`: 40 real 3-hour forecast entries, real temperatures, real
  humidity/wind). My *first* verification attempt wrongly looked like
  the key was still inactive — it wasn't; my throwaway test script had
  omitted `env=dict(os.environ)` on `StdioServerParameters`, so the
  subprocess got `mcp`'s default minimal environment, not the key at
  all. `agent/main.py`'s real `_fetch_daily_forecast` already builds its
  env dict correctly and was never at risk — this was caught before
  wrongly reporting a false "key not activated" stop condition, by
  re-checking the library's own default-environment behavior rather than
  taking the first empty result at face value.
- **`agent/normalize.py`'s parser needed no fix against real data** —
  checked by hand against two real days (`2026-08-22`, 3 slots;
  `2026-08-23`, 8 slots): computed `temp_min_c`/`temp_max_c` matched the
  true min/max of the real `Low`/`High` values exactly. This was a real
  possible outcome the plan anticipated, not an assumed one — reported
  as "no discrepancy found," not skipped.
- **One fixture-fidelity gap found and fixed, functionally inert but
  worth correcting**: `tests/test_normalization.py`'s sample text
  omitted the real API's ` +0000 UTC` timezone suffix on each
  `Date & Time:` line. The parser's `[^\n]*` already discarded that
  suffix regardless (confirmed: identical parsed output either way), so
  this was never a behavioral bug — but the fixture is now built from
  real captured entries (trimmed, no key) instead of a constructed guess,
  closing the "test and code share a blind spot" risk the phase's brief
  named directly, for the two full days at least. The "incomplete day"
  case in that same fixture is still constructed (2 real entries
  presented as if that were the whole day), since the live forecast this
  session happened to have every actual calendar day at or above the
  3-slot threshold — there was no naturally short day available to
  capture instead.
- **The real 5-day/3-hour forecast for Kyiv had zero days below
  `MIN_SLOTS_PER_DAY=3`** (day slot counts: 3, 8, 8, 8, 8, 5 = 40 total,
  6 calendar days survived filtering) — the "drop an incomplete day"
  branch is real, tested code, but this specific live call didn't
  exercise it; only a constructed fixture entry did (see above).
- **Second demo city — Murmansk, chosen live, not guessed.** Checked
  real current forecasts for five cold-weather candidates (Reykjavik,
  Murmansk, Tromsø, Longyearbyen, Norilsk); Murmansk and Longyearbyen
  both had every day below `exterior_painting`'s 10°C minimum. Picked
  Murmansk. The real run's actual blocking constraint turned out to be
  **humidity** (96% vs. the 80% limit), not temperature — the forecast
  temperature was only marginally low enough to land in the conditional
  *warning* band, not a hard violation — and the model correctly
  identified humidity as the true blocking cause in its final report
  rather than conflating the two. Not the exact mechanism anticipated
  going in, but a genuine, live-verified case of `validate_work_window`
  contributing real information to the outcome.
- **Invalid city vs. invalid key: re-confirmed indistinguishable, now
  with a real working key in play, not just an absent one.** Directly
  compared raw tool output for `("Kyivv", <real valid key>)` against
  `("Kyiv", "GARBAGE_KEY_NOT_REAL_00000")` — byte-for-byte identical.
  The existing "indistinguishable" claims in `docs/tool-contracts.md`
  and `docs/demo-checklist.md` stand as previously written; this entry
  just records that they were re-tested under stronger conditions, not
  left as an unverified holdover from when no real key existed at all.
- **`.env.example`'s placeholder line** had been changed on disk to
  Ukrainian text (`OWM_API_KEY=тут_повинен_бути_ключ`) by some process
  outside this conversation's own edits — reverted to English to match
  every other committed file's established convention (see this log's
  very first entry), and called out explicitly rather than silently
  changed.
- **`MCP_OPENWEATHER_PATH` added to `.env`** (not `.env.example` — that
  file only documents the option) pointing at the confirmed working
  binary path, for reliability across fresh shells in this environment
  (an established gotcha since phase 2 — Go's installer doesn't add
  `go install`'s own output directory to `PATH`).
