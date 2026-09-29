"""State continuity tests for the shared interaction controller."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from linkedin_mcp.browser.interaction import ActivityPhase, InteractionController


@pytest.mark.asyncio
async def test_click_tracks_cursor_and_uses_visible_precondition():
    page = MagicMock(viewport_size={"width": 1000, "height": 800})
    page.mouse.move = AsyncMock()
    page.mouse.down = AsyncMock()
    page.mouse.up = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    locator = MagicMock()
    locator.wait_for = AsyncMock()
    locator.scroll_into_view_if_needed = AsyncMock()
    locator.bounding_box = AsyncMock(return_value={"x": 100, "y": 200, "width": 80, "height": 40})
    controller = InteractionController(seed=1)
    assert await controller.click(page, locator) is True
    locator.wait_for.assert_awaited_once_with(state="visible", timeout=5000)
    assert controller.state.cursor_x is not None
    assert controller.state.cursor_y is not None


@pytest.mark.asyncio
async def test_typing_moves_from_composing_to_reviewing():
    page = MagicMock()
    locator = MagicMock()
    locator.wait_for = AsyncMock()
    locator.scroll_into_view_if_needed = AsyncMock()
    locator.click = AsyncMock()
    locator.fill = AsyncMock()
    locator.press_sequentially = AsyncMock()
    controller = InteractionController(seed=1)
    assert await controller.type_text(page, locator, "ok") is True
    assert locator.press_sequentially.await_count == 2
    assert controller.state.phase == ActivityPhase.REVIEWING
