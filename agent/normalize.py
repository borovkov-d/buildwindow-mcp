"""Deterministic parsing of mcp-openweather's `weather` tool output into
daily weather figures.

The upstream tool (github.com/mschneider82/mcp-openweather, built here
from the `main` branch per commit `e032683` -- see README's Configuration
section for why `main` and not the `@latest` tag) does **not** return
structured JSON. Its `weather` tool renders a Go text/template into a
single plain-text block: a "Current weather for <city>:" section
followed by a "Weather Forecast for <city>:" section with one repeated
block per 3-hour forecast entry (`Date & Time:`, `Conditions:`, `Temp:`,
`High:`, `Low:`). This was confirmed by reading the installed version's
actual source, not inferred from its README.

Two real, source-verified limitations of the upstream tool shape this
module's design, rather than being invented here:

- The forecast section carries only date/time and temperature per 3-hour
  entry. Wind speed, humidity and precipitation are **not** present per
  forecast entry at all -- only in the single "current conditions"
  snapshot. Wind and humidity are therefore taken as a constant, current-
  conditions-derived approximation applied to every forecast day; this is
  a genuine limitation of the upstream data source, not a shortcut taken
  here. Precipitation is not exposed by this tool in any section, so it
  is always 0.0 through this integration.
- The tool signals **no distinct error condition of any kind**. A missing
  API key, an invalid API key, an unrecognized city, or an unreachable
  upstream API all render the *same* way: `is_error=False` at the MCP
  level, with the template executed against a zero-valued/empty struct
  (an empty city name, all-zero current readings, and zero forecast
  entries). There is nothing to pattern-match for "the key was wrong" vs.
  "the city was wrong" -- both look identical. The only thing that can be
  detected here is "no usable forecast data came back," which is exactly
  what `normalize_forecast` reports by returning an empty list.
"""

from __future__ import annotations

import re
from collections import defaultdict

_FORECAST_ENTRY_RE = re.compile(
    r"Date & Time:\s*(?P<date>\d{4}-\d{2}-\d{2})[^\n]*\n"
    r"Conditions:[^\n]*\n"
    r"Temp:\s*(?P<temp>-?[\d.]+)[^\n]*\n"
    r"High:\s*(?P<high>-?[\d.]+)[^\n]*\n"
    r"Low:\s*(?P<low>-?[\d.]+)"
)
_HUMIDITY_RE = re.compile(r"Humidity:\s*(-?[\d.]+)")
_WIND_SPEED_RE = re.compile(r"Wind Speed:\s*(-?[\d.]+)")
_CITY_NAME_RE = re.compile(r"Current weather for ([^\n:]*):")
_CONDITIONS_RE = re.compile(r"Conditions:\s*([^\n]*)")
_NOW_TEMP_RE = re.compile(r"Now:\s*(-?[\d.]+)")

MIN_SLOTS_PER_DAY = 3


def _extract_first_float(pattern: re.Pattern[str], text: str) -> float | None:
    match = pattern.search(text)
    if match is None:
        return None
    return float(match.group(1))


def normalize_forecast(raw_text: str) -> list[dict]:
    """Aggregate the weather tool's raw text output into one daily figure
    set per calendar date.

    Returns an empty list if the response contains no usable forecast
    entries at all -- through this upstream tool, that is the one and only
    signal available that something went wrong (see module docstring).

    Each returned dict has the same field names as server.schemas.WeatherWindow
    (date as "YYYY-MM-DD", temp_min_c, temp_max_c, wind_ms, humidity_pct,
    precipitation_mm), ready to embed directly as tool-call arguments.
    """
    entries_by_date: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for match in _FORECAST_ENTRY_RE.finditer(raw_text):
        date = match.group("date")
        low = float(match.group("low"))
        high = float(match.group("high"))
        entries_by_date[date].append((low, high))

    if not entries_by_date:
        return []

    current_wind = _extract_first_float(_WIND_SPEED_RE, raw_text)
    current_humidity = _extract_first_float(_HUMIDITY_RE, raw_text)

    daily: list[dict] = []
    for date in sorted(entries_by_date):
        slots = entries_by_date[date]
        if len(slots) < MIN_SLOTS_PER_DAY:
            continue
        daily.append(
            {
                "date": date,
                "temp_min_c": min(low for low, _ in slots),
                "temp_max_c": max(high for _, high in slots),
                "wind_ms": current_wind if current_wind is not None else 0.0,
                "humidity_pct": (
                    round(current_humidity) if current_humidity is not None else 0
                ),
                "precipitation_mm": 0.0,
            }
        )
    return daily


def parse_current_conditions(raw_text: str) -> dict | None:
    """Extract the current-conditions snapshot (city, current temperature,
    conditions description) from the weather tool's raw text response.

    Used for replay mode's offline current-conditions note: reads from
    the same "Current weather for <city>:" section normalize_forecast's
    wind/humidity proxy already comes from, so no live call is needed to
    get this.

    Returns None for the tool's hollow/empty response shape (an empty
    city name) -- the same "no usable data" signal normalize_forecast
    uses for the forecast section.
    """
    city_match = _CITY_NAME_RE.search(raw_text)
    city = city_match.group(1).strip() if city_match else ""
    if not city:
        return None

    temp_match = _NOW_TEMP_RE.search(raw_text)
    conditions_match = _CONDITIONS_RE.search(raw_text)
    return {
        "city": city,
        "temp_c": float(temp_match.group(1)) if temp_match else None,
        "conditions": conditions_match.group(1).strip() if conditions_match else "",
    }
