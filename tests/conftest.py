"""Shared pytest fixtures for the BuildWindow test suite.

Numeric edge-case fixtures below are computed once, here, with the
arithmetic shown in comments — individual test files use these values
directly rather than each re-deriving them.
"""

from __future__ import annotations

import datetime

import pytest

from server.dataset import Dataset, get_dataset
from server.schemas import WeatherWindow, WorkCode, WorkRequirements

# rules.evaluate_window's conditional-band constants, for reference in the
# arithmetic comments below: TEMP_CONDITIONAL_BAND_C = 2.0,
# WIND_CONDITIONAL_BAND_MS = 1.0, HUMIDITY_CONDITIONAL_BAND_PCT = 5.0.


@pytest.fixture
def dataset() -> Dataset:
    """The real, validated work-type dataset."""
    return get_dataset()


@pytest.fixture
def concrete_pour_req(dataset: Dataset) -> WorkRequirements:
    """concrete_pour: temp 5-30 C, wind <=15 m/s, humidity <=95%, no rain."""
    return dataset.get_by_code(WorkCode.CONCRETE_POUR)


@pytest.fixture
def excavation_req(dataset: Dataset) -> WorkRequirements:
    """excavation: temp -10..40 C, wind <=20 m/s, humidity <=100%, rain OK."""
    return dataset.get_by_code(WorkCode.EXCAVATION)


@pytest.fixture
def structural_welding_req(dataset: Dataset) -> WorkRequirements:
    """structural_welding: no curing stage (base_curing_hours is null)."""
    return dataset.get_by_code(WorkCode.STRUCTURAL_WELDING)


@pytest.fixture
def base_date() -> datetime.date:
    return datetime.date(2026, 8, 20)


@pytest.fixture
def good_day(base_date: datetime.date) -> WeatherWindow:
    """Comfortably within every concrete_pour limit -> allowed."""
    return WeatherWindow(
        date=base_date,
        temp_min_c=15.0,
        temp_max_c=22.0,
        wind_ms=5.0,
        humidity_pct=50,
        precipitation_mm=0.0,
    )


@pytest.fixture
def cold_day(base_date: datetime.date) -> WeatherWindow:
    """temp_min_c=-5.0 vs concrete_pour's limit of 5.0.

    margin = -5.0 - 5.0 = -10.0, |margin| = 10.0 > 2.0 -> hard violation,
    verdict=prohibited (test #11).
    """
    return WeatherWindow(
        date=base_date,
        temp_min_c=-5.0,
        temp_max_c=22.0,
        wind_ms=5.0,
        humidity_pct=50,
        precipitation_mm=0.0,
    )


@pytest.fixture
def windy_day(base_date: datetime.date) -> WeatherWindow:
    """wind_ms=17.0 vs concrete_pour's limit of 15.0.

    margin = 17.0 - 15.0 = 2.0, |margin| = 2.0 > WIND_CONDITIONAL_BAND_MS
    (1.0) -> hard violation.
    """
    return WeatherWindow(
        date=base_date,
        temp_min_c=15.0,
        temp_max_c=22.0,
        wind_ms=17.0,
        humidity_pct=50,
        precipitation_mm=0.0,
    )


@pytest.fixture
def rainy_day(base_date: datetime.date) -> WeatherWindow:
    """0.2 mm precipitation; concrete_pour disallows any -> prohibited,
    no conditional band exists for precipitation (test #16)."""
    return WeatherWindow(
        date=base_date,
        temp_min_c=15.0,
        temp_max_c=22.0,
        wind_ms=5.0,
        humidity_pct=50,
        precipitation_mm=0.2,
    )


@pytest.fixture
def boundary_day(base_date: datetime.date) -> WeatherWindow:
    """temp_min_c=3.0 vs concrete_pour's limit of 5.0.

    margin = 3.0 - 5.0 = -2.0, |margin| = 2.0 <= TEMP_CONDITIONAL_BAND_C
    (2.0) -> within band inclusive -> conditional, in warnings (test #14).
    """
    return WeatherWindow(
        date=base_date,
        temp_min_c=3.0,
        temp_max_c=22.0,
        wind_ms=5.0,
        humidity_pct=50,
        precipitation_mm=0.0,
    )


@pytest.fixture
def slightly_over_band_day(base_date: datetime.date) -> WeatherWindow:
    """temp_min_c=2.9 vs concrete_pour's limit of 5.0.

    margin = 2.9 - 5.0 = -2.1, |margin| = 2.1 > 2.0 -> hard violation,
    verdict=prohibited (test #15).
    """
    return WeatherWindow(
        date=base_date,
        temp_min_c=2.9,
        temp_max_c=22.0,
        wind_ms=5.0,
        humidity_pct=50,
        precipitation_mm=0.0,
    )


@pytest.fixture
def within_band_1_5_day(base_date: datetime.date) -> WeatherWindow:
    """temp_min_c=3.5 vs concrete_pour's limit of 5.0.

    margin = 3.5 - 5.0 = -1.5, |margin| = 1.5 <= 2.0 -> conditional
    (test #13).
    """
    return WeatherWindow(
        date=base_date,
        temp_min_c=3.5,
        temp_max_c=22.0,
        wind_ms=5.0,
        humidity_pct=50,
        precipitation_mm=0.0,
    )


def daily_forecast(start: datetime.date, days: int, **overrides) -> list[WeatherWindow]:
    """Build `days` consecutive good-weather WeatherWindows starting at
    `start`, with any field in `overrides` applied to every day."""
    fields = dict(
        temp_min_c=15.0,
        temp_max_c=22.0,
        wind_ms=5.0,
        humidity_pct=50,
        precipitation_mm=0.0,
    )
    fields.update(overrides)
    return [
        WeatherWindow(date=start + datetime.timedelta(days=i), **fields)
        for i in range(days)
    ]
