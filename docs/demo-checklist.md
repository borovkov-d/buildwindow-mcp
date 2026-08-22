# Live demo checklist

A step-by-step walkthrough script for a live 10-15 minute grading demo of
BuildWindow. Run each step from the repository root in order. Commands are
copy-pasteable as written; PowerShell-specific variants are noted where they
differ.

This script assumes the presenter's machine has Go installed and
`OWM_API_KEY` set, per README's Configuration section, so the OpenWeather
connection is live. Wherever a step's output depends on the real forecast
at demo time, that is called out explicitly below — it cannot be
pre-scripted.

---

## 1. Start the BuildWindow MCP server independently

```
uv run python -m server.main
```

**Point out:** this is a separate process from the agent — it proves the
BuildWindow server starts and runs completely on its own, with no
dependency on the agent or on OpenWeather.

**Expected stderr** (captured verbatim from a real run):

```
BuildWindow MCP server ready: 4 tools, 12 work types loaded
```

Stop it with **Ctrl+C**.

---

## 2. Start the agent and show discovery of both connections

```
uv run python -m agent.main
```

**Architecture note (updated this phase):** the schedule-critical daily
forecast is still fetched and normalized directly by `agent/main.py` via
a low-level MCP client (`mcp.client.stdio.stdio_client` +
`mcp.ClientSession`), *before* the LLM session starts — that part of
phase 2's design didn't change and is still correct (the raw text
response is parsed deterministically, not interpreted by the model). What
changed this phase: the model itself now *also* connects to `openweather`
and is genuinely allowed to call its `weather` tool
(`allowed_tools` lists all 5 real tool names — 4 buildwindow + `weather`;
no `disallowed_tools` or `bypassPermissions` needed, confirmed live) —
but only for one current-conditions sentence in its final report, per the
system prompt's step 1. The daily forecast driving `plan_work_schedule`
always comes from the deterministic pre-session fetch, never from the
model's own call. Both connections are genuinely incorporated into the
agent's own flow, not just visible in discovery.

**Point out, in order:**
- The line `--- weather: fetched and normalized N day(s) of forecast for
  '<city>' ---` on stderr — the OpenWeather connection's real evidence,
  printed by `agent/main.py` right after the direct client call succeeds
  and `agent/normalize.py` produced at least one usable day.
- `--- MCP server discovery ---` printed at the end, from
  `get_mcp_status()`. Real captured output (live run against `Kyiv`,
  with a genuinely valid `OWM_API_KEY`):
  ```
  buildwindow: connected (tools: lookup_work_requirements, validate_work_window, estimate_curing_time, plan_work_schedule)
  openweather: connected (tools: weather)
  ```
  Both connections, both discovered — this is the direct answer to "show
  that the agent discovers both MCP connections."

---

## 3. A successful call to the OpenWeather tool

Two genuine calls happen per run, one Python-side and one model-side —
point out both:

- **The deterministic pre-session fetch**, made *before* the LLM session
  starts (see step 2's architecture note), by `agent/main.py`'s
  `_fetch_daily_forecast` function. Run `uv run python -m agent.main "Kyiv"`
  and watch stderr for `--- weather: fetched and normalized N day(s) of
  forecast for 'Kyiv' (source: a live call) ---` — that line only appears
  once `agent/normalize.py`'s `normalize_forecast` found at least one day
  with 3+ forecast entries.
- **The model's own call**, visible in the tool-call trace as
  `[tool call] mcp__openweather__weather({"city": "Kyiv"})`, per the
  system prompt's step 1 (current conditions only — see step 5 below for
  why the two calls can't be confused with each other).

Also point out (from `docs/tool-contracts.md`'s OpenWeather section): the
raw response is **plain text**, not JSON, and only carries temperature
per 3-hour forecast entry — wind, humidity and precipitation are not
present per entry at all, only in the single current-conditions snapshot
(precip is absent even there) — this is exactly why a dedicated,
unit-tested parser (`agent/normalize.py`, see `tests/test_normalization.py`)
exists instead of asking the model to eyeball the format for the
schedule-critical data; the model's own call only ever reads the same
text for a one-sentence color note.

---

## 4. The full flow where the forecast actually changes the outcome

**4a. Baseline run (default demo input) — everything fits, nothing to
reschedule.**

```
uv run python -m agent.main
```

(No arguments — the built-in demo input: city **Kyiv**, works
`excavation -> concrete_pour (depends on excavation) ->
concrete_finishing (depends on concrete_pour)`.)

Real captured result (this phase, live, valid key): all three works
scheduled `allowed` with no rescheduling (`excavation` 2026-08-23,
`concrete_pour` 2026-08-24 to 25, `concrete_finishing` 2026-08-26).
`estimate_curing_time` for `concrete_pour` correctly reported
`capped: true` — the supplied forecast doesn't extend far enough past
the pour date to reach full Nurse-Saul maturity (2834.64 of the required
5040 units accumulated by the end of the forecast). **Point out:**
Kyiv's real August weather is warm enough that nothing gets rescheduled
— a technically-correct but visually unconvincing demo of weather's
influence on its own, which is exactly why step 4b exists. (On a live
run, today's real dates will differ from the ones shown above — that's
expected; see 4c's note on why the dates in this doc don't need updating
every day.)

**4b. A city where the real forecast actually forces a reschedule.**

```
uv run python -m agent.main "Longyearbyen" '[{"work_code": "excavation", "duration_days": 1, "depends_on": []}, {"work_code": "exterior_painting", "duration_days": 2, "depends_on": []}]'
```

Chosen by actually checking real current forecasts (see `DECISIONS.md`)
against `exterior_painting`'s 10°C minimum — Longyearbyen's real
forecast this phase was 1.23–5.32°C across its whole 3-5 day horizon,
entirely below that threshold. Real captured result:
- `excavation` scheduled `allowed` (2026-08-23) — tolerates the cold
  (its own range is −10 to 40°C).
- `exterior_painting` (2 days) came back `unschedulable`,
  `no_suitable_window`.
- `validate_work_window` fired automatically (per phase 3's system-prompt
  addition) on the first forecast day, and the model correctly cited
  **both** breached constraints together: **temperature** (3.77°C vs. the
  10.0°C minimum, margin −6.23°C — far outside the 2°C conditional band,
  so a hard violation this time, not just a warning) and **humidity**
  (87% vs. the 80% maximum). Unlike an earlier demo city (see
  `DECISIONS.md`) where temperature only landed as a warning, here it's
  independently blocking on its own — the model reported both causes
  rather than picking one.

**Point out:** this is genuine evidence that `validate_work_window`'s
output changes what the engineer is told, and that the specific breached
constraint(s) it names are real, not guessed by the model. (These
numbers are a real captured run — a fresh live run on a different day
will show different real weather and may differ slightly, e.g. a
different humidity reading; for numbers guaranteed to reproduce exactly,
use 4c's replay mode instead.)

**4c. Replay mode — fully offline, no network or key needed at all.**
Weather changes, and a demo shouldn't depend on the internet working on
the day. This mode doesn't just re-use a recorded forecast (phase 5) —
it now supplies current conditions from the same file too, so
`openweather` isn't connected at all:

```
uv run python -m agent.main "Longyearbyen" '[{"work_code": "excavation", "duration_days": 1, "depends_on": []}, {"work_code": "exterior_painting", "duration_days": 2, "depends_on": []}]' --forecast-from-file fixtures/weather_longyearbyen.txt
```

`--forecast-from-file` swaps the *source* of both the daily forecast and
the current-conditions note — `fixtures/weather_longyearbyen.txt` is a
real response captured live this phase (not synthetic, not a fabricated
example), trimmed to 3 full real calendar days (24 entries). The exact
same `normalize_forecast`/`parse_current_conditions` parsing path runs
on it as on a live call — no special-cased bypass. **Verified live with
a deliberately broken `OWM_API_KEY` and an unreachable
`MCP_OPENWEATHER_PATH` set at the same time** — the run still completed
normally and reproduced the same outcome as 4b's live run:
`exterior_painting` unschedulable/`no_suitable_window`, both temperature
and humidity cited by `validate_work_window`, current conditions correct
(4.91°C, overcast clouds — matching the fixture's header exactly), and
`get_mcp_status()` discovery showing **only** `buildwindow` connected —
`openweather` doesn't even appear, proving no connection was attempted.
A matching `fixtures/weather_kyiv.txt` exists for the same purpose on
the baseline scenario.

**The fixture dates are frozen at capture time and will be in the past
by demo day — this doesn't matter.** `server/rules.py`'s `plan_schedule`
derives `horizon_start`/`horizon_end` as `min`/`max` over the supplied
forecast's own dates (confirmed by reading the code: no call to
`date.today()`, `datetime.now()`, or any other system-clock read exists
anywhere in `server/` or `agent/`); it schedules entirely relative to
whatever dates the forecast carries, never the machine's current date.
Replaying a fixture whose dates are now in the past produces the exact
same schedule, relative to those dates, as it did the day it was
captured — nothing in this doc needs updating just because time has
passed.

**Proving both connections discover fine even with an invalid API key, a
separate way.** Replay mode's own `get_mcp_status()` output (above) only
ever shows `buildwindow`, since `openweather` is deliberately omitted
from the session entirely — so it can't be used to show *both*
connections at once. If asked to prove the `openweather` binary itself
still starts and answers MCP discovery without a working key (as
opposed to just "the agent chooses not to connect it"), run:

```
uv run python scripts/list_tools.py
```

**Real captured output, run this phase with a deliberately broken
`OWM_API_KEY` set in the environment:**

```
buildwindow ['lookup_work_requirements', 'validate_work_window', 'estimate_curing_time', 'plan_work_schedule']
openweather ['weather']
```

Both connections answer `list_tools()` instantly with a broken key in
place — direct evidence that MCP tool *discovery* (`initialize` +
`list_tools`) does not depend on a valid key, since only an actual
`call_tool("weather", ...)` reaches the OpenWeather HTTP API. **What
this does *not* prove:** this machine's real network adapter was left
on for this test (disabling it was judged too disruptive a
machine-wide action to take just to document one claim more strongly,
and wasn't independently re-run here) — so "no network access at all"
is not a verified claim, only "no valid API key required." It remains
possible that `list_tools()` makes some network-independent local
check the OpenWeather binary happens to perform at startup; nothing in
the binary's own source (see `docs/tool-contracts.md`) suggested one,
but this specific run didn't rule it out by cutting the adapter.

---

## 5. Explain the OpenWeather tool's contract and its role

No command — reference `docs/tool-contracts.md`, section
**"OpenWeather MCP — `weather` tool."**

**Say:** one tool, `weather`, served by an external Go binary
(`mcp-openweather`, not part of this repo). It returns a plain-text
report, not JSON — confirmed by reading its actual source, since the
tool's own `structured_content` is always empty. BuildWindow's server
(`server/main.py`) never sees this raw text at all. The model *is*
allowed to call it (`allowed_tools` includes
`mcp__openweather__weather`) — but only for one current-conditions
sentence per the system prompt's step 1; the schedule-critical daily
forecast still comes exclusively from `agent/main.py`'s own deterministic
pre-session fetch + `agent/normalize.py` parse, never from the model's
own call, so there are two independent readings of the same tool and
only one of them can ever influence the schedule. Worth mentioning: this
upstream tool can't distinguish a bad API key from an unrecognized city
from an unreachable provider — all three come back as the same "hollow,"
zero-valued response (see `docs/tool-contracts.md`); that's a real,
source-confirmed limitation of the external tool, not a gap in this
project's own code.

---

## 6. The full workflow through the BuildWindow server alone

No weather dependency — always reproducible live regardless of Go/API-key
status. Run interactively:

```
uv run python
```

```python
from datetime import date
from server.main import (
    lookup_work_requirements, validate_work_window,
    estimate_curing_time, plan_work_schedule,
)
from server.schemas import (
    LookupWorkRequirementsInput, ValidateWorkWindowInput, WeatherWindow,
    EstimateCuringTimeInput, PlanWorkScheduleInput, PlannedWork, WorkCode,
)

# a) requirements lookup
lookup_work_requirements(LookupWorkRequirementsInput(work_code=WorkCode.CONCRETE_POUR))

# b) validate against a cold/windy day -- hard wind violation AND a
# within-band temperature warning together, proving no short-circuit
validate_work_window(ValidateWorkWindowInput(
    work_code=WorkCode.CONCRETE_POUR,
    window=WeatherWindow(date=date(2026, 8, 20), temp_min_c=3.0,
                          temp_max_c=25.0, wind_ms=17.0,
                          humidity_pct=60, precipitation_mm=0.0),
))

# c) curing at a stable 20 C for 7 days -- effective_hours lands exactly
# on 168, the nominal base_curing_hours
estimate_curing_time(EstimateCuringTimeInput(
    work_code=WorkCode.CONCRETE_POUR,
    daily_temps_c=[20.0] * 7,
    start_date=date(2026, 8, 20),
))

# d) a 2-work dependency chain
plan_work_schedule(PlanWorkScheduleInput(
    works=[
        PlannedWork(work_code=WorkCode.EXCAVATION, duration_days=1, depends_on=[]),
        PlannedWork(work_code=WorkCode.CONCRETE_POUR, duration_days=2,
                    depends_on=[WorkCode.EXCAVATION]),
    ],
    forecast=[...],  # see docs/tool-contracts.md for the exact forecast
))
```

**Point out:** these are the same real examples captured in
`docs/tool-contracts.md` — reference that file for the exact JSON
input/output of each call if asked. In (b): both a hard `wind` violation
and a within-band `temperature_min` warning appear in the same response,
proving all five constraint checks always run, with no short-circuit on
the first breach. In (c): `effective_hours == 168`, exactly
`base_curing_hours` for `concrete_pour`, as expected at the 20 C
reference temperature.

---

## 7. Prove 4 tools are exposed

No new command — point back at step 2's discovery output
(`buildwindow: connected (tools: lookup_work_requirements,
validate_work_window, estimate_curing_time, plan_work_schedule)`) as the
direct proof.

Alternatively:

```
uv run pytest tests/ -v
```

**Point out:** the tool-facing tests exercise all 4 tools by name across
47 passing tests (43 covering the spec's required cases, plus 4 for the
weather-normalization module added this phase), with clean `ruff`/`black`.

---

## 8. Explain one custom tool's contract and one design decision

**Tool:** `plan_work_schedule` — the most structurally interesting of the
four (dependency resolution via topological sort, then greedy first-fit
placement). Reference `docs/tool-contracts.md`'s `plan_work_schedule`
section for the exact input/output schema.

**Design decision:** reference `docs/design-rationale.md`, section 5
(Trade-offs) — either:
- **Greedy planner over an optimizer** — placing works in topological
  order and taking the first non-prohibited window is far easier to
  reason about, explain live, and keep deterministic, at the cost of not
  being provably optimal; or
- **The `conditional` tolerance band** — a forecast is not ground truth,
  so a single hard threshold would either reject work that will probably
  be fine or force the limits themselves to loosen; the band surfaces the
  uncertainty explicitly instead of hiding it behind one boolean.

---

## 9. Failure scenario 1 — invalid city

```
uv run python -m agent.main "Kyivv"
```

(The doubled letter is deliberate — this guarantees it is not a real
city.)

**Real captured output** (re-confirmed this phase with a genuinely valid,
active `OWM_API_KEY` in the environment — this now proves the two really
are indistinguishable rather than just looking that way because no key
worked yet):

```
Forecast unavailable for 'Kyivv' (the weather tool returned no usable
forecast data for this city (through this upstream tool, a missing/
invalid API key, an unrecognized city, and an unreachable provider are
all indistinguishable -- none of them produce a distinct error)).
Scheduling requires a forecast; no schedule was produced.
```

No traceback, no fabricated schedule, no LLM call even attempted (the
Python-level fetch fails before any agent session starts — see step 2's
architecture note). **Important, source-confirmed nuance:** this upstream
tool discards the underlying error from the weather API entirely
(confirmed by reading its source), so it renders the exact same
zero-valued response for an invalid city as it does for a bad API key —
this scenario and scenario 2 below are **observationally identical**
through this specific external tool even with a working key active in
the same environment (directly diffed the two raw responses byte-for-
byte this phase: identical). That's a genuine limitation of the upstream
tool, disclosed rather than papered over — say so if asked why the
message doesn't specifically say "city not found."

---

## 10. Failure scenario 2 — `OWM_API_KEY` unset

Unset the key for the current session (or simply don't set it):

```
Remove-Item Env:OWM_API_KEY
```

then:

```
uv run python -m agent.main
```

**Real captured output** — this phase, a garbage value was substituted
for `OWM_API_KEY` via the process environment (not editing `.env`, which
still holds the real key), confirming the failure path independent of
whether a valid key exists elsewhere:

```
Forecast unavailable for 'Kyiv' (the weather tool returned no usable
forecast data for this city (through this upstream tool, a missing/
invalid API key, an unrecognized city, and an unreachable provider are
all indistinguishable -- none of them produce a distinct error)).
Scheduling requires a forecast; no schedule was produced.
```

Byte-for-byte the same shape as step 9's message, for the reason
explained there. **A third, distinguishable failure mode also exists and
was re-confirmed this phase**: if `mcp-openweather`'s command in
`agent/mcp_config.json` (or `MCP_OPENWEATHER_PATH`) doesn't resolve at
all (binary missing/wrong path), the direct client call raises a real
Python exception instead (observed live: `[WinError 2] The system cannot
find the file specified`), and the message becomes `Forecast unavailable
for '<city>' (could not connect to the weather server (...))` — this is
the one case this project's tooling *can* actually distinguish.

**Point out:** this is direct, confirmed evidence that the "no forecast,
no schedule" hard rule holds under all three real failure modes tried,
not just in theory — and that the rule is now enforced by a plain early
return in Python before any LLM call, not by asking the model to notice
and comply.

---

## 11. A prepared variation of a valid input

```
uv run python -m agent.main "Lviv" '[{"work_code": "asphalt_paving", "duration_days": 3, "depends_on": []}, {"work_code": "structural_welding", "duration_days": 2, "depends_on": []}]'
```

A different city and a different, independent (no `depends_on`) work
pair.

**Point out:** the CLI overrides both the city and the work list
end-to-end with no code change — `agent/main.py`'s `main()` reads
`sys.argv[1]`/`sys.argv[2]` directly.

---

## 12. A prepared invalid input

```
uv run python -m agent.main "Kyiv" '[{"work_code": "concrete_pouring", "duration_days": 1, "depends_on": []}]'
```

Note `concrete_pouring` — not a real work code; the real one is
`concrete_pour`.

**Point out:** `work_code` is a Pydantic `WorkCode` enum on every
BuildWindow tool's input schema, so this becomes a validation failure at
the MCP boundary the moment the model tries to call a BuildWindow tool
with it — before any tool body runs. The error message lists all valid
codes (per `docs/tool-contracts.md` and `DECISIONS.md`'s
`unknown_work_code` entry). Expect the model to either self-correct after
seeing the validation error, or explain the invalid input to the user.

---

## 13. Trace one value end-to-end, by file and function

Trace `temp_min_c` for Longyearbyen, 2026-08-23, in this exact order —
this value is a genuine real per-day aggregate (unlike
`wind_ms`/`humidity_pct`, which are a constant current-conditions proxy
repeated across every day — see step 5's note — a fine documented
limitation, but a weak choice to trace end-to-end since it never varies
by day; temperature is the real per-day signal and is what actually
drove the 4b/4c reschedule):

**a.** OpenWeather's raw response — the external `mcp-openweather`
binary's `weather` tool returns one **plain-text** block (not JSON;
confirmed by reading its source — see `docs/tool-contracts.md`). The
forecast section's real entries for 2026-08-23 (from
`fixtures/weather_longyearbyen.txt`) read `Low: 3.88`, `Low: 3.77`,
`Low: 4.08`, `Low: 4.57`, `Low: 4.79`, `Low: 5.32`, `Low: 5.16`,
`Low: 4.96` (8 three-hour slots).

**b.** `agent/main.py`'s `_get_raw_weather_text` gets this raw text
(either via a live low-level MCP call, or read from a replay fixture —
either way, the same next step runs) and hands it to
`agent/normalize.py`'s `normalize_forecast` (via `_daily_forecast_from_text`).
That function's `_FORECAST_ENTRY_RE` regex extracts each 3-hour entry's
`Low`/`High`, groups them by calendar date, and computes
`temp_min_c = min(low for low, _ in slots)` for 2026-08-23 —
`min(3.88, 3.77, 4.08, 4.57, 4.79, 5.32, 5.16, 4.96) = 3.77` —
deterministic, tested Python (`tests/test_normalization.py`), not model
reasoning. See `DECISIONS.md`'s "Normalization moved from LLM-prompt
instructions to a pure, unit-tested Python function" entry for why this
is code, not a model-interpreted step.

**c.** `agent/main.py`'s `_build_prompt` embeds the resulting
`{"date": "2026-08-23", "temp_min_c": 3.77, ...}` dict directly as JSON
in the user message sent to the LLM. The model reads this pre-computed
value — it does not aggregate anything itself — and passes it through
verbatim as part of the JSON arguments to a `plan_work_schedule` or
`validate_work_window` tool call.

**d.** `server/main.py`'s tool function receives this as
`request.window.temp_min_c` / inside `request.forecast`, already
validated by Pydantic (-60..60 range) before the function body runs.

**e.** `server/rules.py`'s `evaluate_window()` function reads
`window.temp_min_c` and compares it to `req.temp_min_c` (10.0 for
`exterior_painting`) — the line
`if window.temp_min_c < req.temp_min_c:`. Breached (3.77 < 10.0), so it
calls the internal `_classify()` helper, which computes
`margin = actual_value - limit_value = 3.77 - 10.0 = -6.23` and checks
`abs(margin) <= TEMP_CONDITIONAL_BAND_C` (2.0) — false (6.23 > 2.0), so
this lands as a hard **violation**, not a warning.

**f.** The result becomes a `ConstraintViolation` (in
`server/schemas.py`) with `constraint="temperature_min"`,
`actual_value=3.77`, `margin=-6.23`, embedded in
`ValidateWorkWindowOutput.violations` — a real, live-captured example
(step 4b/4c), alongside a second, independently blocking `humidity`
violation (87% vs. the 80% limit) in the same response's `violations`
list.

**g.** This surfaces back to the model as the tool's JSON output — real
captured values from this phase's live and replay runs (both matched).

**h.** The model reads both entries and, per `agent/main.py`'s system
prompt rule (cite the exact constraint and value), correctly reported
**both** temperature and humidity as blocking causes in its final
natural-language answer, rather than picking one — since both are hard
violations here, unlike an earlier demo city where temperature only
reached the conditional warning band (see `DECISIONS.md`).
