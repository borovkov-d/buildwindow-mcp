"""Pydantic v2 models for the BuildWindow MCP server.

Every model forbids extra fields and documents each field with
`Field(description=...)`; those descriptions are surfaced to the calling
model as part of each tool's JSON Schema.
"""

from __future__ import annotations

from datetime import date as date_
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from server.errors import InvalidLookupCriteriaError, InvalidWeatherWindowError


class WorkCode(StrEnum):
    """The 12 construction work types known to the BuildWindow dataset."""

    CONCRETE_POUR = "concrete_pour"
    CONCRETE_FINISHING = "concrete_finishing"
    SCREED_POUR = "screed_pour"
    MASONRY = "masonry"
    EXTERIOR_PAINTING = "exterior_painting"
    FACADE_PLASTERING = "facade_plastering"
    WATERPROOFING = "waterproofing"
    ROOFING_MEMBRANE = "roofing_membrane"
    BITUMEN_ROOFING = "bitumen_roofing"
    STRUCTURAL_WELDING = "structural_welding"
    ASPHALT_PAVING = "asphalt_paving"
    EXCAVATION = "excavation"


class WorkCategory(StrEnum):
    """Broad trade category a work type belongs to."""

    CONCRETE = "concrete"
    FINISHING = "finishing"
    ROOFING = "roofing"
    WELDING = "welding"
    PAVING = "paving"
    EARTHWORKS = "earthworks"


class Verdict(StrEnum):
    """Outcome of evaluating one work type against one day of weather."""

    ALLOWED = "allowed"
    CONDITIONAL = "conditional"
    PROHIBITED = "prohibited"


class ConstraintKind(StrEnum):
    """Which weather constraint a violation or warning refers to."""

    TEMPERATURE_MIN = "temperature_min"
    TEMPERATURE_MAX = "temperature_max"
    WIND = "wind"
    HUMIDITY = "humidity"
    PRECIPITATION = "precipitation"


class UnschedulableReason(StrEnum):
    """Why the planner could not place a work in the schedule."""

    NO_SUITABLE_WINDOW = "no_suitable_window"
    DEPENDENCY_BLOCKED = "dependency_blocked"
    HORIZON_EXCEEDED = "horizon_exceeded"


class WeatherWindow(BaseModel):
    """One day of observed or forecast weather."""

    model_config = ConfigDict(extra="forbid")

    date: date_ = Field(description="Calendar date this weather applies to.")
    temp_min_c: float = Field(
        ge=-60,
        le=60,
        description="Minimum air temperature for the day, in degrees Celsius.",
    )
    temp_max_c: float = Field(
        ge=-60,
        le=60,
        description="Maximum air temperature for the day, in degrees Celsius.",
    )
    wind_ms: float = Field(
        ge=0, le=60, description="Wind speed for the day, in metres per second."
    )
    humidity_pct: int = Field(
        ge=0, le=100, description="Relative humidity for the day, in percent."
    )
    precipitation_mm: float = Field(
        ge=0, description="Total precipitation for the day, in millimetres."
    )

    @model_validator(mode="after")
    def _temp_range_is_valid(self) -> WeatherWindow:
        if self.temp_min_c > self.temp_max_c:
            raise ValueError(
                str(
                    InvalidWeatherWindowError(
                        f"temp_min_c ({self.temp_min_c}) must be <= temp_max_c "
                        f"({self.temp_max_c})."
                    )
                )
            )
        return self


class WorkRequirements(BaseModel):
    """The normative weather constraints for one construction work type.

    Mirrors one record of the BuildWindow dataset. All fields are required —
    even base_curing_hours, which may be null for work types with no curing
    stage, but must still be present in the source data.
    """

    model_config = ConfigDict(extra="forbid")

    code: WorkCode = Field(description="Unique snake_case identifier of the work type.")
    name: str = Field(description="Human-readable English name of the work type.")
    category: WorkCategory = Field(description="Trade category of the work type.")
    temp_min_c: float = Field(
        ge=-30,
        le=50,
        description="Minimum air temperature at which this work may proceed, "
        "in Celsius.",
    )
    temp_max_c: float = Field(
        ge=-30,
        le=50,
        description="Maximum air temperature at which this work may proceed, "
        "in Celsius.",
    )
    wind_max_ms: float = Field(
        ge=0,
        le=40,
        description="Maximum wind speed at which this work may proceed, in m/s.",
    )
    humidity_max_pct: int = Field(
        ge=0,
        le=100,
        description="Maximum relative humidity at which this work may proceed, "
        "in percent.",
    )
    precipitation_allowed: bool = Field(
        description="Whether this work may proceed while precipitation is falling."
    )
    base_curing_hours: Annotated[int, Field(gt=0)] | None = Field(
        description=(
            "Nominal curing duration in hours at a 20 C reference temperature, "
            "or null if this work type has no curing stage."
        )
    )
    reference_note: str = Field(
        description="One-sentence explanation of where this work type's "
        "limits come from."
    )

    @model_validator(mode="after")
    def _temp_range_is_valid(self) -> WorkRequirements:
        if self.temp_min_c >= self.temp_max_c:
            raise ValueError(
                f"temp_min_c ({self.temp_min_c}) must be less than temp_max_c "
                f"({self.temp_max_c})."
            )
        return self


class LookupWorkRequirementsInput(BaseModel):
    """Input for lookup_work_requirements: exactly one of work_code/category."""

    model_config = ConfigDict(extra="forbid")

    work_code: WorkCode | None = Field(
        default=None, description="Look up a single work type by its exact code."
    )
    category: WorkCategory | None = Field(
        default=None, description="Look up all work types in this category."
    )

    @model_validator(mode="after")
    def _exactly_one_criterion(self) -> LookupWorkRequirementsInput:
        if (self.work_code is None) == (self.category is None):
            raise ValueError(
                str(
                    InvalidLookupCriteriaError(
                        "Provide exactly one of work_code or category, not "
                        "both or neither. Received "
                        f"work_code={self.work_code!r}, category={self.category!r}."
                    )
                )
            )
        return self


class LookupWorkRequirementsOutput(BaseModel):
    """Output of lookup_work_requirements."""

    model_config = ConfigDict(extra="forbid")

    requirements: list[WorkRequirements] = Field(
        description="Matching work type requirements. Empty if none matched."
    )
    matched_count: int = Field(description="Number of items in requirements.")


class ConstraintViolation(BaseModel):
    """One breached (or near-breached) weather constraint."""

    model_config = ConfigDict(extra="forbid")

    constraint: ConstraintKind = Field(description="Which constraint this refers to.")
    limit_value: float = Field(description="The work type's limit for this constraint.")
    actual_value: float = Field(description="The actual observed/forecast value.")
    margin: float = Field(
        description=(
            "actual_value minus limit_value. Sign convention is not uniform: "
            "for temperature_min a violation is negative (actual below the "
            "limit); for temperature_max, wind, humidity and precipitation a "
            "violation is positive (actual above the limit)."
        )
    )
    message: str = Field(description="Human-readable explanation of this constraint.")


class ValidateWorkWindowInput(BaseModel):
    """Input for validate_work_window."""

    model_config = ConfigDict(extra="forbid")

    work_code: WorkCode = Field(description="The work type to evaluate.")
    window: WeatherWindow = Field(
        description="The day of weather to evaluate it against."
    )


class ValidateWorkWindowOutput(BaseModel):
    """Output of validate_work_window."""

    model_config = ConfigDict(extra="forbid")

    verdict: Verdict = Field(description="Overall verdict for this work-day.")
    violations: list[ConstraintViolation] = Field(
        description="Hard constraint breaches. Any entry here forces "
        "verdict=prohibited."
    )
    warnings: list[ConstraintViolation] = Field(
        description=(
            "Near-boundary breaches within the conditional tolerance band. "
            "Any entry here (with violations empty) forces verdict=conditional."
        )
    )
    window_date: date_ = Field(description="The date that was evaluated.")
    work_code: WorkCode = Field(description="The work type that was evaluated.")


class DailyMaturity(BaseModel):
    """One day's contribution to the Nurse-Saul maturity index."""

    model_config = ConfigDict(extra="forbid")

    date: date_ = Field(description="Calendar date of this day.")
    temp_c: float = Field(description="Temperature supplied for this day.")
    daily_contribution: float = Field(
        description="Degree-hours contributed by this day (0 if temp_c is at "
        "or below the -10 C datum)."
    )
    cumulative: float = Field(
        description="Running total of accumulated maturity through this day, inclusive."
    )


class EstimateCuringTimeInput(BaseModel):
    """Input for estimate_curing_time."""

    model_config = ConfigDict(extra="forbid")

    work_code: WorkCode = Field(description="The work type to estimate curing for.")
    daily_temps_c: list[Annotated[float, Field(ge=-60, le=60)]] = Field(
        min_length=1,
        max_length=30,
        description="Sequence of daily average temperatures starting on start_date.",
    )
    start_date: date_ = Field(
        description="Calendar date of the first supplied temperature."
    )


class EstimateCuringTimeOutput(BaseModel):
    """Output of estimate_curing_time."""

    model_config = ConfigDict(extra="forbid")

    work_code: WorkCode = Field(description="The work type curing was estimated for.")
    required_maturity: float = Field(
        description="Target Nurse-Saul maturity in degree-Celsius-hours."
    )
    accumulated_maturity: float = Field(
        description="Maturity actually accumulated over the supplied days."
    )
    effective_hours: int = Field(
        description="Elapsed hours (in whole days) needed to reach the ready "
        "date, or covered by the supplied days if capped."
    )
    ready_date: date_ | None = Field(
        description="Date the work becomes ready, or null if not reached "
        "within the supplied days."
    )
    capped: bool = Field(
        description="True if the supplied temperature sequence was too "
        "short to reach required_maturity."
    )
    daily_breakdown: list[DailyMaturity] = Field(
        description=(
            "Per-day maturity accounting. Truncated at the ready day if one "
            "was found; includes every supplied day if capped is true."
        )
    )


class PlannedWork(BaseModel):
    """One work item submitted to the scheduler."""

    model_config = ConfigDict(extra="forbid")

    work_code: WorkCode = Field(description="The work type to schedule.")
    duration_days: int = Field(
        ge=1, le=10, description="How many consecutive days this work occupies."
    )
    depends_on: list[WorkCode] = Field(
        default_factory=list,
        description="Work codes (from this same request) that must finish "
        "before this one starts.",
    )


class PlanWorkScheduleInput(BaseModel):
    """Input for plan_work_schedule."""

    model_config = ConfigDict(extra="forbid")

    works: list[PlannedWork] = Field(
        min_length=1, max_length=20, description="The works to schedule."
    )
    forecast: list[WeatherWindow] = Field(
        min_length=1,
        max_length=14,
        description="The weather forecast to schedule against.",
    )


class ScheduledWork(BaseModel):
    """One work item placed in the schedule."""

    model_config = ConfigDict(extra="forbid")

    work_code: WorkCode = Field(description="The work type that was scheduled.")
    start_date: date_ = Field(description="First day this work occupies.")
    end_date: date_ = Field(description="Last day this work occupies, inclusive.")
    worst_verdict: Verdict = Field(
        description="The worst per-day verdict among the days this work occupies."
    )


class UnschedulableWork(BaseModel):
    """One work item that could not be placed in the schedule."""

    model_config = ConfigDict(extra="forbid")

    work_code: WorkCode = Field(
        description="The work type that could not be scheduled."
    )
    reason: UnschedulableReason = Field(description="Why it could not be scheduled.")
    detail: str = Field(
        description="Human-readable explanation, naming the root cause."
    )


class PlanWorkScheduleOutput(BaseModel):
    """Output of plan_work_schedule."""

    model_config = ConfigDict(extra="forbid")

    scheduled: list[ScheduledWork] = Field(description="Works successfully placed.")
    unschedulable: list[UnschedulableWork] = Field(
        description="Works that could not be placed, each with a reason."
    )
    horizon_start: date_ = Field(
        description="First date covered by the supplied forecast."
    )
    horizon_end: date_ = Field(
        description="Last date covered by the supplied forecast."
    )
