# Tool contracts

All four BuildWindow tools are registered in `server/main.py` via
`@mcp.tool()` on the `mcp.server.MCPServer` instance, served over stdio.
Every input and output is a Pydantic v2 model with `extra="forbid"`; the
JSON Schema shown to the calling model is generated automatically from
those models, including every `Field(description=...)`.

---

## lookup_work_requirements

| Contract element | Content |
|---|---|
| Name | `lookup_work_requirements` |
| Purpose | Return the normative weather limits for one work type, or every work type in a category. Call this first to learn what limits apply before validating a window or planning a schedule, or to enumerate a category's members. |
| Model-facing description | Return the normative weather constraints for construction work types. Call this first when you need to know the temperature, wind, humidity or precipitation limits that apply to a work type, or to enumerate all work types in a category. Provide either a single work_code or a category, never both. Returns an empty list with matched_count=0 when the category contains no work types; this is a successful result, not an error. |
| Input schema | `LookupWorkRequirementsInput`: `work_code` (`WorkCode` enum, optional, default null) — look up a single work type by exact code. `category` (`WorkCategory` enum, optional, default null) — look up all work types in this category. Exactly one of the two must be set; both or neither is rejected by a `model_validator` as a Pydantic `ValidationError` whose text contains `invalid_lookup_criteria`. |
| Output schema | `LookupWorkRequirementsOutput`: `requirements` (list of `WorkRequirements`, each mirroring one full dataset record — `code`, `name`, `category`, `temp_min_c`, `temp_max_c`, `wind_max_ms`, `humidity_max_pct`, `precipitation_allowed`, `base_curing_hours` nullable, `reference_note`). `matched_count` (int) — always equals `len(requirements)`. An empty list with `matched_count=0` is a normal successful result for a category with no matches (not possible with the current 12-record dataset, but the contract doesn't assume the dataset's shape). |
| Error conditions | `invalid_lookup_criteria` — both or neither of `work_code`/`category` given (Pydantic `ValidationError` at the input-schema boundary, before the tool body runs). `unknown_work_code` — defensive-only; unreachable via a real MCP call since `WorkCode` is a Pydantic enum that already rejects unknown codes at the schema boundary. `internal_error` — any unexpected failure. |
| Side effects | None. |
| Example | Input: `{"work_code": "concrete_pour"}` → Output: `{"requirements": [{"code": "concrete_pour", "name": "Concrete pouring", "category": "concrete", "temp_min_c": 5.0, "temp_max_c": 30.0, "wind_max_ms": 15.0, "humidity_max_pct": 95, "precipitation_allowed": false, "base_curing_hours": 168, "reference_note": "Fresh concrete hydration requires temperatures above 5 C to avoid ice damage to the paste and below 30 C to limit rapid moisture loss and thermal cracking; surface water intrusion during placement compromises the water-cement ratio."}], "matched_count": 1}` (captured from a real run of `lookup_work_requirements(LookupWorkRequirementsInput(work_code=WorkCode.CONCRETE_POUR))`). |

---

## validate_work_window

| Contract element | Content |
|---|---|
| Name | `validate_work_window` |
| Purpose | Check one work type against one day of weather and get back an authoritative, itemized verdict. Use for a single work-day check; use `plan_work_schedule` for placing several works across a forecast. |
| Model-facing description | Evaluate whether one construction work type may proceed during one specific day of weather. Returns a verdict of allowed, conditional or prohibited together with the exact constraints that were breached and by how much. Use this to check a single work-day; use plan_work_schedule when you need to place several works across a forecast. The verdict is computed by deterministic rules, not estimated — treat it as authoritative. |
| Input schema | `ValidateWorkWindowInput`: `work_code` (`WorkCode`, required). `window` (`WeatherWindow`, required) — `date`, `temp_min_c`/`temp_max_c` (float, -60..60, min ≤ max), `wind_ms` (float, 0..60), `humidity_pct` (int, 0..100), `precipitation_mm` (float, ≥0). |
| Output schema | `ValidateWorkWindowOutput`: `verdict` (`allowed` \| `conditional` \| `prohibited`). `violations` (list of `ConstraintViolation` — hard breaches; any entry forces `prohibited`). `warnings` (list of `ConstraintViolation` — near-boundary breaches within the conditional tolerance band; any entry, with `violations` empty, forces `conditional`). `window_date`, `work_code`. Each `ConstraintViolation` has `constraint` (`temperature_min` \| `temperature_max` \| `wind` \| `humidity` \| `precipitation`), `limit_value`, `actual_value`, `margin` (`actual_value - limit_value`), `message`. |
| Error conditions | `unknown_work_code` — defensive-only, unreachable via a real call. `internal_error` — any unexpected failure. A malformed `window` (e.g. `temp_min_c > temp_max_c`) is rejected as a Pydantic `ValidationError` before the tool body runs, not a `BuildWindowError`. |
| Side effects | None. |
| Example | Input: `{"work_code": "concrete_pour", "window": {"date": "2026-08-20", "temp_min_c": 3.0, "temp_max_c": 25.0, "wind_ms": 17.0, "humidity_pct": 60, "precipitation_mm": 0.0}}` → Output: `{"verdict": "prohibited", "violations": [{"constraint": "wind", "limit_value": 15.0, "actual_value": 17.0, "margin": 2.0, "message": "Forecast wind speed 17.0 m/s exceeds the 15.0 m/s maximum allowed for concrete_pour."}], "warnings": [{"constraint": "temperature_min", "limit_value": 5.0, "actual_value": 3.0, "margin": -2.0, "message": "Forecast minimum temperature 3.0 C is below the 5.0 C minimum required for concrete_pour."}], "window_date": "2026-08-20", "work_code": "concrete_pour"}` (captured from a real run — note both a hard wind violation and a within-band temperature warning are reported together, proving the five checks always all run). |

---

## estimate_curing_time

| Contract element | Content |
|---|---|
| Name | `estimate_curing_time` |
| Purpose | Given a run of daily temperatures, find out when a curing work type actually becomes ready, accounting for cold weather extending it past the nominal duration. |
| Model-facing description | Estimate how long a concrete or coating work type needs to cure under a given sequence of daily temperatures, using the Nurse-Saul maturity method. Use this when a work type has a curing stage and cold weather may extend it beyond the nominal duration. Returns the ready date, or capped=true when the supplied temperature sequence is too short to reach the required maturity. Fails with no_curing_stage for work types that have no curing stage at all. |
| Input schema | `EstimateCuringTimeInput`: `work_code` (`WorkCode`, required). `daily_temps_c` (list of float, 1..30 items, each -60..60, required) — one average temperature per day starting on `start_date`. `start_date` (date, required). |
| Output schema | `EstimateCuringTimeOutput`: `work_code`. `required_maturity` (float, °C·h target). `accumulated_maturity` (float, actually accumulated). `effective_hours` (int). `ready_date` (date, nullable — null if not reached within the supplied days). `capped` (bool — true if the supplied days ran out first; this is a successful result, not an error). `daily_breakdown` (list of `DailyMaturity`: `date`, `temp_c`, `daily_contribution`, `cumulative` — truncated at the ready day if one was found, otherwise includes every supplied day). |
| Error conditions | `no_curing_stage` — the work type's `base_curing_hours` is null (e.g. `structural_welding`). `unknown_work_code` — defensive-only. `internal_error` — any unexpected failure. An empty `daily_temps_c` is rejected as a Pydantic `ValidationError` (min_length=1) before the tool body runs. |
| Side effects | None. |
| Example | Input: `{"work_code": "concrete_pour", "daily_temps_c": [20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0], "start_date": "2026-08-20"}` → Output: `{"work_code": "concrete_pour", "required_maturity": 5040.0, "accumulated_maturity": 5040.0, "effective_hours": 168, "ready_date": "2026-08-26", "capped": false, "daily_breakdown": [{"date": "2026-08-20", "temp_c": 20.0, "daily_contribution": 720.0, "cumulative": 720.0}, "...5 more days...", {"date": "2026-08-26", "temp_c": 20.0, "daily_contribution": 720.0, "cumulative": 5040.0}]}` (captured from a real run; at a stable 20 C reference temperature, `effective_hours` lands exactly on `base_curing_hours` — 168 — as expected for `concrete_pour`). |

---

## plan_work_schedule

| Contract element | Content |
|---|---|
| Name | `plan_work_schedule` |
| Purpose | Place several works across a multi-day forecast in one call, honouring declared dependencies, instead of manually walking `validate_work_window` day by day. |
| Model-facing description | Produce a feasible day-by-day schedule for several construction works across a weather forecast, honouring declared dependencies between works. Each work is placed in the earliest window where no day is prohibited. Returns both the scheduled works and the works that could not be placed, each with an explicit reason. Use this instead of repeated validate_work_window calls when planning more than one work. |
| Input schema | `PlanWorkScheduleInput`: `works` (list of `PlannedWork`, 1..20 items) — each has `work_code`, `duration_days` (int, 1..10), `depends_on` (list of `WorkCode`, default empty). `forecast` (list of `WeatherWindow`, 1..14 items). |
| Output schema | `PlanWorkScheduleOutput`: `scheduled` (list of `ScheduledWork`: `work_code`, `start_date`, `end_date`, `worst_verdict` — the worst per-day verdict among its occupied days). `unschedulable` (list of `UnschedulableWork`: `work_code`, `reason` — `no_suitable_window` \| `dependency_blocked` \| `horizon_exceeded`, `detail` naming the root cause). `horizon_start`, `horizon_end`. An empty `scheduled` alongside a non-empty `unschedulable` is a valid successful result. |
| Error conditions | `cyclic_dependency` — the submitted works' `depends_on` edges form a cycle (fails the whole call, not one work). `unknown_work_code` — defensive-only. `internal_error` — any unexpected failure. A `depends_on` entry pointing outside the request is not an error; that work is reported `unschedulable`/`dependency_blocked` instead. |
| Side effects | None. |
| Example | Input: 2 works (`excavation` 1 day, `concrete_pour` 2 days depending on `excavation`) against a 4-day forecast where every day has `temp_min_c=-5.0` (below `concrete_pour`'s 5 C minimum, but above `excavation`'s -10 C minimum) → Output: `{"scheduled": [{"work_code": "excavation", "start_date": "2026-08-20", "end_date": "2026-08-20", "worst_verdict": "allowed"}], "unschedulable": [{"work_code": "concrete_pour", "reason": "no_suitable_window", "detail": "No 2-day window between 2026-08-21 and 2026-08-23 avoids a prohibited day."}], "horizon_start": "2026-08-20", "horizon_end": "2026-08-23"}` (captured from a real run — `excavation` tolerates the cold and schedules; `concrete_pour` cannot and is reported with a specific, actionable reason). |

---

## OpenWeather MCP — `weather` tool

This is the one tool exposed by the external server
(github.com/mschneider82/mcp-openweather), documented here in the context
of how *this project* calls it — not a reproduction of its own README.

| Contract element | Content |
|---|---|
| Name | `weather` (server name `openweather` in `agent/mcp_config.json`, so the agent sees it as `mcp__openweather__weather`) |
| Purpose | In this project, the agent calls it once per run to get current conditions and a 5-day forecast for the requested city, which it then aggregates into daily `WeatherWindow`s before calling `plan_work_schedule`. |
| Model-facing description | Defined by the upstream server, not by this project; it reports current weather and a 5-day/3-hour forecast for a named city. |
| Input schema (as used here) | `city` (string, required) — passed as the plain city name from the agent's input (e.g. `"Kyiv"`). `units` / `lang` (optional) — left unset in this project; the agent's normalization step assumes Celsius. |
| Output schema (as used here) | Raw OpenWeather 5-day/3-hour data: current conditions plus a list of 3-hour interval entries, each with its own timestamp, temperature, wind speed, humidity, and precipitation. **Not** pre-aggregated into daily values — this project's agent (per its system prompt) aggregates 3-hour entries into one `WeatherWindow` per calendar date (`temp_min_c`/`temp_max_c` = min/max of that day's entries, `wind_ms` = max, `humidity_pct` = average, `precipitation_mm` = sum) before calling any BuildWindow tool. |
| Error conditions (as observed here) | An unrecognized city or a missing/invalid `OWM_API_KEY` come back as a plain text string inside the normal tool response (not a protocol-level MCP error), per the upstream source — best-available evidence, not exhaustively documented upstream. A missing binary or failed subprocess launch (this project's actual state — Go is not installed in this environment) surfaces at the MCP connection level as `status: "failed"`, `error: "Connection closed"` in `get_mcp_status()`, before any tool call is even attempted. |
| Side effects | None from this project's perspective (an outbound HTTPS call to the OpenWeather API is made by the external server process, not by BuildWindow or the agent's own code). |
| Example | This project could not build the `mcp-openweather` Go binary in this environment (Go is not installed — see README Limitations / DECISIONS.md), so no successful call was captured live. What *was* captured live: running `agent/main.py` with `openweather` configured but its command unresolvable produced `get_mcp_status()` → `{"name": "openweather", "status": "failed", "error": "Connection closed", "config": {"type": "stdio", "command": "mcp-openweather", "args": []}, "scope": "dynamic"}`, and the agent — per its system prompt's hard rule — refused to fabricate a forecast and reported the missing connection instead of guessing. A successful response's rough shape (per the upstream project's documented interface, not captured here) is a JSON object with a `list` of 3-hour entries, each carrying `dt`/`dt_txt`, `main.temp_min`/`main.temp_max`, `main.humidity`, `wind.speed`, and `rain`/`snow` volume fields — labeled here as documented, not verified, since it was never actually run in this environment. |
