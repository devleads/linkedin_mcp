"""Unit tests for human-like behavior simulation."""

import asyncio
import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from linkedin_mcp.browser.human import HumanBehavior


class TestDelays:
    """Test delay methods."""

    @pytest.mark.asyncio
    async def test_delay(self):
        """delay should call asyncio.sleep with a value in range."""
        with patch("linkedin_mcp.browser.human.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            await HumanBehavior.delay(min_ms=500, max_ms=500)
            mock_sleep.assert_awaited_once_with(0.5)

    @pytest.mark.asyncio
    async def test_typing_delay(self):
        """typing_delay should sleep 50-150ms."""
        with patch("linkedin_mcp.browser.human.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            await HumanBehavior.typing_delay()
            called_val = mock_sleep.call_args[0][0]
            assert 0.05 <= called_val <= 0.15

    @pytest.mark.asyncio
    async def test_page_load_delay(self):
        """page_load_delay should sleep 2-5 seconds."""
        with patch("linkedin_mcp.browser.human.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            await HumanBehavior.page_load_delay()
            called_val = mock_sleep.call_args[0][0]
            assert 2.0 <= called_val <= 5.0

    @pytest.mark.asyncio
    async def test_reading_delay_caps_at_10(self):
        """reading_delay should cap at 10 seconds."""
        with patch("linkedin_mcp.browser.human.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            await HumanBehavior.reading_delay(text_length=100000)
            called_val = mock_sleep.call_args[0][0]
            assert called_val <= 10.0

    @pytest.mark.asyncio
    async def test_reading_delay_min_1(self):
        """reading_delay should be at least 1 second."""
        with patch("linkedin_mcp.browser.human.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            await HumanBehavior.reading_delay(text_length=1)
            called_val = mock_sleep.call_args[0][0]
            assert called_val >= 1.0


class TestHumanPause:
    """Test human_pause method."""

    @pytest.mark.asyncio
    async def test_calls_wait_for_timeout(self, mock_page):
        """Should call page.wait_for_timeout with a value in range."""
        await HumanBehavior.human_pause(mock_page, min_ms=500, max_ms=500)
        mock_page.wait_for_timeout.assert_awaited_once()
        called_val = mock_page.wait_for_timeout.call_args[0][0]
        assert 500 <= called_val <= 500  # min == max, no long pause triggered


class TestScrollAmount:
    """Test random_scroll_amount."""

    def test_within_variance(self):
        """Scroll amount should be within ±20% of base."""
        base = 400
        for _ in range(100):
            amount = HumanBehavior.random_scroll_amount(base)
            assert 320 <= amount <= 480  # ±20% of 400

    def test_default_base(self):
        """Default base should be 400."""
        amount = HumanBehavior.random_scroll_amount()
        assert 320 <= amount <= 480


class TestTypingSpeed:
    """Test get_typing_speed."""

    def test_range(self):
        """Should return 50-150ms."""
        for _ in range(100):
            speed = HumanBehavior.get_typing_speed()
            assert 50 <= speed <= 150


class TestHumanType:
    """Test human_type method."""

    @pytest.mark.asyncio
    async def test_success(self, mock_page):
        """Should type text and return True."""
        result = await HumanBehavior.human_type(mock_page, "#email", "test@example.com")
        assert result is True

    @pytest.mark.asyncio
    async def test_failure_returns_false(self, mock_page):
        """Should return False on exception."""
        mock_page.locator.return_value.first.click = AsyncMock(side_effect=Exception("not found"))
        result = await HumanBehavior.human_type(mock_page, "#missing", "text")
        assert result is False


class TestMouseMovement:
    """Test mouse movement helpers."""

    @pytest.mark.asyncio
    async def test_human_mouse_and_scroll(self, mock_page):
        """Should move mouse and optionally scroll without errors."""
        await HumanBehavior.human_mouse_and_scroll(mock_page)
        # Mouse move should have been called at least once
        assert mock_page.mouse.move.await_count >= 1

    @pytest.mark.asyncio
    async def test_human_mouse_no_viewport(self, mock_page):
        """Should handle missing viewport_size gracefully."""
        mock_page.viewport_size = None
        await HumanBehavior.human_mouse_and_scroll(mock_page)
        # Should still move mouse with default dimensions
        assert mock_page.mouse.move.await_count >= 1

    @pytest.mark.asyncio
    async def test_human_mouse_swallows_errors(self, mock_page):
        """Should not raise on mouse errors."""
        mock_page.mouse.move = AsyncMock(side_effect=Exception("mouse error"))
        # Should not raise
        await HumanBehavior.human_mouse_and_scroll(mock_page)


class TestViewportOffset:
    """Test random_viewport_offset."""

    def test_range(self):
        """Offset should be -3 to +3 pixels."""
        for _ in range(100):
            x, y = HumanBehavior.random_viewport_offset()
            assert -3 <= x <= 3
            assert -3 <= y <= 3


class TestMouseSteps:
    """Test random_mouse_steps."""

    def test_zero_distance(self):
        """Zero distance should return at least 1 step."""
        assert HumanBehavior.random_mouse_steps(0) >= 1

    def test_short_distance(self):
        """Short distance should return reasonable steps."""
        steps = HumanBehavior.random_mouse_steps(50)
        assert 6 <= steps <= 40

    def test_long_distance(self):
        """Long distance should be capped at 40."""
        steps = HumanBehavior.random_mouse_steps(10000)
        assert steps <= 40


class TestBuildMousePath:
    """Test build_mouse_path (Bezier curve)."""

    def test_single_step(self):
        """Single step should return just the endpoint."""
        path = HumanBehavior.build_mouse_path((0, 0), (100, 100), steps=1)
        assert path == [(100, 100)]

    def test_start_end_points(self):
        """Path should start near start and end at end."""
        path = HumanBehavior.build_mouse_path((0, 0), (100, 200), steps=10)
        assert len(path) == 10
        # Last point should be the end
        assert abs(path[-1][0] - 100) < 1
        assert abs(path[-1][1] - 200) < 1

    def test_curved_path(self):
        """Path should be curved (midpoint not on straight line)."""
        path = HumanBehavior.build_mouse_path((0, 0), (100, 0), steps=10)
        # Midpoint should have some y deviation from 0
        mid = path[len(path) // 2]
        assert mid[1] != 0  # Should be curved


class TestDistance:
    """Test distance calculation."""

    def test_same_point(self):
        assert HumanBehavior.distance((50, 50), (50, 50)) == 0

    def test_horizontal(self):
        assert HumanBehavior.distance((0, 0), (100, 0)) == 100

    def test_diagonal(self):
        d = HumanBehavior.distance((0, 0), (3, 4))
        assert abs(d - 5) < 0.001


class TestClickTiming:
    """Test click timing helpers."""

    def test_click_hold_ms(self):
        """Should return 35-120ms."""
        for _ in range(100):
            hold = HumanBehavior.click_hold_ms()
            assert 35 <= hold <= 120
