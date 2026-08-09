"""Unit tests for challenge lock helpers."""

from datetime import datetime, timedelta

import pytest

from linkedin_mcp.challenge_lock import (
    classify_challenge_signal,
    extract_challenge_event_from_result,
    build_challenge_lock_response,
)


class TestClassifyChallengeSignal:
    """Test challenge signal classification."""

    @pytest.mark.parametrize("message,expected", [
        ("LinkedIn checkpoint detected", "checkpoint"),
        ("Please solve the captcha", "captcha"),
        ("Two-step verification required", "verification"),
        ("2FA verification required", "verification"),
        ("Auth wall encountered", "authwall"),
        ("authwall page shown", "authwall"),
        ("Not logged in", "authwall"),
        ("Login required", "authwall"),
        ("contextual-sign-in form", "authwall"),
        ("Sign in to view more content", "authwall"),
        ("normal error message", None),
        ("", None),
        (None, None),
    ])
    def test_classification(self, message, expected):
        assert classify_challenge_signal(message) == expected

    def test_case_insensitive(self):
        """Should match case-insensitively."""
        assert classify_challenge_signal("CHECKPOINT") == "checkpoint"
        assert classify_challenge_signal("CAPTCHA") == "captcha"


class TestExtractChallengeEvent:
    """Test challenge event extraction from results."""

    def test_non_dict_returns_none(self):
        assert extract_challenge_event_from_result("not a dict") is None

    def test_skipped_with_lock_returns_none(self):
        """Skipped results with challenge_lock should not extract events."""
        result = {"status": "skipped", "challenge_lock": {"remaining_minutes": 10}}
        assert extract_challenge_event_from_result(result) is None

    def test_no_signal_returns_none(self):
        """Results without challenge signals should return None."""
        result = {"status": "error", "message": "network timeout"}
        assert extract_challenge_event_from_result(result) is None

    def test_checkpoint_signal(self):
        """Should extract checkpoint signal."""
        result = {"status": "error", "message": "checkpoint page detected"}
        event = extract_challenge_event_from_result(result)
        assert event is not None
        assert event["signal"] == "checkpoint"

    def test_authwall_signal_with_url(self):
        """Should extract page_url from details."""
        result = {
            "status": "error",
            "message": "Not logged in",
            "details": {"current_url": "https://linkedin.com/authwall"},
        }
        event = extract_challenge_event_from_result(result)
        assert event is not None
        assert event["signal"] == "authwall"
        assert event["page_url"] == "https://linkedin.com/authwall"

    def test_authwall_signal_with_top_level_url(self):
        """Should extract page_url from top-level current_url."""
        result = {
            "status": "error",
            "message": "login required",
            "current_url": "https://linkedin.com/login",
        }
        event = extract_challenge_event_from_result(result)
        assert event is not None
        assert event["page_url"] == "https://linkedin.com/login"


class TestBuildChallengeLockResponse:
    """Test challenge lock response builder."""

    def test_basic_response(self):
        """Should build a skipped response with lock data."""
        lock_data = {
            "remaining_minutes": 10.5,
            "signal": "checkpoint",
            "source_tool": "read_feed",
        }
        response = build_challenge_lock_response("profile-uuid", lock_data)
        assert response["status"] == "skipped"
        assert response["profile_id"] == "profile-uuid"
        assert response["challenge_lock"] is lock_data
        assert "10.5 min remaining" in response["message"]
        assert "challenge" in response["message"].lower()
