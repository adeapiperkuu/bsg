"""Tests for delivery conversation helpers."""

from app.agents.delivery.services.conversation_service import title_from_message


def test_title_from_message_truncates_and_defaults() -> None:
    assert title_from_message("") == "New conversation"
    assert title_from_message("  Which projects are at risk?  ") == "Which projects are at risk?"
    assert len(title_from_message("x" * 200)) == 120
