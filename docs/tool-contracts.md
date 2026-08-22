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
Everything below was verified directly: by reading the actual installed
version's Go source (see the note on versioning below), and by live calls
against the real built binary using a low-level MCP client
(`mcp.client.stdio.stdio_client` + `mcp.ClientSession`), not inferred or
guessed.

**Versioning note:** this project builds from
`go install github.com/mschneider82/mcp-openweather@main` (commit
`e032683`, "Fix #5"), not `@latest` (tag `v1.0.0`, one commit behind).
Both were built and compared live: `main` fixes a real bug in `v1.0.0`
(see the compatibility note below) and its forecast template is
otherwise byte-identical — see `DECISIONS.md` for the comparison.

| Contract element | Content |
|---|---|
| Name | `weather` (server name `openweather` in `agent/mcp_config.json`). The LLM session is connected to this server (so it appears in `get_mcp_status()` discovery, alongside `buildwindow`), but the model is never allowed to call it — `disallowed_tools=["mcp__openweather__weather"]` blocks it structurally, and `agent/main.py` calls it directly via a low-level MCP client before the LLM session ever starts (see `docs/design-rationale.md` and `DECISIONS.md`). |
| Purpose | In this project, `agent/main.py` calls it once per run to get current conditions and a 5-day/3-hour forecast for the requested city, then deterministically aggregates it (`agent/normalize.py`) into daily figures before ever invoking the LLM. |
| Model-facing description | `Retrieves current and forecast weather information for a given location.` (verbatim, from the `main`-branch build's tool registration — confirmed via live `list_tools()`; `v1.0.0` advertises slightly different wording, `Get current and forecast weather information for a specific City`). |
| Input schema (real, from a live `list_tools()` call) | `city` (string, required): `"Location to get weather. If location has a space, wrap the location in double quotes."` `units` (string, default `"c"`): `"Temperature units (celsius\|fahrenheit\|kelvin) - default: c"`. `lang` (string, default `"en"`): `"Language for weather descriptions - default: en"`. **Compatibility note:** tag `v1.0.0` reads `units`/`lang` from the call arguments with a bare type assertion and no fallback when the key is entirely absent, so an omitted `lang` becomes `""`, which the underlying weather library rejects with `language unavailable` — even though the schema's own declared default is `"en"`. Commit `e032683` ("Fix #5") on `main`, which this project now builds from, adds defensive handling and the same omitted-`lang` call succeeds — confirmed live on both. This project's `agent/main.py` always passes `city`, `units="c"`, and `lang="en"` explicitly on every call regardless, since that costs nothing and removes any dependency on which version is installed. |
| Output schema (real, from source + live calls) | **Not JSON.** The handler renders a Go `text/template` into a single plain-text content block (`CallToolResult.content[0].text`; `structured_content` is always `None`). The text has two sections: `Current weather for <city>:` (conditions, current temp/high/low, pressure, humidity, feels-like, wind speed/degree, sunrise/sunset) followed by `Weather Forecast for <city>:` with one repeated block per 3-hour forecast entry — but **each forecast entry carries only `Date & Time`, `Conditions`, `Temp`, `High`, `Low`. Wind speed, humidity and precipitation are not present per forecast entry at all** — only in the single current-conditions snapshot, and precipitation isn't present anywhere in the output at all. This is identical between `v1.0.0` and `main` — confirmed by reading and comparing both. `agent/normalize.py` parses this fixed text format with regular expressions (not `json.loads`), aggregates per-day temperature min/max from the forecast entries, and uses the current snapshot's wind/humidity as a constant proxy applied to every day (a real limitation of this upstream tool, not a shortcut taken by this project) — precipitation is always `0.0` through this integration. |
| Error conditions (real, verified live) | **This tool cannot distinguish failure causes at all.** `getCurrent`/`getForecast5` in the source discard the error return of the underlying weather-fetch calls entirely — true of both `v1.0.0` and `main`. A missing API key, an invalid API key, an unrecognized city, and an unreachable OpenWeather API all render **identically**: `is_error=false`, with the template executed against a zero-valued struct — an empty city name, all-zero current readings, and **zero forecast entries**. Verified live with a genuinely valid, active `OWM_API_KEY` in play (not just an absent one): `("Kyivv", <the real valid key>)` and `("Kyiv", "GARBAGE_KEY_NOT_REAL_00000")` produced byte-for-byte identical hollow output — this upstream tool truly cannot distinguish an invalid city from an invalid key even when a working key exists elsewhere in the same environment. The only distinguishable failure mode is the binary/subprocess being unreachable at all (confirmed separately as a real Python-level connection exception, e.g. `[WinError 2] The system cannot find the file specified`, when the configured command doesn't resolve) — this happens before any tool call is attempted. `agent/normalize.py`'s `normalize_forecast` therefore has exactly one usable signal: an empty result means "no usable forecast," full stop; `agent/main.py` treats that as `Forecast unavailable`. |
| Side effects | None from this project's perspective (an outbound HTTPS call to the OpenWeather API is made by the external server process, not by BuildWindow or the agent's own code). |
| Example | **Real successful response**, captured live with a genuinely valid `OWM_API_KEY` (city `"Kyiv"`, `units="c"`, `lang="en"`; trimmed to the current-conditions section plus 2 of the 40 real forecast entries returned — no key appears anywhere in this text): `is_error: False`, `content[0].text` (trimmed): `"Current weather for Kyiv:\n    Conditions:  clear sky \n    Now:         34.29 metric\n    High:        34.29 metric\n    Low:         34.29 metric\n\tPressure:    1006\n\tHumidity:    30\n\tFeelsLike:   33.68\n\tWind Speed:  0.89\n\tWind Degree:    89\n\tSunrise:     1787367408 Unixtime\n\tSunset:      1787418323 Unixtime\nWeather Forecast for Kyiv:\nDate & Time: 2026-08-22 15:00:00 +0000 UTC\nConditions:  Clear clear sky\nTemp:        34.29\nHigh:        35.32\nLow:         34.29\n\nDate & Time: 2026-08-22 18:00:00 +0000 UTC\nConditions:  Clear clear sky\nTemp:        31.45\nHigh:        31.45\nLow:         25.76\n\n...(38 more 3-hour entries across 5 more days)..."`. For comparison, the hollow/failure-mode response (missing or invalid key, or an unrecognized city) looks like: `"Current weather for :\n    Conditions: \n    Now:         0 metric\n    High:        0 metric\n    Low:         0 metric\n...\nWeather Forecast for :\n\n"` — empty city name, all-zero readings, zero forecast entries; both shapes are reproduced verbatim in `tests/test_normalization.py`. |
