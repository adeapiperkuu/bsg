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
    codes = ["ERR-01", "ERR-02", "ERR-03", "ERR-04", "ERR-05", "ERR-06", "ERR-07"]
    for code in codes:
        entry = _entry(code)
        assert entry.error_category == code
    other = QualityErrorEntryCreate(
        error_category="ERR-OTHER", share_pct=Decimal("5.0"), error_note="misc"
    )
    assert other.error_category == "ERR-OTHER"


def test_all_canonical_names_accepted() -> None:
    names_to_codes = {
        "Boundary precision": "ERR-01",
        "Class confusion": "ERR-02",
        "Missed object": "ERR-03",
        "Guideline ambiguity": "ERR-04",
        "False positive": "ERR-05",
        "Attribute error": "ERR-06",
        "Tool error": "ERR-07",
    }
    for name, expected_code in names_to_codes.items():
        assert _entry(name).error_category == expected_code
    assert (
        QualityErrorEntryCreate(
            error_category="Other", share_pct=Decimal("5.0"), error_note="misc"
        ).error_category
        == "ERR-OTHER"
    )


# ---------------------------------------------------------------------------
# Hard taxonomy enforcement (Phase 1.5 / QI-F04)
# ---------------------------------------------------------------------------


def test_unknown_code_rejected() -> None:
    with pytest.raises(ValidationError, match="Unknown error category"):
        _entry("CUSTOM_ERROR_TYPE")


def test_empty_string_rejected() -> None:
    with pytest.raises(ValidationError):
        _entry("  ")


def test_err_other_requires_note() -> None:
    with pytest.raises(ValidationError, match="error_note is required"):
        QualityErrorEntryCreate(error_category="ERR-OTHER", share_pct=Decimal("10.0"))


def test_err_other_with_note_accepted() -> None:
    entry = QualityErrorEntryCreate(
        error_category="ERR-OTHER",
        share_pct=Decimal("10.0"),
        error_note="Novel edge-case label noise",
    )
    assert entry.error_category == "ERR-OTHER"
    assert entry.error_note == "Novel edge-case label noise"


# ---------------------------------------------------------------------------
# share_pct validation still applies
# ---------------------------------------------------------------------------


def test_share_pct_out_of_range_raises() -> None:
    with pytest.raises(ValidationError):
        QualityErrorEntryCreate(error_category="ERR-01", share_pct=Decimal("110.0"))


def test_share_pct_negative_raises() -> None:
    with pytest.raises(ValidationError):
        QualityErrorEntryCreate(error_category="ERR-01", share_pct=Decimal("-5.0"))
