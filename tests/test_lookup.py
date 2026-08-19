"""Tests for the lookup_work_requirements MCP tool (spec tests 6-9)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from server.dataset import Dataset
from server.main import lookup_work_requirements
from server.schemas import LookupWorkRequirementsInput, WorkCategory, WorkCode


def test_lookup_by_work_code_returns_single_matching_record(dataset: Dataset) -> None:
    """Test 6: work_code=CONCRETE_POUR -> exactly one matching requirements
    record, equal to the dataset's own record for that code."""
    request = LookupWorkRequirementsInput(work_code=WorkCode.CONCRETE_POUR)

    result = lookup_work_requirements(request)

    assert result.matched_count == 1
    assert len(result.requirements) == 1
    assert result.requirements[0] == dataset.get_by_code(WorkCode.CONCRETE_POUR)


def test_lookup_by_category_returns_all_concrete_work_types() -> None:
    """Test 7: category=CONCRETE -> all 4 concrete work types (concrete_pour,
    concrete_finishing, screed_pour, masonry), each tagged CONCRETE."""
    request = LookupWorkRequirementsInput(category=WorkCategory.CONCRETE)

    result = lookup_work_requirements(request)

    assert result.matched_count == 4
    assert len(result.requirements) == 4
    for req in result.requirements:
        assert req.category == WorkCategory.CONCRETE

    returned_codes = {req.code for req in result.requirements}
    assert returned_codes == {
        WorkCode.CONCRETE_POUR,
        WorkCode.CONCRETE_FINISHING,
        WorkCode.SCREED_POUR,
        WorkCode.MASONRY,
    }


def test_lookup_with_both_work_code_and_category_is_rejected() -> None:
    """Test 8: setting both work_code and category violates the
    exactly-one-of constraint -> ValidationError mentioning
    invalid_lookup_criteria."""
    with pytest.raises(ValidationError) as exc_info:
        LookupWorkRequirementsInput(
            work_code=WorkCode.CONCRETE_POUR, category=WorkCategory.CONCRETE
        )

    assert "invalid_lookup_criteria" in str(exc_info.value)


def test_lookup_with_neither_work_code_nor_category_is_rejected() -> None:
    """Test 9: setting neither work_code nor category violates the
    exactly-one-of constraint -> ValidationError mentioning
    invalid_lookup_criteria."""
    with pytest.raises(ValidationError) as exc_info:
        LookupWorkRequirementsInput()

    assert "invalid_lookup_criteria" in str(exc_info.value)
