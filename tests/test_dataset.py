"""Tests for server/dataset.py: dataset loading and validation.

Covers spec test numbers 1-5:
1. get_dataset() loads exactly 12 records.
2. All codes in the real dataset are unique.
3. A duplicated code in the source JSON raises DatasetError.
4. WorkRequirements with temp_min_c == temp_max_c raises ValidationError.
5. WorkRequirements with base_curing_hours=0 raises ValidationError.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from server.dataset import Dataset, get_dataset
from server.errors import DatasetError
from server.schemas import WorkCategory, WorkCode, WorkRequirements


def test_get_dataset_loads_exactly_12_records() -> None:
    dataset = get_dataset()
    assert dataset.count == 12
    assert len(dataset.work_types) == 12


def test_dataset_codes_are_unique() -> None:
    dataset = get_dataset()
    codes = [r.code for r in dataset.work_types]
    assert len(codes) == len(set(codes)) == 12


def test_duplicate_code_raises_dataset_error(tmp_path: Path) -> None:
    record = {
        "code": "concrete_pour",
        "name": "Concrete pouring",
        "category": "concrete",
        "temp_min_c": 5,
        "temp_max_c": 30,
        "wind_max_ms": 15,
        "humidity_max_pct": 95,
        "precipitation_allowed": False,
        "base_curing_hours": 168,
        "reference_note": "test fixture",
    }
    payload = {
        "schema_version": "1.0",
        "work_types": [dict(record), dict(record)],
    }
    bad_file = tmp_path / "duplicate_codes.json"
    bad_file.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DatasetError):
        Dataset.load(bad_file)


def test_work_requirements_rejects_equal_temp_min_and_max() -> None:
    with pytest.raises(ValidationError):
        WorkRequirements(
            code=WorkCode.CONCRETE_POUR,
            name="x",
            category=WorkCategory.CONCRETE,
            temp_min_c=10,
            temp_max_c=10,
            wind_max_ms=5,
            humidity_max_pct=50,
            precipitation_allowed=False,
            base_curing_hours=24,
            reference_note="x",
        )


def test_work_requirements_rejects_zero_base_curing_hours() -> None:
    with pytest.raises(ValidationError):
        WorkRequirements(
            code=WorkCode.CONCRETE_POUR,
            name="x",
            category=WorkCategory.CONCRETE,
            temp_min_c=5,
            temp_max_c=30,
            wind_max_ms=5,
            humidity_max_pct=50,
            precipitation_allowed=False,
            base_curing_hours=0,
            reference_note="x",
        )
