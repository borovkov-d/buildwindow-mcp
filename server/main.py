"""BuildWindow MCP server entry point. Registers the four tools and runs
over stdio. Independent of the agent process: start with

    uv run python -m server.main
"""

from __future__ import annotations

import sys
import traceback
from functools import wraps

from mcp.server import MCPServer

from server import rules
from server.dataset import get_dataset
from server.errors import BuildWindowError, DatasetError, InternalError
from server.schemas import (
    EstimateCuringTimeInput,
    EstimateCuringTimeOutput,
    LookupWorkRequirementsInput,
    LookupWorkRequirementsOutput,
    PlanWorkScheduleInput,
    PlanWorkScheduleOutput,
    ValidateWorkWindowInput,
    ValidateWorkWindowOutput,
)

mcp = MCPServer("BuildWindow")


def _mcp_boundary(func):
    """Map domain exceptions to model-readable text; never leak a raw traceback.

    A BuildWindowError (already formatted as "[code] message" by its own
    __str__) propagates unchanged. Any other exception is unexpected: its
    full traceback goes to stderr only, and the model sees a short
    [internal_error] message instead.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except BuildWindowError:
            raise
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            raise InternalError(f"Unexpected server error: {exc}") from None

    return wrapper


@mcp.tool()
@_mcp_boundary
def lookup_work_requirements(
    request: LookupWorkRequirementsInput,
) -> LookupWorkRequirementsOutput:
    """Return the normative weather constraints for construction work types.
    Call this first when you need to know the temperature, wind, humidity
    or precipitation limits that apply to a work type, or to enumerate all
    work types in a category. Provide either a single work_code or a
    category, never both. Returns an empty list with matched_count=0 when
    the category contains no work types; this is a successful result, not
    an error.
    """
    dataset = get_dataset()
    if request.work_code is not None:
        matches = [dataset.get_by_code(request.work_code)]
    else:
        matches = dataset.get_by_category(request.category)
    return LookupWorkRequirementsOutput(
        requirements=matches, matched_count=len(matches)
    )


@mcp.tool()
@_mcp_boundary
def validate_work_window(
    request: ValidateWorkWindowInput,
) -> ValidateWorkWindowOutput:
    """Evaluate whether one construction work type may proceed during one
    specific day of weather. Returns a verdict of allowed, conditional or
    prohibited together with the exact constraints that were breached and
    by how much. Use this to check a single work-day; use
    plan_work_schedule when you need to place several works across a
    forecast. The verdict is computed by deterministic rules, not
    estimated — treat it as authoritative.
    """
    dataset = get_dataset()
    req = dataset.get_by_code(request.work_code)
    return rules.evaluate_window(req, request.window)


@mcp.tool()
@_mcp_boundary
def estimate_curing_time(
    request: EstimateCuringTimeInput,
) -> EstimateCuringTimeOutput:
    """Estimate how long a concrete or coating work type needs to cure under
    a given sequence of daily temperatures, using the Nurse-Saul maturity
    method. Use this when a work type has a curing stage and cold weather
    may extend it beyond the nominal duration. Returns the ready date, or
    capped=true when the supplied temperature sequence is too short to
    reach the required maturity. Fails with no_curing_stage for work types
    that have no curing stage at all.
    """
    dataset = get_dataset()
    req = dataset.get_by_code(request.work_code)
    return rules.estimate_curing(req, request.daily_temps_c, request.start_date)


@mcp.tool()
@_mcp_boundary
def plan_work_schedule(request: PlanWorkScheduleInput) -> PlanWorkScheduleOutput:
    """Produce a feasible day-by-day schedule for several construction works
    across a weather forecast, honouring declared dependencies between
    works. Each work is placed in the earliest window where no day is
    prohibited. Returns both the scheduled works and the works that could
    not be placed, each with an explicit reason. Use this instead of
    repeated validate_work_window calls when planning more than one work.
    """
    dataset = get_dataset()
    requirements = {
        work.work_code: dataset.get_by_code(work.work_code) for work in request.works
    }
    return rules.plan_schedule(request.works, request.forecast, requirements)


def main() -> None:
    try:
        dataset = get_dataset()
    except DatasetError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    print(
        f"BuildWindow MCP server ready: 4 tools, {dataset.count} work types loaded",
        file=sys.stderr,
    )
    mcp.run()


if __name__ == "__main__":
    main()
