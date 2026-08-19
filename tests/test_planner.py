"""Tests for server.main.plan_work_schedule / server.rules.plan_schedule
(spec test numbers 26-35): scheduling, dependencies, cycles, horizon and
weather-driven infeasibility, and determinism.
"""

from __future__ import annotations

import datetime

import pytest

from server.errors import BuildWindowError, CyclicDependencyError
from server.main import plan_work_schedule
from server.schemas import (
    PlannedWork,
    PlanWorkScheduleInput,
    UnschedulableReason,
    Verdict,
    WeatherWindow,
    WorkCode,
)
from tests.conftest import daily_forecast


# 26. Two independent, dependency-free works over a good-weather horizon
# both get scheduled; nothing is unschedulable.
def test_independent_works_both_scheduled(base_date):
    request = PlanWorkScheduleInput(
        works=[
            PlannedWork(work_code=WorkCode.EXCAVATION, duration_days=1),
            PlannedWork(work_code=WorkCode.CONCRETE_POUR, duration_days=1),
        ],
        forecast=daily_forecast(base_date, 5),
    )
    result = plan_work_schedule(request)

    assert len(result.scheduled) == 2
    scheduled_codes = {sw.work_code for sw in result.scheduled}
    assert scheduled_codes == {WorkCode.EXCAVATION, WorkCode.CONCRETE_POUR}
    assert result.unschedulable == []


# 27. A dependent work starts the day after its dependency ends.
def test_dependent_work_starts_after_dependency_ends(base_date):
    request = PlanWorkScheduleInput(
        works=[
            PlannedWork(work_code=WorkCode.EXCAVATION, duration_days=1),
            PlannedWork(
                work_code=WorkCode.CONCRETE_POUR,
                duration_days=2,
                depends_on=[WorkCode.EXCAVATION],
            ),
        ],
        forecast=daily_forecast(base_date, 5),
    )
    result = plan_work_schedule(request)

    assert result.unschedulable == []
    by_code = {sw.work_code: sw for sw in result.scheduled}
    assert set(by_code) == {WorkCode.EXCAVATION, WorkCode.CONCRETE_POUR}

    excavation = by_code[WorkCode.EXCAVATION]
    concrete_pour = by_code[WorkCode.CONCRETE_POUR]
    assert concrete_pour.start_date == excavation.end_date + datetime.timedelta(days=1)


# 28. A dependency cycle between two works raises CyclicDependencyError.
def test_cyclic_dependency_raises(base_date):
    request = PlanWorkScheduleInput(
        works=[
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
        ],
        forecast=daily_forecast(base_date, 5),
    )

    with pytest.raises(CyclicDependencyError) as exc_info:
        plan_work_schedule(request)
    assert isinstance(exc_info.value, BuildWindowError)
    assert exc_info.value.code == "cyclic_dependency"


# 29. Weather makes every day of the horizon prohibited for concrete_pour,
# but the horizon is easily long enough -> no_suitable_window, not
# horizon_exceeded.
def test_bad_weather_every_day_gives_no_suitable_window(base_date):
    request = PlanWorkScheduleInput(
        works=[PlannedWork(work_code=WorkCode.CONCRETE_POUR, duration_days=2)],
        forecast=daily_forecast(base_date, 5, temp_min_c=-5.0),
    )
    result = plan_work_schedule(request)

    assert result.scheduled == []
    assert len(result.unschedulable) == 1
    assert result.unschedulable[0].reason == UnschedulableReason.NO_SUITABLE_WINDOW


# 30. A work that fails on weather cascades: its dependent becomes
# dependency_blocked, and the detail names the root cause.
def test_dependency_blocked_cascades_from_weather_failure(base_date):
    request = PlanWorkScheduleInput(
        works=[
            PlannedWork(work_code=WorkCode.CONCRETE_POUR, duration_days=2),
            PlannedWork(
                work_code=WorkCode.MASONRY,
                duration_days=1,
                depends_on=[WorkCode.CONCRETE_POUR],
            ),
        ],
        forecast=daily_forecast(base_date, 5, temp_min_c=-5.0),
    )
    result = plan_work_schedule(request)

    assert result.scheduled == []
    by_code = {uw.work_code: uw for uw in result.unschedulable}
    assert set(by_code) == {WorkCode.CONCRETE_POUR, WorkCode.MASONRY}

    assert by_code[WorkCode.CONCRETE_POUR].reason == (
        UnschedulableReason.NO_SUITABLE_WINDOW
    )
    assert by_code[WorkCode.MASONRY].reason == UnschedulableReason.DEPENDENCY_BLOCKED
    assert "concrete_pour" in by_code[WorkCode.MASONRY].detail


# 31. A dependency pointing outside the request marks the work
# dependency_blocked and names the missing dependency.
def test_dependency_outside_request_is_blocked(base_date):
    request = PlanWorkScheduleInput(
        works=[
            PlannedWork(
                work_code=WorkCode.CONCRETE_POUR,
                duration_days=1,
                depends_on=[WorkCode.MASONRY],
            ),
        ],
        forecast=daily_forecast(base_date, 5),
    )
    result = plan_work_schedule(request)

    assert result.scheduled == []
    assert len(result.unschedulable) == 1
    unschedulable = result.unschedulable[0]
    assert unschedulable.work_code == WorkCode.CONCRETE_POUR
    assert unschedulable.reason == UnschedulableReason.DEPENDENCY_BLOCKED
    assert "masonry" in unschedulable.detail


# 32. An empty scheduled list alongside a non-empty unschedulable list is a
# valid, non-error result (reusing test 29's setup).
def test_empty_scheduled_with_unschedulable_is_a_valid_result(base_date):
    request = PlanWorkScheduleInput(
        works=[PlannedWork(work_code=WorkCode.CONCRETE_POUR, duration_days=2)],
        forecast=daily_forecast(base_date, 5, temp_min_c=-5.0),
    )
    result = plan_work_schedule(request)

    assert result.scheduled == []
    assert len(result.unschedulable) == 1


# 33. A work whose duration cannot possibly fit in the horizon (regardless
# of weather) is horizon_exceeded, not no_suitable_window.
def test_duration_longer_than_horizon_gives_horizon_exceeded(base_date):
    request = PlanWorkScheduleInput(
        works=[
            PlannedWork(
                work_code=WorkCode.CONCRETE_POUR, duration_days=5, depends_on=[]
            ),
        ],
        forecast=daily_forecast(base_date, 3),
    )
    result = plan_work_schedule(request)

    assert result.scheduled == []
    assert len(result.unschedulable) == 1
    assert result.unschedulable[0].reason == UnschedulableReason.HORIZON_EXCEEDED


# 34. Determinism: the same input produces the exact same output.
def test_same_input_produces_same_output(base_date):
    forecast = daily_forecast(base_date, 5)
    works = [
        PlannedWork(work_code=WorkCode.EXCAVATION, duration_days=1),
        PlannedWork(
            work_code=WorkCode.CONCRETE_POUR,
            duration_days=2,
            depends_on=[WorkCode.EXCAVATION],
        ),
    ]
    request1 = PlanWorkScheduleInput(works=works, forecast=forecast)
    request2 = PlanWorkScheduleInput(works=works, forecast=forecast)

    result1 = plan_work_schedule(request1)
    result2 = plan_work_schedule(request2)

    assert result1.model_dump() == result2.model_dump()


# 35. A conditional (but not prohibited) day contributes to worst_verdict:
# the work still gets scheduled, with worst_verdict=conditional.
def test_conditional_day_yields_conditional_worst_verdict(base_date):
    forecast = [
        WeatherWindow(
            date=base_date,
            temp_min_c=3.0,
            temp_max_c=22,
            wind_ms=5,
            humidity_pct=50,
            precipitation_mm=0.0,
        ),
        WeatherWindow(
            date=base_date + datetime.timedelta(days=1),
            temp_min_c=15,
            temp_max_c=22,
            wind_ms=5,
            humidity_pct=50,
            precipitation_mm=0.0,
        ),
    ]
    request = PlanWorkScheduleInput(
        works=[PlannedWork(work_code=WorkCode.CONCRETE_POUR, duration_days=2)],
        forecast=forecast,
    )
    result = plan_work_schedule(request)

    assert result.unschedulable == []
    assert len(result.scheduled) == 1
    scheduled = result.scheduled[0]
    assert scheduled.work_code == WorkCode.CONCRETE_POUR
    assert scheduled.start_date == base_date
    assert scheduled.end_date == base_date + datetime.timedelta(days=1)
    assert scheduled.worst_verdict == Verdict.CONDITIONAL
