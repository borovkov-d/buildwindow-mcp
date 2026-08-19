"""Loads and validates the BuildWindow work-type dataset.

This is the only module that reads server/data/work_types.json from disk.
The dataset is loaded once (via get_dataset()) and kept in memory; tools
never re-read the file per call.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ValidationError

from server.errors import DatasetError, UnknownWorkCodeError
from server.schemas import WorkCategory, WorkCode, WorkRequirements

DEFAULT_DATASET_PATH = Path(__file__).parent / "data" / "work_types.json"


class _WorkTypesFile(BaseModel):
    """Raw shape of work_types.json, validated on load."""

    schema_version: str
    work_types: list[WorkRequirements]


@dataclass(frozen=True)
class Dataset:
    """The validated, in-memory work-type dataset."""

    schema_version: str
    work_types: tuple[WorkRequirements, ...]
    by_code: dict[WorkCode, WorkRequirements] = field(repr=False)

    @classmethod
    def load(cls, path: Path = DEFAULT_DATASET_PATH) -> Dataset:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            parsed = _WorkTypesFile.model_validate(raw)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise DatasetError(f"Failed to load dataset from {path}: {exc}") from exc

        codes = [record.code for record in parsed.work_types]
        if len(codes) != len(set(codes)):
            duplicates = sorted({c for c in codes if codes.count(c) > 1})
            raise DatasetError(
                "Dataset contains duplicate work type codes: "
                f"{', '.join(duplicates)}."
            )

        missing_from_dataset = set(WorkCode) - set(codes)
        if missing_from_dataset:
            raise DatasetError(
                "Dataset is missing records for known work codes: "
                f"{', '.join(sorted(missing_from_dataset))}."
            )

        by_code = {record.code: record for record in parsed.work_types}
        return cls(
            schema_version=parsed.schema_version,
            work_types=tuple(parsed.work_types),
            by_code=by_code,
        )

    def get_by_code(self, code: WorkCode) -> WorkRequirements:
        """Look up one work type's requirements.

        Defensive safety net: WorkCode being a Pydantic enum already rejects
        unknown codes at the MCP input-schema boundary, so this branch is
        unreachable through normal tool calls once the dataset has loaded
        successfully (load() cross-checks every WorkCode has a record). It
        exists as insurance against a future mismatch, and is exercised
        directly in tests by bypassing the type hint.
        """
        try:
            return self.by_code[code]
        except KeyError:
            known = ", ".join(sorted(WorkCode))
            raise UnknownWorkCodeError(
                f"Work code '{code}' is not present in the dataset. "
                f"Known codes: {known}."
            ) from None

    def get_by_category(self, category: WorkCategory) -> list[WorkRequirements]:
        return [record for record in self.work_types if record.category == category]

    @property
    def count(self) -> int:
        return len(self.work_types)


@lru_cache(maxsize=1)
def get_dataset() -> Dataset:
    """Return the process-wide dataset singleton, loading it on first use."""
    return Dataset.load()
