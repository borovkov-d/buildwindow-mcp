"""Domain exceptions and error codes for the BuildWindow MCP server.

Every exception raised here carries a stable `code` and a human/model-readable
`message`. The MCP boundary (server/main.py) formats these as
`[code] message` text so the calling model can read the failure and, where a
list of valid values is included, self-correct without a human in the loop.
"""

from __future__ import annotations


class BuildWindowError(Exception):
    """Base class for all domain errors raised by the BuildWindow server."""

    code: str = "internal_error"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


class UnknownWorkCodeError(BuildWindowError):
    """Raised when a work code is not present in the loaded dataset."""

    code = "unknown_work_code"


class UnknownCategoryError(BuildWindowError):
    """Raised when a category is not present in the loaded dataset."""

    code = "unknown_category"


class InvalidWeatherWindowError(BuildWindowError):
    """Raised when a weather window is internally inconsistent (e.g.
    temp_min > temp_max)."""

    code = "invalid_weather_window"


class NoCuringStageError(BuildWindowError):
    """Raised when curing time is requested for a work type with no curing stage."""

    code = "no_curing_stage"


class CyclicDependencyError(BuildWindowError):
    """Raised when the works submitted to the planner form a dependency cycle."""

    code = "cyclic_dependency"


class InvalidLookupCriteriaError(BuildWindowError):
    """Raised when a lookup request specifies both or neither of work_code/category."""

    code = "invalid_lookup_criteria"


class DatasetError(BuildWindowError):
    """Raised when the on-disk dataset fails to load or validate at startup."""

    code = "dataset_error"


class InternalError(BuildWindowError):
    """Wraps an unexpected exception before it crosses the MCP boundary."""

    code = "internal_error"
