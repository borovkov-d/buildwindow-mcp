"""Tests for agent.normalize.normalize_forecast.

The fixture text below is constructed to match, byte-for-byte in
structure, the actual Go text/template format of the installed
mcp-openweather v1.0.0 binary's `weather` tool output -- confirmed by
reading its source directly (see agent/normalize.py's module docstring)
and by an empty-key live call that rendered the same template against a
zero-valued struct. It is not a captured real API response (no valid
OWM_API_KEY was available), since no proprietary data is involved -- only
the tool's own fixed template shape, which is public source code.
"""

from __future__ import annotations

from agent.normalize import normalize_forecast

# Two full days (3 and 4 three-hour slots) and two incomplete days (2 and
# 1 slots, both below MIN_SLOTS_PER_DAY=3) interleaved, plus a "current
# weather" section supplying the constant wind/humidity proxy.
SAMPLE_TEXT = """Current weather for Kyiv:
    Conditions:  scattered clouds
    Now:         18.5 c
    High:        19.2 c
    Low:         17.1 c
\tPressure:    1013
\tHumidity:    72
\tFeelsLike:   18.1
\tWind Speed:  4.6
\tWind Degree:    210
\tSunrise:     1755840000 Unixtime
\tSunset:      1755890000 Unixtime
Weather Forecast for Kyiv:
Date & Time: 2026-08-20 15:00:00
Conditions:  Clouds scattered clouds
Temp:        18.5
High:        19.2
Low:         17.1

Date & Time: 2026-08-20 18:00:00
Conditions:  Clear clear sky
Temp:        16.2
High:        16.8
Low:         15.9

Date & Time: 2026-08-20 21:00:00
Conditions:  Clear clear sky
Temp:        14.0
High:        14.5
Low:         13.8

Date & Time: 2026-08-21 00:00:00
Conditions:  Clear clear sky
Temp:        12.1
High:        12.3
Low:         11.9

Date & Time: 2026-08-21 03:00:00
Conditions:  Clear clear sky
Temp:        11.0
High:        11.4
Low:         10.6

Date & Time: 2026-08-22 06:00:00
Conditions:  Clouds broken clouds
Temp:        11.0
High:        15.0
Low:         10.0

Date & Time: 2026-08-22 09:00:00
Conditions:  Clouds broken clouds
Temp:        12.5
High:        14.0
Low:         9.5

Date & Time: 2026-08-22 12:00:00
Conditions:  Clouds broken clouds
Temp:        14.0
High:        13.0
Low:         8.0

Date & Time: 2026-08-22 15:00:00
Conditions:  Clouds broken clouds
Temp:        13.0
High:        16.0
Low:         11.0

Date & Time: 2026-08-24 21:00:00
Conditions:  Clouds broken clouds
Temp:        20.0
High:        20.4
Low:         19.7

"""

# Rendering of the same template against a zero-valued struct, as actually
# observed live (empty/invalid key -> the upstream tool returns this
# hollow response rather than any distinct error -- see agent/normalize.py).
EMPTY_RESPONSE_TEXT = (
    "Current weather for :\n"
    "    Conditions: \n"
    "    Now:         0 metric\n"
    "    High:        0 metric\n"
    "    Low:         0 metric\n"
    "\tPressure:    0\n"
    "\tHumidity:    0\n"
    "\tFeelsLike:   0\n"
    "\tWind Speed:  0\n"
    "\tWind Degree:    0\n"
    "\tSunrise:     0 Unixtime\n"
    "\tSunset:      0 Unixtime\n"
    "Weather Forecast for :\n"
    "\n"
)


def test_full_day_computed_correctly():
    days = normalize_forecast(SAMPLE_TEXT)
    by_date = {d["date"]: d for d in days}

    assert "2026-08-20" in by_date
    day = by_date["2026-08-20"]
    assert day["temp_min_c"] == 13.8  # min(17.1, 15.9, 13.8)
    assert day["temp_max_c"] == 19.2  # max(19.2, 16.8, 14.5)
    assert day["wind_ms"] == 4.6  # from the current-conditions section
    assert day["humidity_pct"] == 72  # from the current-conditions section
    assert day["precipitation_mm"] == 0.0

    assert "2026-08-22" in by_date
    day2 = by_date["2026-08-22"]
    assert day2["temp_min_c"] == 8.0  # min(10.0, 9.5, 8.0, 11.0)
    assert day2["temp_max_c"] == 16.0  # max(15.0, 14.0, 13.0, 16.0)


def test_precipitation_is_always_zero():
    # This upstream tool never exposes precipitation in any section, for
    # any entry -- there is no "missing field" case to distinguish from a
    # "present" one, unlike temperature. Every returned day must be 0.0.
    days = normalize_forecast(SAMPLE_TEXT)
    assert days  # sanity: some days did come through
    assert all(d["precipitation_mm"] == 0.0 for d in days)


def test_incomplete_day_is_dropped():
    days = normalize_forecast(SAMPLE_TEXT)
    dates = {d["date"] for d in days}
    # 2026-08-21 has only 2 three-hour slots, 2026-08-24 has only 1 --
    # both below MIN_SLOTS_PER_DAY=3, so neither is computed from partial
    # data; they're dropped entirely.
    assert "2026-08-21" not in dates
    assert "2026-08-24" not in dates
    assert dates == {"2026-08-20", "2026-08-22"}


def test_empty_response_yields_no_days():
    # This is how a missing/invalid API key, an unrecognized city, or an
    # unreachable upstream API all surface through this tool: a
    # syntactically successful response with zero forecast entries.
    assert normalize_forecast(EMPTY_RESPONSE_TEXT) == []
