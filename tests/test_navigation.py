"""Unit tests for navigation retry helper."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from linkedin_mcp.browser.navigation import (
    goto_with_retry,
    NETWORK_ERROR_RE,
    GOTO_MAX_RETRIES,
    GOTO_RETRY_DELAY_MS,
)


class TestNetworkErrorRegex:
    """Test the transient network error regex."""

    def test_matches_err_timed_out(self):
        assert NETWORK_ERROR_RE.search("net::ERR_TIMED_OUT at https://example.com")

    def test_matches_err_connection_reset(self):
        assert NETWORK_ERROR_RE.search("net::ERR_CONNECTION_RESET")

    def test_matches_err_proxy_connection_failed(self):
        assert NETWORK_ERROR_RE.search("net::ERR_PROXY_CONNECTION_FAILED")

    def test_matches_err_tunnel_connection_failed(self):
        assert NETWORK_ERROR_RE.search("net::ERR_TUNNEL_CONNECTION_FAILED")

    def test_matches_err_network_changed(self):
        assert NETWORK_ERROR_RE.search("net::ERR_NETWORK_CHANGED")

    def test_matches_case_insensitive(self):
        assert NETWORK_ERROR_RE.search("err_timed_out")

    def test_no_match_for_timeout(self):
        """Regular Playwright timeout should not match."""
        assert not NETWORK_ERROR_RE.search("Timeout 30000ms exceeded")

    def test_no_match_for_navigation_error(self):
        assert not NETWORK_ERROR_RE.search("Page.navigate: frame was detached")


class TestGotoWithRetry:
    """Test goto_with_retry behavior."""

    @pytest.mark.asyncio
    async def test_success_first_try(self, mock_page):
        """Should return response on first successful navigation."""
        expected_response = MagicMock()
        mock_page.goto = AsyncMock(return_value=expected_response)

        result = await goto_with_retry(mock_page, "https://example.com")
        assert result is expected_response
        assert mock_page.goto.call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_network_error(self, mock_page):
        """Should retry on transient network errors."""
        error = Exception("net::ERR_CONNECTION_RESET")
        success_response = MagicMock()
        mock_page.goto = AsyncMock(
            side_effect=[error, error, success_response]
        )

        # Patch sleep to avoid real delays
        with patch("linkedin_mcp.browser.navigation.asyncio.sleep", new=AsyncMock()):
            result = await goto_with_retry(mock_page, "https://example.com")
        assert result is success_response
        assert mock_page.goto.call_count == 3

    @pytest.mark.asyncio
    async def test_raises_non_retryable_error(self, mock_page):
        """Should not retry on non-network errors."""
        error = Exception("Page not found: 404")
        mock_page.goto = AsyncMock(side_effect=error)

        with pytest.raises(Exception, match="Page not found"):
            await goto_with_retry(mock_page, "https://example.com")
        assert mock_page.goto.call_count == 1

    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self, mock_page):
        """Should raise after exhausting retries on persistent network errors."""
        error = Exception("net::ERR_PROXY_CONNECTION_FAILED")
        mock_page.goto = AsyncMock(side_effect=error)

        with patch("linkedin_mcp.browser.navigation.asyncio.sleep", new=AsyncMock()):
            with pytest.raises(Exception, match="ERR_PROXY_CONNECTION_FAILED"):
                await goto_with_retry(mock_page, "https://example.com")
        assert mock_page.goto.call_count == GOTO_MAX_RETRIES

    @pytest.mark.asyncio
    async def test_passes_wait_until_and_timeout(self, mock_page):
        """Should pass wait_until and timeout to page.goto."""
        response = MagicMock()
        mock_page.goto = AsyncMock(return_value=response)

        await goto_with_retry(
            mock_page, "https://example.com",
            wait_until="networkidle", timeout=30000,
        )
        mock_page.goto.assert_called_once_with(
            "https://example.com", wait_until="networkidle", timeout=30000
        )
