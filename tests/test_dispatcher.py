"""Unit tests for dispatcher tool routing and validation."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from linkedin_mcp.dispatcher import (
    TOOLS,
    get_tool_names,
    dispatch_tool,
    _is_auth_related_error,
    _is_fatal_session_error,
    _needs_auth_recovery,
)


class TestToolRegistry:
    """Test tool registry structure."""

    def test_get_tool_names(self):
        """Should return list of tool names."""
        names = get_tool_names()
        assert isinstance(names, list)
        assert "login" in names
        assert "read_feed" in names
        assert "get_profile" in names

    def test_all_tools_have_required_fields(self):
        """Every tool should have handler, required, optional, auth_recovery."""
        for name, tool in TOOLS.items():
            assert "handler" in tool, f"{name} missing handler"
            assert "required" in tool, f"{name} missing required"
            assert "optional" in tool, f"{name} missing optional"
            assert "auth_recovery" in tool, f"{name} missing auth_recovery"

    def test_all_handlers_are_callable(self):
        """All handlers should be callable (async functions)."""
        for name, tool in TOOLS.items():
            assert callable(tool["handler"]), f"{name} handler is not callable"


class TestAuthRelatedError:
    """Test _is_auth_related_error detection."""

    def test_non_dict_returns_false(self):
        assert _is_auth_related_error("not a dict") is False

    def test_non_error_status_returns_false(self):
        assert _is_auth_related_error({"status": "ok"}) is False

    def test_auth_required_code(self):
        assert _is_auth_related_error({"status": "error", "code": "auth_required"}) is True

    def test_login_required_code(self):
        assert _is_auth_related_error({"status": "error", "code": "login_required"}) is True

    def test_authwall_code(self):
        assert _is_auth_related_error({"status": "error", "code": "authwall"}) is True

    def test_authwall_in_url(self):
        assert _is_auth_related_error({
            "status": "error",
            "code": "unknown",
            "details": {"current_url": "https://linkedin.com/authwall"},
        }) is True

    def test_login_in_message(self):
        assert _is_auth_related_error({
            "status": "error",
            "message": "Not logged in",
        }) is True

    def test_cookies_invalid_message(self):
        assert _is_auth_related_error({
            "status": "error",
            "message": "Cookies may be invalid or expired",
        }) is True

    def test_non_auth_error_returns_false(self):
        assert _is_auth_related_error({
            "status": "error",
            "message": "Element not found",
        }) is False


class TestFatalSessionError:
    """Test _is_fatal_session_error detection."""

    def test_non_dict_returns_false(self):
        assert _is_fatal_session_error("not a dict") is False

    def test_non_error_returns_false(self):
        assert _is_fatal_session_error({"status": "ok"}) is False

    def test_tunnel_connection_failed(self):
        assert _is_fatal_session_error({
            "status": "error",
            "message": "ERR_TUNNEL_CONNECTION_FAILED",
        }) is True

    def test_proxy_connection_failed(self):
        assert _is_fatal_session_error({
            "status": "error",
            "message": "ERR_PROXY_CONNECTION_FAILED",
        }) is True

    def test_connection_reset(self):
        assert _is_fatal_session_error({
            "status": "error",
            "message": "ERR_CONNECTION_RESET",
        }) is True

    def test_page_closed(self):
        assert _is_fatal_session_error({
            "status": "error",
            "message": "Target page, context or browser has been closed",
        }) is True

    def test_non_fatal_error(self):
        assert _is_fatal_session_error({
            "status": "error",
            "message": "Element not found",
        }) is False


class TestNeedsAuthRecovery:
    """Test _needs_auth_recovery logic."""

    def test_no_profile_id(self):
        """Should return False when no profile_id."""
        tool = {"auth_recovery": True}
        assert _needs_auth_recovery(tool, None) is False
        assert _needs_auth_recovery(tool, "") is False

    def test_auth_recovery_true(self):
        """Should return True when auth_recovery is True and profile_id present."""
        tool = {"auth_recovery": True}
        assert _needs_auth_recovery(tool, "profile-uuid") is True

    def test_auth_recovery_false(self):
        """Should return False when auth_recovery is False."""
        tool = {"auth_recovery": False}
        assert _needs_auth_recovery(tool, "profile-uuid") is False


class TestDispatchTool:
    """Test dispatch_tool routing."""

    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        """Should return error for unknown tool name."""
        result = await dispatch_tool("nonexistent_tool", {})
        assert result["status"] == "error"
        assert "Unknown tool" in result["message"]

    @pytest.mark.asyncio
    async def test_missing_required_argument(self):
        """Should return error when required argument is missing."""
        # Mock get_db to avoid DB connection
        with patch("linkedin_mcp.dispatcher.get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
            mock_repo = MagicMock()
            mock_repo.get_by_uuid.return_value = None
            with patch("linkedin_mcp.dispatcher.ProfileRepository", return_value=mock_repo):
                with patch("linkedin_mcp.dispatcher.get_session_manager"):
                    result = await dispatch_tool("login", {})
        assert result["status"] == "error"
        assert "Missing required argument" in result["message"]

    @pytest.mark.asyncio
    async def test_unknown_argument_fails_before_handler(self):
        handler = AsyncMock(return_value={"status": "ok"})
        with patch.dict(TOOLS, {
            "test_tool": {
                "handler": handler,
                "required": [],
                "optional": {},
                "auth_recovery": False,
            }
        }):
            result = await dispatch_tool("test_tool", {"unexpected": True})
        assert result["code"] == "INVALID_REQUEST"
        handler.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_optional_defaults_applied(self):
        """Should apply default values for optional arguments."""
        mock_handler = AsyncMock(return_value={"status": "ok"})

        with patch.dict(TOOLS, {
            "test_tool": {
                "handler": mock_handler,
                "required": ["profile_id"],
                "optional": {"max_posts": 10, "scroll_count": 3},
                "auth_recovery": False,
            }
        }):
            with patch("linkedin_mcp.dispatcher.get_db") as mock_get_db:
                mock_db = MagicMock()
                mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
                mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
                mock_repo = MagicMock()
                mock_repo.get_by_uuid.return_value = None
                with patch("linkedin_mcp.dispatcher.ProfileRepository", return_value=mock_repo):
                    with patch("linkedin_mcp.dispatcher.get_session_manager"):
                        with patch("linkedin_mcp.dispatcher.ChallengeEventRepository"):
                            result = await dispatch_tool("test_tool", {"profile_id": "uuid-1"})

        assert result == {"status": "ok"}
        mock_handler.assert_awaited_once_with(profile_id="uuid-1", max_posts=10, scroll_count=3)

    @pytest.mark.asyncio
    async def test_handler_exception_caught(self):
        """Should catch handler exceptions and return error dict."""
        mock_handler = AsyncMock(side_effect=RuntimeError("browser crashed"))

        with patch.dict(TOOLS, {
            "test_tool": {
                "handler": mock_handler,
                "required": ["profile_id"],
                "optional": {},
                "auth_recovery": False,
            }
        }):
            with patch("linkedin_mcp.dispatcher.get_db") as mock_get_db:
                mock_db = MagicMock()
                mock_get_db.return_value.__enter__ = MagicMock(return_value=mock_db)
                mock_get_db.return_value.__exit__ = MagicMock(return_value=False)
                mock_repo = MagicMock()
                mock_repo.get_by_uuid.return_value = None
                with patch("linkedin_mcp.dispatcher.ProfileRepository", return_value=mock_repo):
                    with patch("linkedin_mcp.dispatcher.get_session_manager"):
                        with patch("linkedin_mcp.dispatcher.ChallengeEventRepository"):
                            result = await dispatch_tool("test_tool", {"profile_id": "uuid-1"})

        assert result["status"] == "error"
        assert result["code"] == "INTERNAL_ERROR"
        assert result["message"] == "Tool execution failed"
        assert "browser crashed" not in result["message"]

    @pytest.mark.asyncio
    async def test_close_session_bypasses_active_challenge_lock(self):
        handler = AsyncMock(return_value={"status": "ok"})
        profile_row = MagicMock(id=7)
        lock = {"remaining_minutes": 10, "signal": "checkpoint"}
        tool = {
            "handler": handler,
            "required": ["profile_id"],
            "optional": {},
            "auth_recovery": False,
        }
        with patch.dict(TOOLS, {"close_session": tool}):
            with patch("linkedin_mcp.dispatcher.get_db") as get_db:
                get_db.return_value.__enter__.return_value = MagicMock()
                get_db.return_value.__exit__.return_value = False
                with patch("linkedin_mcp.dispatcher.ProfileRepository") as profiles:
                    profiles.return_value.get_by_uuid.return_value = profile_row
                    with patch("linkedin_mcp.dispatcher.ChallengeEventRepository") as events:
                        events.return_value.get_active_lock.return_value = lock
                        result = await dispatch_tool("close_session", {"profile_id": "uuid-1"})
        assert result == {"status": "ok"}
        handler.assert_awaited_once_with(profile_id="uuid-1")

    @pytest.mark.asyncio
    async def test_safe_recovery_tool_bypasses_activity_budget(self):
        handler = AsyncMock(return_value={"status": "ok"})
        tool = {
            "handler": handler,
            "required": ["profile_id"],
            "optional": {},
            "auth_recovery": False,
        }
        denied_policy = MagicMock()
        denied_policy.allow.return_value = False
        with patch.dict(TOOLS, {"close_session": tool}):
            with patch("linkedin_mcp.dispatcher.get_activity_policy", return_value=denied_policy):
                result = await dispatch_tool("close_session", {"profile_id": "uuid-1"})
        assert result == {"status": "ok"}
        denied_policy.allow.assert_not_called()
