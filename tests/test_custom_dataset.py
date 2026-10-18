"""Tests for user-supplied datasets via BUILDWINDOW_DATASET.

Covers: loading a valid dataset from a different domain (drone operations,
examples/drone_operations.json) with its own codes and categories; using
it through the real tool functions; readable errors for an invalid file or
a bad path; falling back to the built-in example when the variable is
unset or empty; and the tool schemas listing the loaded dataset's codes.
"""

from __future__ import annotations

import datetime
import json
from collections.abc import Iterator
from pathlib import Path

import pytest

import server.main as main_module
from server.dataset import (
    DATASET_ENV_VAR,
    DEFAULT_DATASET_PATH,
    Dataset,
    get_dataset,
)
from server.errors import DatasetError, UnknownCategoryError, UnknownWorkCodeError
from server.schemas import (
    LookupWorkRequirementsInput,
    PlannedWork,
    PlanWorkScheduleInput,
    ValidateWorkWindowInput,
    Verdict,
    WeatherWindow,
    WorkCode,
)
from tests.conftest import daily_forecast

DRONE_DATASET_PATH = (
    Path(__file__).resolve().parent.parent / "examples" / "drone_operations.json"
)
DRONE_CODES = {
    "aerial_photography",
    "lidar_survey",
    "thermal_inspection",
    "crop_spraying",
    "parcel_delivery",
}


@pytest.fixture
def fresh_dataset_cache() -> Iterator[None]:
    """Clear the get_dataset() singleton before and after the test, so a
    dataset selected via the environment never leaks into other tests."""
    get_dataset.cache_clear()
    yield
    get_dataset.cache_clear()


@pytest.fixture
def drone_dataset_env(
    monkeypatch: pytest.MonkeyPatch, fresh_dataset_cache: None
) -> None:
    monkeypatch.setenv(DATASET_ENV_VAR, str(DRONE_DATASET_PATH))


def _valid_record(**overrides) -> dict:
    record = {
        "code": "survey_mapping",
        "name": "Survey mapping",
        "category": "survey",
        "temp_min_c": -5,
        "temp_max_c": 35,
        "wind_max_ms": 8,
        "humidity_max_pct": 90,
        "precipitation_allowed": False,
        "base_curing_hours": None,
        "reference_note": "test fixture",
    }
    record.update(overrides)
    return record


def _write_dataset(tmp_path: Path, records: list[dict]) -> Path:
    path = tmp_path / "custom.json"
    payload = {"schema_version": "1.0", "work_types": records}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_custom_dataset_with_other_work_codes() -> None:
    dataset = Dataset.load(DRONE_DATASET_PATH)

    assert set(dataset.codes) == DRONE_CODES
    assert set(dataset.categories) == {
        "imaging",
        "survey",
        "inspection",
        "agriculture",
        "logistics",
    }
    assert WorkCode.CONCRETE_POUR not in dataset.codes


def test_env_var_selects_custom_dataset_end_to_end(
    drone_dataset_env: None,
) -> None:
    dataset = get_dataset()
    assert dataset.source == DRONE_DATASET_PATH
    assert set(dataset.codes) == DRONE_CODES

    # 34 C exceeds crop_spraying's 28 C maximum by 6 C -> beyond the 2 C
    # conditional band -> hard violation.
    hot_day = WeatherWindow(
        date=datetime.date(2026, 8, 20),
        temp_min_c=20.0,
        temp_max_c=34.0,
        wind_ms=2.0,
        humidity_pct=40,
        precipitation_mm=0.0,
    )
    result = main_module.validate_work_window(
        ValidateWorkWindowInput(work_code="crop_spraying", window=hot_day)
    )
    assert result.verdict == Verdict.PROHIBITED
    assert result.violations[0].constraint == "temperature_max"

    lookup = main_module.lookup_work_requirements(
        LookupWorkRequirementsInput(category="survey")
    )
    assert [r.code for r in lookup.requirements] == ["lidar_survey"]

    plan = main_module.plan_work_schedule(
        PlanWorkScheduleInput(
            works=[
                PlannedWork(work_code="lidar_survey", duration_days=1),
                PlannedWork(
                    work_code="aerial_photography",
                    duration_days=1,
                    depends_on=["lidar_survey"],
                ),
            ],
            forecast=daily_forecast(datetime.date(2026, 8, 20), 3),
        )
    )
    assert [w.work_code for w in plan.scheduled] == [
        "lidar_survey",
        "aerial_photography",
    ]


def test_unknown_code_error_lists_loaded_dataset_codes(
    drone_dataset_env: None,
) -> None:
    with pytest.raises(UnknownWorkCodeError) as exc_info:
        get_dataset().get_by_code("concrete_pour")
    message = str(exc_info.value)
    assert message.startswith("[unknown_work_code]")
    for code in DRONE_CODES:
        assert code in message

    with pytest.raises(UnknownCategoryError) as exc_info:
        get_dataset().get_by_category("concrete")
    assert "imaging" in str(exc_info.value)


def test_unknown_dependency_code_is_rejected(drone_dataset_env: None) -> None:
    with pytest.raises(UnknownWorkCodeError):
        main_module.plan_work_schedule(
            PlanWorkScheduleInput(
                works=[
                    PlannedWork(
                        work_code="aerial_photography",
                        duration_days=1,
                        depends_on=["lidar_surveyy"],
                    )
                ],
                forecast=daily_forecast(datetime.date(2026, 8, 20), 2),
            )
        )


def test_invalid_custom_dataset_error_names_field_and_allowed_values(
    tmp_path: Path,
) -> None:
    bad_records = [
        _valid_record(code="windy_flight", wind_max_ms=55),
        _valid_record(code="Bad Code"),
        _valid_record(code="extra_field", max_gust_ms=12),
    ]
    with pytest.raises(DatasetError) as exc_info:
        Dataset.load(_write_dataset(tmp_path, bad_records))
    message = str(exc_info.value)

    assert "3 problems found" in message
    # Out-of-range value: names the record, the field, the bound and the value.
    assert "work_types[0] (code 'windy_flight').wind_max_ms" in message
    assert "less than or equal to 40" in message
    assert "(got 55)" in message
    # Malformed code: explains the expected shape.
    assert "work_types[1] (code 'Bad Code').code" in message
    assert "snake_case" in message
    # Unknown field: lists the allowed field names.
    assert "work_types[2] (code 'extra_field').max_gust_ms" in message
    assert "allowed fields: code, name, category" in message


def test_missing_field_error_lists_allowed_fields(tmp_path: Path) -> None:
    record = _valid_record()
    del record["precipitation_allowed"]
    with pytest.raises(DatasetError) as exc_info:
        Dataset.load(_write_dataset(tmp_path, [record]))
    message = str(exc_info.value)
    assert "precipitation_allowed: required field is missing" in message
    assert "reference_note" in message


def test_env_var_pointing_to_missing_file_names_the_variable(
    monkeypatch: pytest.MonkeyPatch, fresh_dataset_cache: None, tmp_path: Path
) -> None:
    monkeypatch.setenv(DATASET_ENV_VAR, str(tmp_path / "does_not_exist.json"))
    with pytest.raises(DatasetError) as exc_info:
        get_dataset()
    assert DATASET_ENV_VAR in str(exc_info.value)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_unset_or_empty_env_var_falls_back_to_builtin_dataset(
    monkeypatch: pytest.MonkeyPatch, fresh_dataset_cache: None, value: str | None
) -> None:
    if value is None:
        monkeypatch.delenv(DATASET_ENV_VAR, raising=False)
    else:
        monkeypatch.setenv(DATASET_ENV_VAR, value)
    dataset = get_dataset()
    assert dataset.source == DEFAULT_DATASET_PATH
    assert dataset.count == 12
    assert WorkCode.CONCRETE_POUR in dataset.codes


def test_lookup_reports_which_dataset_the_limits_come_from(
    monkeypatch: pytest.MonkeyPatch, fresh_dataset_cache: None
) -> None:
    """The calling model must be able to tell the built-in illustrative
    example from a user's own file without guessing from reference_note
    wording (the drone example's notes also say "illustrative")."""
    monkeypatch.delenv(DATASET_ENV_VAR, raising=False)
    builtin = main_module.lookup_work_requirements(
        LookupWorkRequirementsInput(work_code=WorkCode.CONCRETE_POUR)
    )
    assert builtin.dataset_is_builtin_example is True
    assert builtin.dataset_file == "work_types.json"

    monkeypatch.setenv(DATASET_ENV_VAR, str(DRONE_DATASET_PATH))
    get_dataset.cache_clear()
    custom = main_module.lookup_work_requirements(
        LookupWorkRequirementsInput(work_code="crop_spraying")
    )
    assert custom.dataset_is_builtin_example is False
    assert custom.dataset_file == "drone_operations.json"


def test_tool_schema_lists_loaded_codes_and_categories() -> None:
    """The open WorkCode/WorkCategory types still give the calling model a
    concrete list of options: the JSON Schema carries an enum taken from
    the loaded dataset (here the built-in one)."""
    schema = ValidateWorkWindowInput.model_json_schema()
    work_code = schema["properties"]["work_code"]
    assert work_code["type"] == "string"
    assert work_code["enum"] == list(get_dataset().codes)
    assert work_code["description"]

    lookup_schema = LookupWorkRequirementsInput.model_json_schema()
    category_options = lookup_schema["properties"]["category"]["anyOf"]
    enums = [option.get("enum") for option in category_options]
    assert list(get_dataset().categories) in enums
