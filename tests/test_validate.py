"""Tests for the validate_work_window MCP tool (spec tests 10-18).

Covers verdict classification (allowed/conditional/prohibited), the
conditional-band boundary behaviour, multi-constraint reporting (no
short-circuit), precipitation's band-less hard-violation rule, and the
schema-level temp_min_c > temp_max_c rejection on WeatherWindow itself.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from server.main import validate_work_window
from server.schemas import (
    ConstraintKind,
    ValidateWorkWindowInput,
    Verdict,
    WeatherWindow,
    WorkCode,
)


# 10. Comfortably good weather -> allowed, no violations, no warnings.
def test_good_day_is_allowed(good_day):
    result = validate_work_window(
        ValidateWorkWindowInput(work_code=WorkCode.CONCRETE_POUR, window=good_day)
    )
    assert result.verdict == Verdict.ALLOWED
    assert result.violations == []
    assert result.warnings == []


# 11. Cold day (margin -10.0) -> prohibited, single temperature_min violation.
def test_cold_day_is_prohibited(cold_day):
    result = validate_work_window(
        ValidateWorkWindowInput(work_code=WorkCode.CONCRETE_POUR, window=cold_day)
    )
    assert result.verdict == Verdict.PROHIBITED
    assert len(result.violations) == 1
    assert result.violations[0].constraint == ConstraintKind.TEMPERATURE_MIN
    assert result.violations[0].margin == -10.0
    assert result.warnings == []


# 12. Two independent hard violations in one window -> both reported, no
# short-circuit on the first breach found.
def test_multiple_violations_all_reported(base_date):
    window = WeatherWindow(
        date=base_date,
        temp_min_c=-5.0,
        temp_max_c=22.0,
        wind_ms=20.0,
        humidity_pct=50,
        precipitation_mm=0.0,
    )
    result = validate_work_window(
        ValidateWorkWindowInput(work_code=WorkCode.CONCRETE_POUR, window=window)
    )
    assert result.verdict == Verdict.PROHIBITED
    assert len(result.violations) >= 2
    constraints = {v.constraint for v in result.violations}
    assert ConstraintKind.TEMPERATURE_MIN in constraints
    assert ConstraintKind.WIND in constraints


# 13. margin -1.5, within the 2.0 C band -> conditional/warning.
def test_within_band_is_conditional(within_band_1_5_day):
    result = validate_work_window(
        ValidateWorkWindowInput(
            work_code=WorkCode.CONCRETE_POUR, window=within_band_1_5_day
        )
    )
    assert result.verdict == Verdict.CONDITIONAL
    assert len(result.warnings) == 1
    assert result.warnings[0].constraint == ConstraintKind.TEMPERATURE_MIN
    assert result.warnings[0].margin == -1.5
    assert result.violations == []


# 14. margin exactly -2.0, band boundary is inclusive -> still conditional.
def test_boundary_is_inclusive_conditional(boundary_day):
    result = validate_work_window(
        ValidateWorkWindowInput(work_code=WorkCode.CONCRETE_POUR, window=boundary_day)
    )
    assert result.verdict == Verdict.CONDITIONAL
    assert len(result.warnings) == 1
    assert result.warnings[0].margin == -2.0
    assert result.violations == []


# 15. margin -2.1, just past the band -> hard violation, prohibited.
def test_slightly_over_band_is_prohibited(slightly_over_band_day):
    result = validate_work_window(
        ValidateWorkWindowInput(
            work_code=WorkCode.CONCRETE_POUR, window=slightly_over_band_day
        )
    )
    assert result.verdict == Verdict.PROHIBITED
    assert len(result.violations) == 1
    assert result.violations[0].margin == pytest.approx(-2.1)
    assert result.warnings == []


# 16. Any precipitation when disallowed is always a hard violation (no band).
def test_rainy_day_precipitation_violation(rainy_day):
    result = validate_work_window(
        ValidateWorkWindowInput(work_code=WorkCode.CONCRETE_POUR, window=rainy_day)
    )
    assert result.verdict == Verdict.PROHIBITED
    assert len(result.violations) == 1
    violation = result.violations[0]
    assert violation.constraint == ConstraintKind.PRECIPITATION
    assert violation.limit_value == pytest.approx(0.0)
    assert violation.actual_value == pytest.approx(0.2)


# 17. Excavation allows precipitation; a window fully within its ranges is
# allowed with no violations at all.
def test_excavation_allows_precipitation(base_date):
    window = WeatherWindow(
        date=base_date,
        temp_min_c=10.0,
        temp_max_c=25.0,
        wind_ms=5.0,
        humidity_pct=50,
        precipitation_mm=5.0,
    )
    result = validate_work_window(
        ValidateWorkWindowInput(work_code=WorkCode.EXCAVATION, window=window)
    )
    assert result.verdict == Verdict.ALLOWED
    assert result.violations == []
    assert result.warnings == []


# 18. Schema-level rejection: temp_min_c > temp_max_c raises ValidationError
# before any rule ever runs.
def test_weather_window_rejects_inverted_temps(base_date):
    with pytest.raises(ValidationError):
        WeatherWindow(
            date=base_date,
            temp_min_c=10.0,
            temp_max_c=5.0,
            wind_ms=5.0,
            humidity_pct=50,
            precipitation_mm=0.0,
        )
