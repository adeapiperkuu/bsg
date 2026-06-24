"""Tests for quality error taxonomy validation in Pydantic schemas."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.domain import QualityErrorEntryCreate


# ---------------------------------------------------------------------------
# Canonical code acceptance
# ---------------------------------------------------------------------------


def _entry(category: str) -> QualityErrorEntryCreate:
    return QualityErrorEntryCreate(error_category=category, share_pct=Decimal("25.0"))


def test_canonical_code_accepted() -> None:
    entry = _entry("ERR-01")
    assert entry.error_category == "ERR-01"


def test_canonical_code_uppercase_normalized() -> None:
    entry = _entry("err-01")
    assert entry.error_category == "ERR-01"


def test_canonical_name_accepted() -> None:
    entry = _entry("Boundary precision")
    assert entry.error_category == "ERR-01"


def test_canonical_name_case_insensitive() -> None:
    entry = _entry("CLASS CONFUSION")
    assert entry.error_category == "ERR-02"


def test_all_canonical_codes_accepted() -> None:
    codes = ["ERR-01", "ERR-02", "ERR-03", "ERR-04", "ERR-05", "ERR-06", "ERR-07", "ERR-OTHER"]
    for code in codes:
        entry = _entry(code)
        assert entry.error_category == code


def test_all_canonical_names_accepted() -> None:
    names_to_codes = {
        "Boundary precision": "ERR-01",
        "Class confusion": "ERR-02",
        "Missed object": "ERR-03",
        "Guideline ambiguity": "ERR-04",
        "False positive": "ERR-05",
        "Attribute error": "ERR-06",
        "Tool error": "ERR-07",
        "Other": "ERR-OTHER",
    }
    for name, expected_code in names_to_codes.items():
        assert _entry(name).error_category == expected_code


# ---------------------------------------------------------------------------
# Free-text passthrough (no hard reject in Phase 1.5 MVP)
# ---------------------------------------------------------------------------


def test_unknown_code_passes_as_free_text() -> None:
    entry = _entry("CUSTOM_ERROR_TYPE")
    assert entry.error_category == "CUSTOM_ERROR_TYPE"


def test_empty_string_passes_as_free_text() -> None:
    entry = _entry("  ")
    assert entry.error_category == ""


# ---------------------------------------------------------------------------
# share_pct validation still applies
# ---------------------------------------------------------------------------


def test_share_pct_out_of_range_raises() -> None:
    with pytest.raises(ValidationError):
        QualityErrorEntryCreate(error_category="ERR-01", share_pct=Decimal("110.0"))


def test_share_pct_negative_raises() -> None:
    with pytest.raises(ValidationError):
        QualityErrorEntryCreate(error_category="ERR-01", share_pct=Decimal("-5.0"))
