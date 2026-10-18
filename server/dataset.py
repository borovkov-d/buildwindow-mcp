"""Loads and validates the BuildWindow work-type dataset.

This is the only module that reads a dataset file from disk. Which file is
read is decided once, at first use: the path in the BUILDWINDOW_DATASET
environment variable if it is set and non-empty, otherwise the built-in
example dataset at server/data/work_types.json. The dataset is loaded once
(via get_dataset()) and kept in memory; tools never re-read the file per
call, so switching datasets means restarting the server.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from server.errors import DatasetError, UnknownCategoryError, UnknownWorkCodeError
from server.schemas import WorkCategory, WorkCode, WorkRequirements

DEFAULT_DATASET_PATH = Path(__file__).parent / "data" / "work_types.json"
DATASET_ENV_VAR = "BUILDWINDOW_DATASET"


class _WorkTypesFile(BaseModel):
    """Raw shape of a dataset file, validated on load."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str
    work_types: list[WorkRequirements]


def resolve_dataset_path() -> Path:
    """Return the dataset path selected by BUILDWINDOW_DATASET.

    An unset or empty (whitespace-only) variable means "use the built-in
    example dataset" -- empty counts as unset so that a blank
    `BUILDWINDOW_DATASET=` line copied from .env.example changes nothing.
    A relative path is resolved against the server process's working
    directory.
    """
    raw = os.environ.get(DATASET_ENV_VAR, "").strip()
    return Path(raw).expanduser() if raw else DEFAULT_DATASET_PATH


def _describe_location(loc: tuple[Any, ...], raw: Any) -> str:
    """Render a Pydantic error location as `work_types[2] (code 'x').field`."""
    parts: list[str] = []
    record: Any = None
    for i, item in enumerate(loc):
        if isinstance(item, int):
            parts[-1] = f"{parts[-1]}[{item}]"
            if i == 1 and loc[0] == "work_types":
                try:
                    record = raw["work_types"][item]
                except (KeyError, IndexError, TypeError):
                    record = None
        else:
            parts.append(str(item))
    rendered = ".".join(parts) or "(top level)"
    if isinstance(record, dict) and isinstance(record.get("code"), str):
        head, _, tail = rendered.partition(".")
        rendered = f"{head} (code '{record['code']}')" + (f".{tail}" if tail else "")
    return rendered


def _format_validation_error(exc: ValidationError, raw: Any) -> str:
    """Turn a Pydantic ValidationError into a list a first-time dataset
    author can act on: which record, which field, what is wrong, and --
    for missing or unexpected fields -- which fields are allowed."""
    record_fields = ", ".join(WorkRequirements.model_fields)
    file_fields = ", ".join(_WorkTypesFile.model_fields)
    lines = []
    for error in exc.errors():
        loc = tuple(error["loc"])
        where = _describe_location(loc, raw)
        in_record = len(loc) >= 3 and loc[0] == "work_types"
        allowed = record_fields if in_record else file_fields
        kind = error["type"]
        if kind == "missing":
            detail = f"required field is missing (fields: {allowed})"
        elif kind == "extra_forbidden":
            detail = f"unknown field (allowed fields: {allowed})"
        elif kind == "string_pattern_mismatch":
            detail = (
                f"{error['msg']} -- use lowercase snake_case such as "
                f"'survey_mapping' (got {error['input']!r})"
            )
        else:
            detail = error["msg"]
            if error.get("input") is not None and not isinstance(
                error["input"], dict | list
            ):
                detail += f" (got {error['input']!r})"
        lines.append(f"  - {where}: {detail}")
    count = len(lines)
    header = f"{count} problem{'s' if count != 1 else ''} found:"
    return "\n".join([header, *lines])


@dataclass(frozen=True)
class Dataset:
    """The validated, in-memory work-type dataset."""

    schema_version: str
    work_types: tuple[WorkRequirements, ...]
    by_code: dict[WorkCode, WorkRequirements] = field(repr=False)
    source: Path = DEFAULT_DATASET_PATH

    @classmethod
    def load(cls, path: Path = DEFAULT_DATASET_PATH) -> Dataset:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise DatasetError(f"Failed to read dataset file {path}: {exc}") from exc
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise DatasetError(f"Dataset file {path} is not valid JSON: {exc}") from exc
        try:
            parsed = _WorkTypesFile.model_validate(raw)
        except ValidationError as exc:
            raise DatasetError(
                f"Dataset file {path} is invalid. "
                f"{_format_validation_error(exc, raw)}"
            ) from exc

        if not parsed.work_types:
            raise DatasetError(f"Dataset file {path} contains no work types.")

        codes = [record.code for record in parsed.work_types]
        if len(codes) != len(set(codes)):
            duplicates = sorted({c for c in codes if codes.count(c) > 1})
            raise DatasetError(
                "Dataset contains duplicate work type codes: "
                f"{', '.join(duplicates)}."
            )

        by_code = {record.code: record for record in parsed.work_types}
        return cls(
            schema_version=parsed.schema_version,
            work_types=tuple(parsed.work_types),
            by_code=by_code,
            source=path,
        )

    @property
    def codes(self) -> tuple[str, ...]:
        """Every work code, in dataset order."""
        return tuple(record.code for record in self.work_types)

    @property
    def categories(self) -> tuple[str, ...]:
        """Every distinct category, in order of first appearance."""
        return tuple(dict.fromkeys(record.category for record in self.work_types))

    def get_by_code(self, code: WorkCode) -> WorkRequirements:
        """Look up one work type's requirements.

        WorkCode only checks the identifier's shape, so this is where an
        unknown code is rejected; the error lists every code the loaded
        dataset defines, so the caller can self-correct.
        """
        try:
            return self.by_code[code]
        except KeyError:
            raise UnknownWorkCodeError(
                f"Work code '{code}' is not present in the dataset. "
                f"Known codes: {', '.join(self.codes)}."
            ) from None

    def get_by_category(self, category: WorkCategory) -> list[WorkRequirements]:
        """All work types in one category; unknown categories are an error
        that lists every category the loaded dataset defines."""
        if category not in self.categories:
            raise UnknownCategoryError(
                f"Category '{category}' is not present in the dataset. "
                f"Known categories: {', '.join(self.categories)}."
            )
        return [record for record in self.work_types if record.category == category]

    @property
    def count(self) -> int:
        return len(self.work_types)


@lru_cache(maxsize=1)
def get_dataset() -> Dataset:
    """Return the process-wide dataset singleton, loading it on first use
    from the path chosen by resolve_dataset_path()."""
    path = resolve_dataset_path()
    if path != DEFAULT_DATASET_PATH and not path.is_file():
        raise DatasetError(
            f"{DATASET_ENV_VAR} points to {path}, which is not an existing "
            "file. Set it to the path of your dataset JSON, or leave it "
            "empty to use the built-in example dataset."
        )
    return Dataset.load(path)
