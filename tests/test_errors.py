"""Tests proving every error code in server/errors.py fires correctly,
and that the MCP boundary never leaks a raw traceback to the caller.

Covers spec test numbers 36-38.
"""

from __future__ import annotations

import datetime

import pytest
from pydantic import ValidationError

import server.main as main_module
from server.dataset import Dataset, get_dataset
from server.errors import (
    BuildWindowError,
    CyclicDependencyError,
    DatasetError,
    InvalidWeatherWindowError,
    NoCuringStageError,
    UnknownWorkCodeError,
)
from server.schemas import (
    EstimateCuringTimeInput,
    LookupWorkRequirementsInput,
    PlannedWork,
    PlanWorkScheduleInput,
    ValidateWorkWindowInput,
    WeatherWindow,
    WorkCode,
)

ALL_WORK_CODES = [
    "concrete_pour",
    "concrete_finishing",
    "screed_pour",
    "masonry",
    "exterior_painting",
    "facade_plastering",
    "waterproofing",
    "roofing_membrane",
    "bitumen_roofing",
    "structural_welding",
    "asphalt_paving",
    "excavation",
]


# ---------------------------------------------------------------------------
# Test 36: one assertion per error code
# ---------------------------------------------------------------------------


def test_unknown_work_code_error():
    dataset = get_dataset()
    with pytest.raises(UnknownWorkCodeError) as exc_info:
        # Bypass the WorkCode type hint on purpose: Python allows passing a
        # raw string at runtime even though get_by_code is annotated as
        # taking a WorkCode.
        dataset.get_by_code("bogus_code")
    assert exc_info.value.code == "unknown_work_code"


def test_invalid_weather_window_error(base_date: datetime.date):
    # (a) triggered via the model_validator on WeatherWindow itself.
    with pytest.raises(ValidationError) as exc_info:
        WeatherWindow(
            date=base_date,
            temp_min_c=10,
            temp_max_c=5,
            wind_ms=5,
            humidity_pct=50,
            precipitation_mm=0,
        )
    assert "invalid_weather_window" in str(exc_info.value)

    # (b) the exception class itself is wired correctly, independent of
    # where it gets triggered from.
    assert str(InvalidWeatherWindowError("x")) == "[invalid_weather_window] x"


def test_no_curing_stage_error(base_date: datetime.date):
    with pytest.raises(NoCuringStageError) as exc_info:
        main_module.estimate_curing_time(
            EstimateCuringTimeInput(
                work_code=WorkCode.STRUCTURAL_WELDING,
                daily_temps_c=[20.0],
                start_date=base_date,
            )
        )
    assert exc_info.value.code == "no_curing_stage"


def test_cyclic_dependency_error(base_date: datetime.date):
    from tests.conftest import daily_forecast

    works = [
        PlannedWork(
            work_code=WorkCode.CONCRETE_POUR,
            duration_days=1,
            depends_on=[WorkCode.MASONRY],
        ),
        PlannedWork(
            work_code=WorkCode.MASONRY,
            duration_days=1,
            depends_on=[WorkCode.CONCRETE_POUR],
        ),
    ]
    forecast = daily_forecast(base_date, 5)
    with pytest.raises(CyclicDependencyError) as exc_info:
        main_module.plan_work_schedule(
            PlanWorkScheduleInput(works=works, forecast=forecast)
        )
    assert exc_info.value.code == "cyclic_dependency"


def test_invalid_lookup_criteria_error():
    with pytest.raises(ValidationError) as exc_info:
        LookupWorkRequirementsInput()
    assert "invalid_lookup_criteria" in str(exc_info.value)


def test_dataset_error(tmp_path):
    bad_file = tmp_path / "bad_work_types.json"
    bad_file.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(DatasetError) as exc_info:
        Dataset.load(bad_file)
    assert exc_info.value.code == "dataset_error"


# ---------------------------------------------------------------------------
# Test 37: UnknownWorkCodeError message names every known work code
# ---------------------------------------------------------------------------


def test_unknown_work_code_error_message_lists_all_codes():
    dataset = get_dataset()
    with pytest.raises(UnknownWorkCodeError) as exc_info:
        dataset.get_by_code("bogus_code")
    message = str(exc_info.value)
    for code in ALL_WORK_CODES:
        assert code in message


# ---------------------------------------------------------------------------
# Test 38: unexpected exceptions are logged to stderr but never leak a raw
# traceback to the caller.
# ---------------------------------------------------------------------------


def test_unexpected_exception_is_wrapped_and_logged(
    monkeypatch, capsys, good_day: WeatherWindow
):
    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(main_module.rules, "evaluate_window", _boom)

    with pytest.raises(Exception) as exc_info:
        main_module.validate_work_window(
            ValidateWorkWindowInput(
                work_code=WorkCode.CONCRETE_POUR,
                window=good_day,
            )
        )

    message = str(exc_info.value)
    assert message.startswith("[internal_error]")
    assert "boom" in message
    assert "Traceback" not in message
    assert isinstance(exc_info.value, BuildWindowError)

    captured = capsys.readouterr()
    assert "RuntimeError" in captured.err
    assert "Traceback" in captured.err
