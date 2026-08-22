"""Tests for agent.normalize.normalize_forecast.

The fixture text below is a real response, captured live this phase from
the actual built `mcp-openweather` binary (`weather` tool, city "Kyiv")
with a genuinely valid `OWM_API_KEY` -- not a guess at the template's
shape. It is trimmed to a few days/entries for readability; the trimmed
lines are real entries taken verbatim from that live response, not
invented. No API key or other secret appears in this file. The one
constructed part is the "incomplete day" case (below MIN_SLOTS_PER_DAY):
two real entries from the tail of the same live response, presented
together as if that were the whole day, since the live forecast this
phase happened to have every actual calendar day at or above the 3-slot
threshold -- there was no naturally-occurring short day to capture.
"""

from __future__ import annotations

from pathlib import Path

from agent.normalize import normalize_forecast, parse_current_conditions

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"

# Real current-conditions section + two full real days (3 and 8 three-hour
# slots respectively) + one constructed-from-real-entries incomplete day
# (2 slots, below MIN_SLOTS_PER_DAY=3).
SAMPLE_TEXT = """Current weather for Kyiv:
    Conditions:  clear sky
    Now:         34.29 metric
    High:        34.29 metric
    Low:         34.29 metric
\tPressure:    1006
\tHumidity:    30
\tFeelsLike:   33.68
\tWind Speed:  0.89
\tWind Degree:    89
\tSunrise:     1787367408 Unixtime
\tSunset:      1787418323 Unixtime
Weather Forecast for Kyiv:
Date & Time: 2026-08-22 15:00:00 +0000 UTC
Conditions:  Clear clear sky
Temp:        34.29
High:        35.32
Low:         34.29

Date & Time: 2026-08-22 18:00:00 +0000 UTC
Conditions:  Clear clear sky
Temp:        31.45
High:        31.45
Low:         25.76

Date & Time: 2026-08-22 21:00:00 +0000 UTC
Conditions:  Clouds scattered clouds
Temp:        25.47
High:        25.47
Low:         21.06

Date & Time: 2026-08-23 00:00:00 +0000 UTC
Conditions:  Rain light rain
Temp:        17.45
High:        17.45
Low:         17.45

Date & Time: 2026-08-23 03:00:00 +0000 UTC
Conditions:  Clouds scattered clouds
Temp:        16.41
High:        16.41
Low:         16.41

Date & Time: 2026-08-23 06:00:00 +0000 UTC
Conditions:  Clouds few clouds
Temp:        16.75
High:        16.75
Low:         16.75

Date & Time: 2026-08-23 09:00:00 +0000 UTC
Conditions:  Clear clear sky
Temp:        24
High:        24
Low:         24

Date & Time: 2026-08-23 12:00:00 +0000 UTC
Conditions:  Clear clear sky
Temp:        26.26
High:        26.26
Low:         26.26

Date & Time: 2026-08-23 15:00:00 +0000 UTC
Conditions:  Clear clear sky
Temp:        25.47
High:        25.47
Low:         25.47

Date & Time: 2026-08-23 18:00:00 +0000 UTC
Conditions:  Clear clear sky
Temp:        20.79
High:        20.79
Low:         20.79

Date & Time: 2026-08-23 21:00:00 +0000 UTC
Conditions:  Clear clear sky
Temp:        18.05
High:        18.05
Low:         18.05

Date & Time: 2026-08-27 00:00:00 +0000 UTC
Conditions:  Clear clear sky
Temp:        14.89
High:        14.89
Low:         14.89

Date & Time: 2026-08-27 03:00:00 +0000 UTC
Conditions:  Clear clear sky
Temp:        13.77
High:        13.77
Low:         13.77

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

    assert "2026-08-22" in by_date
    day = by_date["2026-08-22"]
    assert day["temp_min_c"] == 21.06  # min(34.29, 25.76, 21.06)
    assert day["temp_max_c"] == 35.32  # max(35.32, 31.45, 25.47)
    assert day["wind_ms"] == 0.89  # from the current-conditions section
    assert day["humidity_pct"] == 30  # from the current-conditions section
    assert day["precipitation_mm"] == 0.0

    assert "2026-08-23" in by_date
    day2 = by_date["2026-08-23"]
    # min/max of the 8 real Low/High values captured for this day
    assert day2["temp_min_c"] == 16.41
    assert day2["temp_max_c"] == 26.26


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
    # 2026-08-27 has only 2 three-hour slots in this fixture, below
    # MIN_SLOTS_PER_DAY=3, so it's dropped entirely rather than computed
    # from partial data.
    assert "2026-08-27" not in dates
    assert dates == {"2026-08-22", "2026-08-23"}


def test_empty_response_yields_no_days():
    # This is how a missing/invalid API key, an unrecognized city, or an
    # unreachable upstream API all surface through this tool: a
    # syntactically successful response with zero forecast entries.
    assert normalize_forecast(EMPTY_RESPONSE_TEXT) == []


def test_kyiv_fixture_parses_to_three_real_days():
    # fixtures/weather_kyiv.txt: a real captured response (see
    # agent/main.py's --forecast-from-file replay mode), trimmed to 3
    # full real calendar days (24 entries: 8+8+8), used both here and as
    # the replay-mode baseline demo input.
    text = (FIXTURES_DIR / "weather_kyiv.txt").read_text(encoding="utf-8")
    days = normalize_forecast(text)
    assert [d["date"] for d in days] == ["2026-08-23", "2026-08-24", "2026-08-25"]
    by_date = {d["date"]: d for d in days}
    assert by_date["2026-08-23"]["temp_min_c"] == 16.41
    assert by_date["2026-08-23"]["temp_max_c"] == 26.26
    assert by_date["2026-08-24"]["temp_min_c"] == 13.58
    assert by_date["2026-08-24"]["temp_max_c"] == 24.44
    assert by_date["2026-08-25"]["temp_min_c"] == 13.43
    assert by_date["2026-08-25"]["temp_max_c"] == 25.12


def test_longyearbyen_fixture_parses_to_three_real_days():
    # fixtures/weather_longyearbyen.txt: a real captured response,
    # trimmed to 3 full real calendar days (24 entries: 8+8+8) -- the
    # replay-mode counterpart to the live Longyearbyen demo run
    # (docs/demo-checklist.md step 4b/4c).
    text = (FIXTURES_DIR / "weather_longyearbyen.txt").read_text(encoding="utf-8")
    days = normalize_forecast(text)
    assert [d["date"] for d in days] == ["2026-08-23", "2026-08-24", "2026-08-25"]
    by_date = {d["date"]: d for d in days}
    assert by_date["2026-08-23"]["temp_min_c"] == 3.77
    assert by_date["2026-08-23"]["temp_max_c"] == 5.32
    assert by_date["2026-08-24"]["temp_min_c"] == 1.72
    assert by_date["2026-08-24"]["temp_max_c"] == 4.24
    assert by_date["2026-08-25"]["temp_min_c"] == 1.23
    assert by_date["2026-08-25"]["temp_max_c"] == 3.01


def test_parse_current_conditions_from_real_fixture():
    text = (FIXTURES_DIR / "weather_longyearbyen.txt").read_text(encoding="utf-8")
    current = parse_current_conditions(text)
    assert current == {
        "city": "Longyearbyen",
        "temp_c": 4.91,
        "conditions": "overcast clouds",
    }


def test_parse_current_conditions_from_empty_response_is_none():
    # Same hollow-response signal normalize_forecast uses: an empty city
    # name means no usable data came back at all.
    assert parse_current_conditions(EMPTY_RESPONSE_TEXT) is None
