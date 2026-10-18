---
name: buildwindow
description: Decides whether weather-dependent work may go ahead on a given day, and schedules several such works across a forecast, using the BuildWindow MCP server's deterministic rules against weather limits the user supplies. Use when the user asks "can we pour / paint / roof / spray / fly on Tuesday?", "find a weather window for…", "schedule these jobs around the forecast", or "why can't this job run this week?".
when_to_use:
  - The user has a weather forecast (or daily weather figures) and needs a go / no-go verdict for an activity with temperature, wind, humidity or precipitation limits.
  - The user needs several dependent activities placed into the earliest days the weather allows.
  - The user asks how long a cementitious material needs to cure under a run of cold days.
  - Do NOT use for general weather questions, forecasting itself, or activities whose limits are not in the loaded dataset.
---

# BuildWindow — deterministic weather-window planning

BuildWindow is an MCP server with four tools. It answers one question
reliably: **given these weather limits and this weather, may this work
proceed — and if not, exactly which limit is breached and by how much?**

## The core rule: the verdict comes from the tool, never from you

Every verdict, schedule and curing estimate is computed by deterministic
code (pure functions over the dataset and the weather you pass in). The same
input always gives the same answer. Your job is to pass the data in and
report what comes back.

- Never judge by your own reasoning whether a temperature, wind speed,
  humidity or rainfall is acceptable for a work. Call a tool.
- Quote the tool's numbers when explaining a result, e.g. "wind 17 m/s
  exceeds the 15 m/s limit for concrete_pour", not "it's too windy".
- If no tool call was possible (server not connected, no forecast), say so.
  Do not produce a verdict or schedule without one.

## Where the limits come from

The weather limits per work type live in a JSON dataset loaded by the
server at startup:

- **The user's own dataset**, if the `BUILDWINDOW_DATASET` environment
  variable points to one. This is the intended use: the user brings limits
  from their own standards, product data sheets, equipment manuals or
  regulations.
- **Otherwise, a built-in construction example** (12 work types such as
  `concrete_pour`, `exterior_painting`, `roofing_membrane`). Its thresholds
  are **illustrative, not a normative source**. When results come from the
  built-in example, say so, and do not present them as compliant with any
  standard.

`lookup_work_requirements` shows each work type's `reference_note`, which
says where that work type's limits come from. Repeat it when the user asks
why a limit is what it is. The dataset format is described in
`references/dataset-format.md`.

## The four tools

The valid `work_code` and `category` values are listed as an `enum` in each
tool's input schema. They are taken from the loaded dataset, so read them
from the schema instead of guessing.

| Tool | Use it to | Key input | Key output |
|---|---|---|---|
| `lookup_work_requirements` | Learn a work type's limits, or list every work type in a category | exactly one of `work_code` or `category` | `requirements[]` (full limit records), `matched_count` |
| `validate_work_window` | Check one work against one day | `work_code`, `window` | `verdict` (`allowed` / `conditional` / `prohibited`), `violations[]`, `warnings[]` |
| `plan_work_schedule` | Place several works across a forecast, with dependencies | `works[]` (`work_code`, `duration_days` 1–10, `depends_on[]`), `forecast[]` (1–14 days) | `scheduled[]` (dates and `worst_verdict`), `unschedulable[]` (`reason` and `detail`) |
| `estimate_curing_time` | Get the real ready date for a work with a curing stage | `work_code`, `daily_temps_c[]`, `start_date` | `ready_date`, or `capped=true` if the days run out first |

A weather `window` (one forecast day) is: `date`, `temp_min_c`,
`temp_max_c`, `wind_ms`, `humidity_pct` (0–100), and `precipitation_mm`
(at least 0). `temp_min_c` must not be greater than `temp_max_c`.

How to read a verdict:

- `prohibited`: at least one hard breach (`violations`). Any precipitation
  on a work with `precipitation_allowed=false` is always hard.
- `conditional`: only near-boundary breaches (`warnings`), within 2 °C,
  1 m/s or 5 % humidity of the limit. Report these as "possible, with
  risk", and give the numbers.
- `allowed`: no breaches.
- Each breach has `constraint`, `limit_value`, `actual_value`, `margin`
  and a readable `message`. All five checks always run, so the list is
  complete.

## Recommended procedure

1. If you do not know the work codes, read them from the tool schema, or
   call `lookup_work_requirements` with a `category`.
2. Several works → call `plan_work_schedule` once with all of them. Do not
   walk `validate_work_window` day by day yourself.
3. For each work that comes back `unschedulable` with reason
   `no_suitable_window`, call `validate_work_window` for that work on the
   first forecast day. This gives the user the specific breached limit
   and its numbers.
4. For each scheduled work whose `base_curing_hours` is not null, call
   `estimate_curing_time` with the daily temperatures of the days it
   occupies. Report when it is actually ready, not only when the activity
   ends.
5. Report the schedule, every unschedulable work with its cited reason,
   and any curing-adjusted ready dates. Say which dataset the limits came
   from.

## Errors and how to react

Errors arrive as text of the form `[code] message`.

- `unknown_work_code` / `unknown_category`: the message lists every valid
  value. Pick the intended one and retry, or ask the user. Never invent a
  code.
- `invalid_lookup_criteria`: you passed both or neither of `work_code` and
  `category`. Pass exactly one.
- `cyclic_dependency`: the works' `depends_on` form a loop. Tell the user
  which works are involved. Do not drop a dependency on your own.
- `no_curing_stage`: this work type has no curing stage. Skip the curing
  step for it.
- `invalid_weather_window` or a schema validation error: the weather data
  you passed is malformed (for example, min above max). Fix the input and
  do not guess values.
- `unschedulable` entries are **results, not errors**. `horizon_exceeded`
  means the forecast is too short. `dependency_blocked` means a
  prerequisite could not be placed.

## Installation (for the user, once)

This skill needs the BuildWindow MCP server running locally. Do not
install anything yourself. If the `buildwindow` tools are not available,
show the user these steps and let them run them.

Requirements: Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/borovkov-d/buildwindow-mcp.git
cd buildwindow-mcp
uv sync
```

Register the server with the agent. For example, in Claude Code:

```bash
claude mcp add buildwindow -e BUILDWINDOW_DATASET=/absolute/path/to/your_limits.json -- uv --directory /absolute/path/to/buildwindow-mcp run python -m server.main
```

Leave out `-e BUILDWINDOW_DATASET=…` to start with the built-in
construction example. Other MCP clients take the same command
(`uv --directory <repo> run python -m server.main`) and the same
environment variable in their stdio server config.

On startup the server prints
`BuildWindow MCP server ready: 4 tools, N work types loaded from <path>` to
stderr. An invalid dataset stops the server with a message that names the
record, the field and the allowed values.

**What the server does and does not do:** it makes no network calls,
reads only the one dataset file, and needs no API keys or credentials.
It does not fetch weather. The forecast comes from elsewhere: the user, a
weather MCP server, or any other source. Pass it in as daily figures.
