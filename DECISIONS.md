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
