---
name: buildwindow
description: Deterministic go/no-go verdicts for weather-dependent work, checked by the BuildWindow MCP server against weather limits the user supplies. Use when asked "can we paint the facade tomorrow?", "is it warm enough to pour concrete?", "can I fly the drone on Friday?" or "plan these jobs around the forecast".
when_to_use:
  - The user asks whether an outdoor activity with temperature, wind, humidity or rain limits can go ahead on a specific day or days.
  - The user needs several (possibly dependent) weather-sensitive jobs placed into the earliest days the forecast allows.
  - The user asks why a job cannot be done on a given day, or how long concrete will take to cure in cold weather.
  - Forecast source, in order - the user's figures, a weather connector, web search, else ask the user; always name the source; never invent or zero-fill a missing field; the verdict still comes only from the server.
  - Do NOT use for general weather questions or forecasting itself; BuildWindow judges activities against a forecast, it does not produce one.
---

# BuildWindow - deterministic weather-window planning

BuildWindow is an MCP server with four tools. It answers one question
reliably: **given these weather limits and this weather, may this work
proceed - and if not, exactly which limit is breached and by how much?**

**Requires** the BuildWindow MCP server, added with one `claude mcp add`
command (open source, MIT; needs uv and git; no API keys) - see
Installation at the end. Without the server the skill can still fetch the
forecast, but it cannot give a verdict.

## Read first: what the answer depends on

- **The limits come from a dataset, and the built-in one is only an
  example.** The server applies the limits in the JSON dataset it was
  started with: the user's own file (set through `BUILDWINDOW_DATASET`,
  see Installation) or, if none was set, a built-in construction example
  of 12 work types (`concrete_pour`, `exterior_painting`, ...) whose
  thresholds are **illustrative, not taken from any standard**. When
  results come from the built-in example, say so in the answer and never
  present them as compliant with a norm, a data sheet or a regulation.
- **The verdict is only as good as the weather you pass in.** The server
  does not fetch weather; you do (Procedure, step 1), and you tell the user
  where it came from. Many forecast sources are incomplete - web forecasts
  often omit humidity or give rain only in words, and the OpenWeather MCP
  server used by the repository's reference agent gives no precipitation
  and only the *current* wind and humidity. A missing value is never
  invented and never treated as 0, since a precipitation or wind limit
  cannot fire on data that was never there.
- **Five dimensions only:** daily min/max temperature, wind, humidity and
  precipitation. No gusts, visibility, hourly timing or ground conditions.

## The core rule: the verdict comes from the tool, never from you

Every verdict, schedule and curing estimate is computed by deterministic
code. The same input always gives the same answer. Your job is to pass the
data in and report what comes back.

- Never judge by your own reasoning whether a temperature, wind speed,
  humidity or rainfall is acceptable for a work. Call a tool.
- Quote the tool's numbers when explaining a result, e.g. "wind 17 m/s
  exceeds the 15 m/s limit for concrete_pour", not "it's too windy".
- This includes explanations: never say *why* a day was skipped, or that
  another day "should work", from your own reading of the forecast. If you
  want to explain a skipped day or suggest an alternative, check that day
  with `validate_work_window` first and quote the result.
- If no tool call was possible (server not connected, no forecast), say so
  and stop. Do not produce a verdict or schedule without one.

## Procedure

1. **Get the forecast first** - before any BuildWindow call, and even if
   the server turns out to be missing. Use the first source that applies:
   1. Weather figures the user gave in the conversation: use them as given
      and do not search. If they gave only some fields, use those and ask
      for the rest (you may offer to look the rest up).
   2. A weather MCP connector or tool in this session: query it for the
      place and dates.
   3. A search or web-fetch tool available to you: find a forecast for the
      place and dates, preferring a page with daily min/max temperature,
      wind, humidity and precipitation.
   4. None of these: ask the user for the figures.

   Hard rules for this step:
   - **Always name the source** in your answer: "your figures", the
     connector by name, or the website (with its update time if shown),
     so the user can judge how far to trust it.
   - **Never invent a field and never treat a missing one as 0.** If
     humidity is missing, or precipitation is given only in words or as a
     probability ("light rain", "60%"), do not turn it into a number
     yourself: ask the user for that value, and give no verdict until every
     field has a value from a source or from the user.
   - **`temp_min_c` and `temp_max_c` are two different numbers taken from
     the source.** If it gives a single temperature, ask for the other.
   - Unit conversion is arithmetic only (km/h / 3.6 = m/s, F to C); say
     when you converted.
   - Getting the forecast does not replace the verdict: whether the weather
     is acceptable is decided only by the BuildWindow tools.

   Shape each day as `date`, `temp_min_c`, `temp_max_c`, `wind_ms`,
   `humidity_pct`, `precipitation_mm` (C, m/s, %, mm).
2. **Check the server is there.** If the `buildwindow` tools
   (`lookup_work_requirements`, `validate_work_window`,
   `plan_work_schedule`, `estimate_curing_time`) are not available, the
   server is not installed: show the forecast you gathered (with its source
   and any missing fields), show the Installation section below, and stop
   without a verdict.
3. **Map the user's activity to a work code.** The valid codes are the
   `enum` of `work_code` in the tools' input schemas - they come from the
   loaded dataset, so read them there; never invent one. If the request
   fits more than one code (e.g. "work on the facade" could be
   `exterior_painting` or `facade_plastering`), ask, or name the code you
   chose. If nothing fits, say the dataset has no such activity.
   Then call `lookup_work_requirements` for each job: it returns the limits,
   `base_curing_hours`, and **`dataset_is_builtin_example` /
   `dataset_file`, the only reliable way to tell the built-in example from
   the user's own file** - never infer it from `reference_note` wording. If
   the user says they configured their own dataset but
   `dataset_is_builtin_example` is true, tell them it was not picked up
   (see "Check the dataset was loaded").
4. **One job, one or a few days** -> `validate_work_window` per day.
   **Several jobs, or "when can we..."** -> one `plan_work_schedule` call with
   all jobs and the whole forecast (1-14 days); do not walk
   `validate_work_window` day by day yourself.
5. For each job `unschedulable` with reason `no_suitable_window`, call
   `validate_work_window` for it on the first forecast day to get the
   specific breached limit and its numbers. If a job was placed later than
   the first possible day and you explain why, validate the skipped days
   the same way.
6. For each scheduled job whose `base_curing_hours` is not null, call
   `estimate_curing_time` with the daily temperatures of the days it
   occupies and report the real ready date.
7. **Report:** the verdict or schedule; every breach with its numbers;
   which dataset the limits came from (from `dataset_is_builtin_example`
   / `dataset_file`, plus the `reference_note` when relevant); and where
   the forecast came from, including any value the user supplied or you
   converted.

## The four tools

| Tool | Use it to | Key input | Key output |
|---|---|---|---|
| `lookup_work_requirements` | Learn a work type's limits, or list every work type in a category | exactly one of `work_code` or `category` | `requirements[]` (full limit records, incl. `reference_note`), `matched_count`, `dataset_is_builtin_example`, `dataset_file` |
| `validate_work_window` | Check one work against one day | `work_code`, `window` (one day of weather) | `verdict`, `violations[]`, `warnings[]` |
| `plan_work_schedule` | Place several works across a forecast, with dependencies | `works[]` (`work_code`, `duration_days` 1-10, `depends_on[]`), `forecast[]` (1-14 days) | `scheduled[]` (dates, `worst_verdict`), `unschedulable[]` (`reason`, `detail`) |
| `estimate_curing_time` | Real ready date for a work with a curing stage | `work_code`, `daily_temps_c[]`, `start_date` | `ready_date`, or `capped=true` if the days run out first |

How to read a verdict:

- `prohibited` - at least one hard breach (`violations`). Any
  precipitation on a work with `precipitation_allowed=false` is always hard.
- `conditional` - the limit **is** breached, but only by a small margin
  (`warnings`, within 2 C, 1 m/s or 5 % humidity of the limit). Report it
  as "over the limit by X - possible only with risk", with the numbers. If
  the user's limits are hard legal or warranty limits (a product label, a
  regulation), say plainly that `conditional` means the limit is not met.
- `allowed` - no breaches.
- Each breach has `constraint`, `limit_value`, `actual_value`, `margin` and
  a readable `message`. All five checks always run, so the list is
  complete.

## Errors and how to react

Errors arrive as text `[code] message`.

- `unknown_work_code` / `unknown_category` - the message lists every valid
  value. Pick the intended one and retry, or ask the user. Never invent a
  code.
- `invalid_lookup_criteria` - pass exactly one of `work_code`, `category`.
- `cyclic_dependency` - the works' `depends_on` form a loop; tell the user
  which works, do not drop a dependency on your own.
- `no_curing_stage` - this work type has no curing stage; skip curing.
- `invalid_weather_window` or a schema validation error - the weather you
  passed is malformed (e.g. min above max); fix it, don't guess values.
- `unschedulable` entries are **results, not errors**: `horizon_exceeded`
  means the forecast is too short, `dependency_blocked` means a
  prerequisite could not be placed.

## Installation (for the user, once)

This skill needs the BuildWindow MCP server. **Do not install anything
yourself** - show these steps to the user and let them run them.
Requirements: [uv](https://docs.astral.sh/uv/) (it fetches a suitable
Python by itself) and git.

1. Add the server to Claude Code with one command:

   ```bash
   claude mcp add buildwindow -- uvx --from git+https://github.com/borovkov-d/buildwindow-mcp@v0.2.2 buildwindow-server
   ```

   With your own limits (full path; keep the quotes if it contains spaces;
   on Windows a path like `C:\Users\you\limits.json`):

   ```bash
   claude mcp add buildwindow -e BUILDWINDOW_DATASET="/full/path/to/your_limits.json" -- uvx --from git+https://github.com/borovkov-d/buildwindow-mcp@v0.2.2 buildwindow-server
   ```

   `uvx` downloads that tagged release from GitHub once and runs it in an
   isolated environment; nothing is cloned into your project. Without
   `-e BUILDWINDOW_DATASET=...` the server uses the built-in construction
   example. Other MCP clients: command `uvx`, arguments
   `--from git+https://github.com/borovkov-d/buildwindow-mcp@v0.2.2 buildwindow-server`, and the same environment variable.

2. Restart the agent session so the tools appear. The first start
   downloads the server and its two dependencies (`mcp`, `pydantic`); if
   that first connection times out, run the check command below once and
   restart again.

3. **Bring your own limits:** write a JSON file in the format below and
   point `BUILDWINDOW_DATASET` at it as above. To switch to another file
   later, run `claude mcp remove buildwindow` and add it again with the new
   path; the server reads the file once, at start.

To edit the server's code instead, clone the repository - see its README.

### Dataset format

```json
{
  "schema_version": "1.0",
  "work_types": [
    {
      "code": "crop_spraying",
      "name": "Crop spraying by drone",
      "category": "agriculture",
      "temp_min_c": 8,
      "temp_max_c": 25,
      "wind_max_ms": 3,
      "humidity_max_pct": 100,
      "precipitation_allowed": false,
      "base_curing_hours": null,
      "reference_note": "Product X label, section 4."
    }
  ]
}
```

Every field is required in every record, and no other fields are allowed:

- `code`, `category` - lowercase snake_case (`^[a-z][a-z0-9_]*$`); codes
  unique.
- `name`, `reference_note` - free text; put the source of the limits in
  `reference_note`, it is shown to the user.
- `temp_min_c` < `temp_max_c`, both -30...50 C; `wind_max_ms` 0...40 m/s;
  `humidity_max_pct` integer 0...100 (use `100` if humidity doesn't matter);
  `precipitation_allowed` `true`/`false`.
- `base_curing_hours` - positive integer, or `null` for no curing stage
  (only cementitious work uses it).

When helping a user write this file, fill every field and ask for any
limit they did not give rather than guessing it. More detail and a
five-mission example: `references/dataset-format.md` in this skill and
`examples/drone_operations.json` in the repository.

### Check the dataset was loaded

From the agent: any `lookup_work_requirements` result has
`dataset_is_builtin_example` (must be `false` for your own file) and
`dataset_file` (your file's name). Or run the server once by hand with the
same path:

```bash
BUILDWINDOW_DATASET="/full/path/to/your_limits.json" uvx --from git+https://github.com/borovkov-d/buildwindow-mcp@v0.2.2 buildwindow-server
```

(PowerShell: `$env:BUILDWINDOW_DATASET="C:\path\to\your_limits.json"` on
its own line first.) It should print
`BuildWindow MCP server ready: 4 tools, N work types loaded from <your file>`.
Then press Ctrl+C. If it names the built-in `work_types.json` instead, the
variable did not reach the server - check its spelling and quotes. An
invalid file stops the server with a list naming each record, field and
allowed value.

**Network use, stated plainly:** `uvx` downloads the server from GitHub
when it is first started. At runtime the server makes no network calls,
reads only the one dataset file, and needs no API keys or credentials. It
never fetches weather. When this skill looks up a forecast (Procedure,
step 1), it does so with the agent's own web search or weather connector,
and that traffic belongs to the agent, not the server.
