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

**Architecture note (confirmed this phase, not assumed):** `openweather`
is *not* given to the LLM at all. `agent/main.py` calls it directly via a
low-level MCP client (`mcp.client.stdio.stdio_client` +
`mcp.ClientSession`) before the LLM session even starts, so the raw text
response never reaches the model. Only `buildwindow` is passed into
`ClaudeAgentOptions.mcp_servers`, so only it appears in
`ClaudeSDKClient.get_mcp_status()`.

**Point out, in order:**
- The line `--- weather: fetched and normalized N day(s) of forecast for
  '<city>' ---` on stderr — this *is* the OpenWeather connection's
  evidence, printed by `agent/main.py` right after the direct client call
  succeeds and `agent/normalize.py` produced at least one usable day.
- `--- MCP server discovery (LLM session) ---` printed at the end, from
  `get_mcp_status()`: `buildwindow: connected (tools:
  lookup_work_requirements, validate_work_window, estimate_curing_time,
  plan_work_schedule)` — all 4 tools discovered by name. `openweather`
  will not appear here — that's correct, not a bug (see the architecture
  note above).

---

## 3. A successful call to the OpenWeather tool

No LLM tool call to point at — this connection is deliberately made
*before* the LLM session starts (see step 2's architecture note), by
`agent/main.py`'s `_fetch_daily_forecast` function, using the same
low-level MCP client pattern.

**Point out:** run
`uv run python -m agent.main "Kyiv"` and watch stderr for
`--- weather: fetched and normalized N day(s) of forecast for 'Kyiv' ---`
— that line only appears once `agent/normalize.py`'s `normalize_forecast`
found at least one day with 3+ forecast entries. Also point out (from
`docs/tool-contracts.md`'s OpenWeather section): the raw response is
**plain text**, not JSON, and only carries temperature per 3-hour
forecast entry — wind, humidity and precipitation are not present per
entry at all, only in the single current-conditions snapshot (precip is
absent even there) — this is exactly why a dedicated, unit-tested parser
(`agent/normalize.py`, see `tests/test_normalization.py`) exists instead
of asking the model to eyeball the format.

---

## 4. The full flow where the forecast actually changes the outcome

```
uv run python -m agent.main
```

(No arguments — the built-in demo input: city **Kyiv**, works
`excavation -> concrete_pour (depends on excavation) ->
concrete_finishing (depends on concrete_pour)`.) Let it run to completion.

**Point out:** the final schedule's exact dates depend on the real
forecast at demo time — don't pre-script the output. Instead, point at
*where* in the output the forecast's influence shows up: a work that got
pushed later, marked `conditional`, or reported unschedulable because of
a specific day's numbers. Per the system prompt's hard rule, the agent
must cite the exact breached constraint and value for any such case
(e.g. "wind 17 m/s exceeds the 15 m/s limit") — find that sentence in the
agent's final answer and read it out.

---

## 5. Explain the OpenWeather tool's contract and its role

No command — reference `docs/tool-contracts.md`, section
**"OpenWeather MCP — `weather` tool."**

**Say:** one tool, `weather`, served by an external Go binary
(`mcp-openweather`, not part of this repo). It returns a plain-text
report, not JSON — confirmed by reading its actual source, since the
tool's own `structured_content` is always empty. Neither BuildWindow's
server (`server/main.py`) nor the LLM ever sees this raw text — only
`agent/main.py`'s own Python code does, via a direct MCP client call made
*before* the LLM session starts, and only long enough to parse it
(`agent/normalize.py`) into `WeatherWindow`-shaped daily figures. Worth
mentioning: this upstream tool can't distinguish a bad API key from an
unrecognized city from an unreachable provider — all three come back as
the same "hollow," zero-valued response (see `docs/tool-contracts.md`);
that's a real, source-confirmed limitation of the external tool, not a
gap in this project's own code.

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

**Real captured output** (run live this phase, with the actual
`mcp-openweather` binary built and reachable, no valid `OWM_API_KEY`):

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
through this specific external tool once the binary itself is reachable.
That's a genuine limitation of the upstream tool, disclosed rather than
papered over — say so if asked why the message doesn't specifically say
"city not found."

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

**Real captured output** (run live this phase, with the actual binary
built and reachable, but no key present):

```
Forecast unavailable for 'Kyiv' (the weather tool returned no usable
forecast data for this city (through this upstream tool, a missing/
invalid API key, an unrecognized city, and an unreachable provider are
all indistinguishable -- none of them produce a distinct error)).
Scheduling requires a forecast; no schedule was produced.
```

Byte-for-byte the same shape as step 9's message, for the reason
explained there. **A third, distinguishable failure mode also exists and
was captured separately**: if `mcp-openweather`'s command in
`agent/mcp_config.json` doesn't resolve at all (binary missing/wrong
path), the direct client call raises a real Python exception instead
(observed live: `[WinError 2] The system cannot find the file
specified`), and the message becomes `Forecast unavailable for '<city>'
(could not connect to the weather server (...))` — this is the one case
this project's tooling *can* actually distinguish.

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

Trace `wind_ms` for a windy day, in this exact order (updated this phase
to reflect the real, source-confirmed shape of the OpenWeather tool's
output, and the resulting move of aggregation into tested Python code):

**a.** OpenWeather's raw response — the external `mcp-openweather`
binary's `weather` tool returns one **plain-text** block (not JSON;
confirmed by reading its source — see `docs/tool-contracts.md`). Its
current-conditions section contains a line like `Wind Speed:  4.6`. This
is the *only* place wind speed appears at all — the forecast section's
repeated 3-hour entries carry only date/time and temperature, never wind,
humidity, or precipitation (a real limitation of this specific upstream
tool).

**b.** `agent/main.py`'s `_fetch_daily_forecast` calls this tool directly
via a low-level MCP client (`mcp.client.stdio.stdio_client` +
`mcp.ClientSession`) — **not** via the LLM — and hands the raw text to
`agent/normalize.py`'s `normalize_forecast`. That function's
`_WIND_SPEED_RE` regex extracts the current-conditions wind speed once,
and applies it as a constant `wind_ms` value to every day in the
forecast (since no per-day figure exists to use instead) — this is
deterministic, tested Python (`tests/test_normalization.py`), not model
reasoning. See `DECISIONS.md`'s "Normalization moved from LLM-prompt
instructions to a pure, unit-tested Python function" entry for why.

**c.** `agent/main.py`'s `_build_prompt` embeds the resulting
`{"date": ..., "wind_ms": 4.6, ...}` dict directly as JSON in the user
message sent to the LLM. The model reads this pre-computed value — it
does not aggregate anything itself anymore — and passes it through
verbatim as part of the JSON arguments to a `plan_work_schedule` or
`validate_work_window` tool call.

**d.** `server/main.py`'s tool function (`plan_work_schedule` or
`validate_work_window`) receives this as `request.window.wind_ms` /
inside `request.forecast`, already validated by Pydantic (0..60 range)
before the function body runs.

**e.** `server/rules.py`'s `evaluate_window()` function reads
`window.wind_ms` and compares it to `req.wind_max_ms` — the line
`if window.wind_ms > req.wind_max_ms:`. If breached, it calls the
internal `_classify()` helper, which computes
`margin = actual_value - limit_value` and checks it against the
module-level `WIND_CONDITIONAL_BAND_MS = 1.0` constant to decide
violation vs. warning.

**f.** The result becomes a `ConstraintViolation` (also in
`server/schemas.py`) with `constraint="wind"`,
`actual_value=<the wind_ms value>`, embedded in
`ValidateWorkWindowOutput.violations` or `.warnings` (or, inside the
planner, used to compute a day's `Verdict` which feeds `plan_schedule`'s
window search).

**g.** This surfaces back to the model as the tool's JSON output — e.g.
`"actual_value": 17.0` in `docs/tool-contracts.md`'s real captured
`validate_work_window` example.

**h.** The model reads this and, per `agent/main.py`'s system prompt
rule ("cite the exact constraint and value... e.g. 'wind 17 m/s exceeds
the 15 m/s limit'"), states it in its final natural-language answer to
the user.
