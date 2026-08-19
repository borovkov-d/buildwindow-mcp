# Design rationale

## 1. Why OpenWeather MCP

The entire premise of BuildWindow is that a scheduling decision depends on
data that changes every day and that no local dataset can hold: the actual
weather. `server/data/work_types.json` encodes *static* facts — what
temperature, wind, humidity and precipitation a work type tolerates — and
those facts are legitimately safe to bake into a 12-record file that never
changes at runtime. Whether it will be 3 °C or 22 °C in Kyiv next Tuesday is
not that kind of fact; it is live, external, and the whole reason the
scheduling problem is interesting. A tool that reads local files (Obsidian)
or drives a browser (Playwright) has no bearing on that — neither one can
tell you tomorrow's wind speed. OpenWeather MCP is the one connection in
this project that supplies information the agent could not otherwise have.

Its role in the flow is narrow and specific: the agent calls its one
`weather` tool once per run to get a 5-day/3-hour forecast for the
requested city, aggregates that into daily figures, and only then calls
BuildWindow's tools. If that call fails — wrong city, no key, no
connection — nothing downstream can be trusted, which is why the agent's
system prompt makes "no forecast, no schedule" a hard rule rather than a
suggestion: a fabricated forecast would make every subsequent tool call
look successful while being meaningless.

## 2. Why each custom tool sits at the MCP boundary

The unifying reason, before the four individual ones: a decision that has
to be reproducible and defensible — the same input always yields the same
output, and a person can point at the line of code that produced it — 
cannot live inside a model's free-form reasoning. An LLM asked "is 3 °C
with 17 m/s wind okay for pouring concrete?" might answer differently
depending on phrasing, model version, or plain sampling variance. A
function that only compares numbers to fields on a Pydantic model always
gives the same answer, and that answer can be pytest-asserted. Every
tool below exists because its job is exactly this kind of decision.

- **`lookup_work_requirements`** — the dataset is server-owned ground
  truth. If the agent (or its prompt) baked in "concrete needs 5-30 °C,"
  that number would silently drift out of sync with `work_types.json` the
  moment either side changed. Routing every read through the tool means
  there is exactly one place the numbers live.
- **`validate_work_window`** — the verdict (`allowed`/`conditional`/
  `prohibited`) is the single most important claim this whole project
  makes, and it has to be the same claim regardless of which model is
  driving the agent, or whether a human is testing it directly instead.
  Putting it behind a fixed, typed contract turns "is this weather okay"
  from a judgment call into a pinned, unit-tested fact.
- **`estimate_curing_time`** — the Nurse-Saul maturity calculation is
  exact arithmetic accumulated over up to 30 days; asking a model to
  reliably sum `(T_i - (-10)) * 24` across a month by itself, correctly,
  every time, is asking for trouble a spreadsheet doesn't have. Code
  either gets this right every time or fails a test; a model doing mental
  arithmetic over many rows degrades with length in a way that is hard to
  detect from the outside.
- **`plan_work_schedule`** — placing several dependent works into the
  earliest non-prohibited windows is a search/placement algorithm
  (topological sort plus a greedy first-fit), not a language task.
  Expressing it as a prompt ("here are 8 works and their dependencies,
  figure out a schedule") would be slow, would not guarantee a valid
  topological order was respected, and — critically for a course
  demo — would not be guaranteed to produce the *same* schedule twice for
  the *same* input, which test #34 exists specifically to catch.

## 3. How the tool set supports the workflow

The four tools map onto four distinct granularities of the same problem,
and none of them overlaps another's responsibility:

| Tool | Operates on | Answers |
|---|---|---|
| `lookup_work_requirements` | one dataset record, or a category's worth | "What are the limits?" |
| `validate_work_window` | one work × one day | "Is this specific day okay?" |
| `estimate_curing_time` | one work × a timeline of days | "When will it actually be ready?" |
| `plan_work_schedule` | many works × many days, with dependencies | "What's the whole week's schedule?" |

A user scenario walks these in order: an engineer's work list gets
resolved to constraints (lookup), the forecast gets checked against those
constraints day by day inside the planner's search (validate, called
internally by the planner for every candidate window), curing-sensitive
works get a readiness estimate layered on top (estimate_curing), and the
result is one coherent schedule (plan_schedule) rather than the agent
manually stitching together N separate `validate_work_window` calls and
reasoning about dependencies itself. Each tool is strictly more useful
than a filtered version of another — `estimate_curing_time` cannot be
built out of repeated `validate_work_window` calls (it needs the maturity
formula, not a threshold check), and `plan_work_schedule` cannot be built
out of `lookup_work_requirements` (it needs the search algorithm).

## 4. Boundaries

- **The agent process** (`agent/main.py`) knows: how to load
  `mcp_config.json`, how to start a Claude Agent SDK session with both
  servers configured, and the demo's input shape (city + works list). It
  does not know any weather-suitability formula or scheduling algorithm.
- **The MCP client** (`claude_agent_sdk`, used inside `agent/main.py`)
  knows: the wire protocol, how to launch and talk to stdio subprocesses,
  and tool discovery (`get_mcp_status()`). It has no BuildWindow-specific
  or OpenWeather-specific knowledge at all — it is a generic transport.
- **The BuildWindow server** (`server/main.py`, `rules.py`, `dataset.py`,
  `schemas.py`, `errors.py`) knows: work-type limits, the verdict rules,
  the curing formula, and the scheduling algorithm. It has **zero**
  knowledge of OpenWeather, HTTP, or any external API — it only ever sees
  a `WeatherWindow`, a plain Pydantic model with five numbers and a date,
  regardless of where those numbers came from.
- **The dataset** (`work_types.json`) knows only the 12 work types' static
  thresholds. It has no notion of weather, schedules, or MCP at all — it
  is inert data, read once.
- **The model itself**, driven by `agent/main.py`'s system prompt, knows
  the *procedure* (call the weather tool, aggregate 3-hour entries into
  daily figures using an exact, spelled-out formula, call
  `plan_work_schedule`, call `estimate_curing_time` for curing-sensitive
  works, explain the result) but is explicitly told never to judge
  weather suitability by its own reasoning. The 3-hour→daily aggregation
  is the one numeric step the model performs itself, precisely because it
  is data transformation (min/max/sum/average), not a suitability
  judgment — the suitability judgment always still goes through
  `validate_work_window`/`plan_work_schedule`.

## 5. Trade-offs

- **Local dataset instead of a live norms API.** Buys full determinism,
  offline operation, and testability — and is exactly why fixtures and a
  replay mode are *not* needed for BuildWindow's own tests, since it never
  makes a network call in the first place (see §3 of the spec's own "what
  we don't do" list). Costs realism: a real deployment would want these
  thresholds synced against an actually-maintained source rather than a
  file that only changes when someone edits it by hand.
- **Greedy first-fit planner instead of an optimizer.** A real scheduler
  might minimize total project duration or explore several valid
  schedules and pick the best. A greedy placement (process works in
  topological order, take the first non-prohibited window) is far easier
  to reason about, explain live, and keep deterministic — at the cost of
  not being provably optimal; a work that could start earlier under a
  smarter ordering may end up later than necessary.
- **No resource constraints.** Multiple works can occupy the same
  calendar days, which is unrealistic (a real site has a finite crew and
  finite equipment) but modeling that would turn this into a full
  constraint-satisfaction problem, well beyond a four-tool lab server.
- **The `conditional` tolerance band.** A forecast is not ground truth —
  a predicted 4 °C being off by a degree or two is routine. A single hard
  threshold would either reject work that will probably be fine, or the
  limits themselves would have to be loosened (which would then also
  accept genuinely unsafe conditions). The band is the middle path: it
  surfaces the uncertainty explicitly (`conditional`, with the exact
  margin) instead of hiding it behind a single boolean.

## 6. Limitations

- **The dataset's numeric thresholds are illustrative**, chosen to be
  internally consistent and to produce interesting scheduling scenarios —
  not looked up against ДБН/ДСТУ or any other real standard. Every
  `reference_note` describes the physical mechanism in plain terms and
  deliberately does not cite a clause number.
- **No resource/crew constraints** — works are not competing for shared
  equipment or labor, so the schedule can (and sometimes will) place
  multiple works on the same days.
- **The planning horizon is bounded by the weather provider.** OpenWeather
  MCP's forecast covers 5 days; `PlanWorkScheduleInput.forecast` technically
  accepts up to 14 synthetic entries (useful for tests and for exploring
  scenarios beyond what a live forecast could ever supply), but a real run
  against live data cannot plan further out than the provider allows.
- **The Nurse-Saul maturity method is a simplified curing model** — real
  cement curing also depends on mix design, admixtures, and humidity, none
  of which this project models; `base_curing_hours` is one nominal number
  per work type.
- **One work occupies one continuous block.** There is no support for
  splitting a work across a gap (start, pause for bad weather, resume) —
  if no single contiguous window fits, the work is reported
  unschedulable rather than fragmented.
