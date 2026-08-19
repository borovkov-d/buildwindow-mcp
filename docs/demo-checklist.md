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

The agent calls `ClaudeSDKClient.get_mcp_status()` (see `agent/main.py`'s
`_print_discovery` function) and prints each configured server's name,
connection status, and discovered tool names to stderr under
`--- MCP server discovery ---`.

**Point out:**
- `buildwindow: connected (tools: lookup_work_requirements,
  validate_work_window, estimate_curing_time, plan_work_schedule)` — all
  4 tools discovered by name.
- `openweather: connected (tools: weather)` — status here depends on
  whether Go + `OWM_API_KEY` are actually set up for this run; if either
  is missing this instead shows `status: "failed"` (see step 10).

---

## 3. A successful call to the OpenWeather tool

No separate command — this happens automatically as the agent's first
tool call once it starts reasoning about the request in step 2 or step 4.
It is visible in the agent's stderr tool-call log, since `agent/main.py`
prints every `[tool call] name(args)` it observes (e.g.
`[tool call] mcp__openweather__weather({"city": "Kyiv"})`).

**Point out:** the raw response contains 3-hour interval entries (each
with its own timestamp, temperature, wind, humidity, precipitation), not
pre-aggregated daily data — this is exactly why the agent has to run an
aggregation step (step 13b) before it can call any BuildWindow tool.

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
(`mcp-openweather`, not part of this repo). It returns raw 3-hour
interval data. BuildWindow's own server (`server/main.py`) never sees
this data directly — only the agent does, and only long enough to
normalize it into `WeatherWindow` objects (`server/schemas.py`) before
calling any BuildWindow tool. BuildWindow's server has zero knowledge of
OpenWeather, HTTP, or any external API.

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
43 passing tests, with clean `ruff`/`black`.

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
uv run python -m agent.main "Kyiv v"
```

(The doubled letter is deliberate — this guarantees it is not a real
city.)

**Expected:** the `weather` tool call returns a "city not found"-style
error as plain text inside the normal tool response (per
`docs/tool-contracts.md`'s documented behavior — this is not a
protocol-level MCP error). Per the agent's system prompt's hard rule
against inventing weather, the agent reports the failure plainly instead
of producing a schedule. No traceback, no fabricated output.

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

**This was actually run live in this dev environment** (Go isn't
installed here either, so the effect is the same connection failure
either way) — the following is genuine captured output, not a
hypothetical:

- `get_mcp_status()` discovery output shows the `openweather` server as
  `status: "failed"`, `error: "Connection closed"`.
- The agent's final message explicitly states that no weather tool is
  available, names the missing connection, and says it is stopping
  rather than guessing at a schedule.

**Point out:** this is direct, confirmed evidence that the "no forecast,
no schedule" hard rule in the system prompt actually holds under a real
connection failure, not just in theory.

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

Trace `wind_ms` for a windy day, in this exact order:

**a.** OpenWeather's raw response — one 3-hour entry's wind speed field
from the external `mcp-openweather` server (outside this repo).

**b.** `agent/main.py`'s `SYSTEM_PROMPT` instructs the model to compute
the day's `wind_ms` as the **maximum** wind speed among that day's
3-hour entries — this aggregation is performed by the model itself, per
the system prompt's explicit step-2 procedure. This is a documented,
deliberate design choice — see `DECISIONS.md`'s "OpenWeather 3-hour to
daily aggregation" entry.

**c.** The model constructs a `WeatherWindow` object (defined in
`server/schemas.py`) with that value as its `wind_ms` field, as part of
the JSON arguments to a `plan_work_schedule` or `validate_work_window`
tool call.

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
