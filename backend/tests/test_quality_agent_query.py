"""Tests for quality agent query scoping."""

from app.db.models import AppRole
from app.services.quality_scoping import filter_response_for_role


def test_client_response_strips_reviewer_references() -> None:
    text = "Reviewer ID: abc-123 caused errors. Annotator John Smith needs calibration."
    filtered = filter_response_for_role(text, AppRole.CLIENT)
    assert "abc-123" not in filtered
    assert "John Smith" not in filtered


def test_dm_response_unfiltered() -> None:
    text = "Reviewer ID: abc-123 needs calibration."
    assert filter_response_for_role(text, AppRole.DELIVERY_MANAGER) == text
