"""Integration tests for the estimate_curing_time MCP tool (spec #19-25).

These call server.main.estimate_curing_time directly (the tool-boundary
function), not server.rules.estimate_curing, so they exercise dataset
lookup + rule evaluation + the _mcp_boundary error-mapping wrapper together.
"""

from __future__ import annotations

import datetime

import pytest
from pydantic import ValidationError

from server.errors import BuildWindowError, NoCuringStageError
from server.main import estimate_curing_time
from server.schemas import EstimateCuringTimeInput, WorkCode


# 19. Exactly the nominal 7 days at 20 C -> ready right on day 7, effective
# hours equal base_curing_hours exactly, not capped.
def test_19_nominal_temp_reaches_ready_on_exact_nominal_day(
    base_date: datetime.date,
) -> None:
    result = estimate_curing_time(
        EstimateCuringTimeInput(
            work_code=WorkCode.CONCRETE_POUR,
            daily_temps_c=[20.0] * 7,
            start_date=base_date,
        )
    )

    assert result.required_maturity == 5040.0  # 168 * 30
    assert result.accumulated_maturity == 5040.0
    assert result.effective_hours == 168
    assert result.capped is False
    assert result.ready_date == base_date + datetime.timedelta(days=6)
    assert len(result.daily_breakdown) == 7


# 20. Colder temperatures push the ready date beyond the nominal 168 hours.
def test_20_colder_temperature_extends_curing_beyond_nominal(
    base_date: datetime.date,
) -> None:
    result = estimate_curing_time(
        EstimateCuringTimeInput(
            work_code=WorkCode.CONCRETE_POUR,
            daily_temps_c=[10.0] * 15,
            start_date=base_date,
        )
    )

    assert result.effective_hours == 264  # 11 * 24
    assert result.capped is False
    assert result.ready_date == base_date + datetime.timedelta(days=10)
    assert result.effective_hours > 168


# 21. Temperatures at/below the -10 C datum contribute nothing at all.
def test_21_temps_at_or_below_datum_contribute_zero(
    base_date: datetime.date,
) -> None:
    result = estimate_curing_time(
        EstimateCuringTimeInput(
            work_code=WorkCode.CONCRETE_POUR,
            daily_temps_c=[-15.0] * 5,
            start_date=base_date,
        )
    )

    assert result.accumulated_maturity == 0.0
    assert result.capped is True
    assert result.ready_date is None
    assert len(result.daily_breakdown) == 5
    for day in result.daily_breakdown:
        assert day.daily_contribution == 0.0


# 22. Too few supplied days: capped is a successful (non-error) result.
def test_22_too_few_days_is_capped_not_an_error(base_date: datetime.date) -> None:
    result = estimate_curing_time(
        EstimateCuringTimeInput(
            work_code=WorkCode.CONCRETE_POUR,
            daily_temps_c=[20.0] * 3,
            start_date=base_date,
        )
    )

    # Explicit: this is a successful return, not a raised exception.
    assert result is not None
    assert result.accumulated_maturity == 2160.0  # 3 * 720
    assert result.capped is True
    assert result.ready_date is None
    assert result.effective_hours == 72
    assert len(result.daily_breakdown) == 3


# 23. A work type with no curing stage raises NoCuringStageError.
def test_23_no_curing_stage_raises(base_date: datetime.date) -> None:
    with pytest.raises(NoCuringStageError) as exc_info:
        estimate_curing_time(
            EstimateCuringTimeInput(
                work_code=WorkCode.STRUCTURAL_WELDING,
                daily_temps_c=[20.0],
                start_date=base_date,
            )
        )

    assert isinstance(exc_info.value, BuildWindowError)
    assert exc_info.value.code == "no_curing_stage"


# 24. Extra supplied days beyond the ready day are not included in the
# breakdown -- it truncates at the ready day.
def test_24_breakdown_truncates_at_ready_day(base_date: datetime.date) -> None:
    result = estimate_curing_time(
        EstimateCuringTimeInput(
            work_code=WorkCode.CONCRETE_POUR,
            daily_temps_c=[20.0] * 10,
            start_date=base_date,
        )
    )

    assert result.capped is False
    assert result.ready_date == base_date + datetime.timedelta(days=6)
    assert len(result.daily_breakdown) == 7


# 25. An empty daily_temps_c list fails Pydantic validation (min_length=1)
# before the tool is ever called.
def test_25_empty_daily_temps_rejected_by_schema(base_date: datetime.date) -> None:
    with pytest.raises(ValidationError):
        EstimateCuringTimeInput(
            work_code=WorkCode.CONCRETE_POUR,
            daily_temps_c=[],
            start_date=base_date,
        )
