"""Deterministic decision logic for BuildWindow. No I/O, no MCP awareness.

Every function here is a pure function of its arguments: the same inputs
always produce the same output. Verdicts, curing estimates and schedules are
computed here and only here — the calling model never judges weather itself.
"""

from __future__ import annotations

from datetime import date, timedelta

from server.errors import CyclicDependencyError, NoCuringStageError
from server.schemas import (
    ConstraintKind,
    ConstraintViolation,
    DailyMaturity,
    EstimateCuringTimeOutput,
    PlannedWork,
    PlanWorkScheduleOutput,
    ScheduledWork,
    UnschedulableReason,
    UnschedulableWork,
    ValidateWorkWindowOutput,
    Verdict,
    WeatherWindow,
    WorkCode,
    WorkRequirements,
)

# --- evaluate_window ---------------------------------------------------
#
# A breach that stays within these tolerances of the limit is reported as a
# warning (verdict=conditional) instead of a hard violation
# (verdict=prohibited). Forecasts carry inherent error, and a work that
# misses its temperature limit by 1 C is a materially different situation
# from one at -15 C; the band turns the tool from a binary pass/fail filter
# into a decision-support signal. Precipitation has no band: any
# precipitation when a work disallows it is always a hard violation.
TEMP_CONDITIONAL_BAND_C = 2.0
WIND_CONDITIONAL_BAND_MS = 1.0
HUMIDITY_CONDITIONAL_BAND_PCT = 5.0


def _classify(
    constraint: ConstraintKind,
    limit_value: float,
    actual_value: float,
    band: float,
    message: str,
) -> tuple[ConstraintViolation, bool]:
    """Build the violation record for an already-detected breach.

    Returns (violation, is_warning). margin = actual_value - limit_value,
    matching the spec's convention even though the sign meaning flips
    between temperature_min (violation => negative) and the other kinds
    (violation => positive); the conditional-band comparison below uses
    abs(margin) so that flip doesn't affect classification.
    """
    margin = actual_value - limit_value
    violation = ConstraintViolation(
        constraint=constraint,
        limit_value=limit_value,
        actual_value=actual_value,
        margin=margin,
        message=message,
    )
    return violation, abs(margin) <= band


def evaluate_window(
    req: WorkRequirements, window: WeatherWindow
) -> ValidateWorkWindowOutput:
    """Evaluate one work type against one day of weather.

    All five constraints are always checked (no short-circuit on the first
    breach), so the result lists every breach, not just the first one found.
    """
    violations: list[ConstraintViolation] = []
    warnings: list[ConstraintViolation] = []

    if window.temp_min_c < req.temp_min_c:
        violation, is_warning = _classify(
            ConstraintKind.TEMPERATURE_MIN,
            req.temp_min_c,
            window.temp_min_c,
            TEMP_CONDITIONAL_BAND_C,
            f"Forecast minimum temperature {window.temp_min_c} C is below "
            f"the {req.temp_min_c} C minimum required for {req.code}.",
        )
        (warnings if is_warning else violations).append(violation)

    if window.temp_max_c > req.temp_max_c:
        violation, is_warning = _classify(
            ConstraintKind.TEMPERATURE_MAX,
            req.temp_max_c,
            window.temp_max_c,
            TEMP_CONDITIONAL_BAND_C,
            f"Forecast maximum temperature {window.temp_max_c} C exceeds "
            f"the {req.temp_max_c} C maximum allowed for {req.code}.",
        )
        (warnings if is_warning else violations).append(violation)

    if window.wind_ms > req.wind_max_ms:
        violation, is_warning = _classify(
            ConstraintKind.WIND,
            req.wind_max_ms,
            window.wind_ms,
            WIND_CONDITIONAL_BAND_MS,
            f"Forecast wind speed {window.wind_ms} m/s exceeds the "
            f"{req.wind_max_ms} m/s maximum allowed for {req.code}.",
        )
        (warnings if is_warning else violations).append(violation)

    if window.humidity_pct > req.humidity_max_pct:
        violation, is_warning = _classify(
            ConstraintKind.HUMIDITY,
            req.humidity_max_pct,
            window.humidity_pct,
            HUMIDITY_CONDITIONAL_BAND_PCT,
            f"Forecast humidity {window.humidity_pct}% exceeds the "
            f"{req.humidity_max_pct}% maximum allowed for {req.code}.",
        )
        (warnings if is_warning else violations).append(violation)

    if window.precipitation_mm > 0 and not req.precipitation_allowed:
        violations.append(
            ConstraintViolation(
                constraint=ConstraintKind.PRECIPITATION,
                limit_value=0.0,
                actual_value=window.precipitation_mm,
                margin=window.precipitation_mm,
                message=f"Forecast precipitation {window.precipitation_mm} mm "
                f"is not allowed for {req.code}.",
            )
        )

    if violations:
        verdict = Verdict.PROHIBITED
    elif warnings:
        verdict = Verdict.CONDITIONAL
    else:
        verdict = Verdict.ALLOWED

    return ValidateWorkWindowOutput(
        verdict=verdict,
        violations=violations,
        warnings=warnings,
        window_date=window.date,
        work_code=req.code,
    )


# --- estimate_curing -----------------------------------------------------

# Nurse-Saul maturity method datum temperature: below this, cement hydration
# is treated as stopped (contribution clamped to 0, not negative).
CURING_DATUM_C = -10.0
# base_curing_hours is interpreted as the nominal curing duration at this
# reference temperature.
CURING_REFERENCE_TEMP_C = 20.0
HOURS_PER_DAY = 24


def estimate_curing(
    req: WorkRequirements, daily_temps_c: list[float], start_date: date
) -> EstimateCuringTimeOutput:
    """Estimate curing time using the Nurse-Saul maturity method.

    M = sum((T_i - T0) * 24h) over the supplied days, T0 = -10 C.
    required_maturity = base_curing_hours * (20 - T0), treating
    base_curing_hours as the nominal duration at a 20 C reference.
    Reaching required_maturity before the supplied days run out is a
    success (ready_date set); running out first is also a success
    (capped=true), not an error — only a work type with no curing stage at
    all is an error (no_curing_stage).
    """
    if req.base_curing_hours is None:
        raise NoCuringStageError(
            f"{req.code} has no curing stage; estimate_curing_time does not apply."
        )

    required_maturity = req.base_curing_hours * (
        CURING_REFERENCE_TEMP_C - CURING_DATUM_C
    )

    cumulative = 0.0
    breakdown: list[DailyMaturity] = []
    ready_date: date | None = None

    for offset, temp_c in enumerate(daily_temps_c):
        day = start_date + timedelta(days=offset)
        contribution = max(0.0, temp_c - CURING_DATUM_C) * HOURS_PER_DAY
        cumulative += contribution
        breakdown.append(
            DailyMaturity(
                date=day,
                temp_c=temp_c,
                daily_contribution=contribution,
                cumulative=cumulative,
            )
        )
        if cumulative >= required_maturity:
            ready_date = day
            break

    capped = ready_date is None
    effective_hours = len(breakdown) * HOURS_PER_DAY

    return EstimateCuringTimeOutput(
        work_code=req.code,
        required_maturity=required_maturity,
        accumulated_maturity=cumulative,
        effective_hours=effective_hours,
        ready_date=ready_date,
        capped=capped,
        daily_breakdown=breakdown,
    )


# --- plan_schedule ---------------------------------------------------


def _topological_order(works: list[PlannedWork]) -> list[PlannedWork]:
    """Kahn's algorithm; ties broken by original input order for reproducibility.

    Only edges whose dependency is itself present in `works` participate in
    cycle detection — a depends_on entry pointing outside the request is a
    dangling reference (handled separately as dependency_blocked), not part
    of a cycle.
    """
    by_code = {w.work_code: w for w in works}
    codes_in_request = set(by_code)
    order_index = {w.work_code: i for i, w in enumerate(works)}

    deps = {
        code: [d for d in work.depends_on if d in codes_in_request]
        for code, work in by_code.items()
    }
    in_degree = {code: 0 for code in by_code}
    dependents: dict[WorkCode, list[WorkCode]] = {code: [] for code in by_code}
    for code, dep_list in deps.items():
        for d in dep_list:
            in_degree[code] += 1
            dependents[d].append(code)

    ready = [code for code, degree in in_degree.items() if degree == 0]
    result: list[WorkCode] = []
    while ready:
        ready.sort(key=lambda c: order_index[c])
        code = ready.pop(0)
        result.append(code)
        for dependent in dependents[code]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                ready.append(dependent)

    if len(result) != len(by_code):
        raise CyclicDependencyError(
            "The submitted works contain a cyclic dependency and cannot be "
            "scheduled."
        )

    return [by_code[code] for code in result]


def plan_schedule(
    works: list[PlannedWork],
    forecast: list[WeatherWindow],
    requirements: dict[WorkCode, WorkRequirements],
) -> PlanWorkScheduleOutput:
    """Greedy day-by-day scheduler. No optimization, no backtracking.

    Works are placed one at a time in topological order, each in the
    earliest contiguous window (>= its earliest allowed start, which is the
    horizon start or the day after its last dependency ends) where no day
    is prohibited. Works are not resource-constrained: multiple works may
    occupy the same calendar days.
    """
    ordered_works = _topological_order(works)
    codes_in_request = {w.work_code for w in works}

    weather_by_date = {w.date: w for w in forecast}
    horizon_start = min(weather_by_date)
    horizon_end = max(weather_by_date)

    scheduled: dict[WorkCode, ScheduledWork] = {}
    unschedulable: dict[WorkCode, UnschedulableWork] = {}

    for work in ordered_works:
        dangling = sorted(d for d in work.depends_on if d not in codes_in_request)
        if dangling:
            unschedulable[work.work_code] = UnschedulableWork(
                work_code=work.work_code,
                reason=UnschedulableReason.DEPENDENCY_BLOCKED,
                detail=(
                    f"Depends on {', '.join(dangling)}, which is not present "
                    "in this request."
                ),
            )
            continue

        blocked_by = next((d for d in work.depends_on if d in unschedulable), None)
        if blocked_by is not None:
            unschedulable[work.work_code] = UnschedulableWork(
                work_code=work.work_code,
                reason=UnschedulableReason.DEPENDENCY_BLOCKED,
                detail=(
                    f"Depends on '{blocked_by}', which could not be "
                    f"scheduled: {unschedulable[blocked_by].detail}"
                ),
            )
            continue

        if work.depends_on:
            earliest_start = max(
                scheduled[d].end_date for d in work.depends_on
            ) + timedelta(days=1)
        else:
            earliest_start = horizon_start

        if earliest_start + timedelta(days=work.duration_days - 1) > horizon_end:
            unschedulable[work.work_code] = UnschedulableWork(
                work_code=work.work_code,
                reason=UnschedulableReason.HORIZON_EXCEEDED,
                detail=(
                    f"Needs {work.duration_days} consecutive day(s) starting "
                    f"no earlier than {earliest_start}, but the forecast "
                    f"horizon ends {horizon_end}."
                ),
            )
            continue

        req = requirements[work.work_code]
        last_start_candidate = horizon_end - timedelta(days=work.duration_days - 1)
        candidate = earliest_start
        placed = False
        while candidate <= last_start_candidate:
            window_dates = [
                candidate + timedelta(days=i) for i in range(work.duration_days)
            ]
            day_weathers = [weather_by_date.get(d) for d in window_dates]
            if all(w is not None for w in day_weathers):
                verdicts = [evaluate_window(req, w).verdict for w in day_weathers]
                if Verdict.PROHIBITED not in verdicts:
                    worst = (
                        Verdict.CONDITIONAL
                        if Verdict.CONDITIONAL in verdicts
                        else Verdict.ALLOWED
                    )
                    scheduled[work.work_code] = ScheduledWork(
                        work_code=work.work_code,
                        start_date=candidate,
                        end_date=window_dates[-1],
                        worst_verdict=worst,
                    )
                    placed = True
                    break
            candidate += timedelta(days=1)

        if not placed:
            unschedulable[work.work_code] = UnschedulableWork(
                work_code=work.work_code,
                reason=UnschedulableReason.NO_SUITABLE_WINDOW,
                detail=(
                    f"No {work.duration_days}-day window between "
                    f"{earliest_start} and {horizon_end} avoids a "
                    "prohibited day."
                ),
            )

    return PlanWorkScheduleOutput(
        scheduled=[scheduled[w.work_code] for w in works if w.work_code in scheduled],
        unschedulable=[
            unschedulable[w.work_code] for w in works if w.work_code in unschedulable
        ],
        horizon_start=horizon_start,
        horizon_end=horizon_end,
    )
