"""Session lifecycle, pinning, and capacity tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from linkedin_mcp.browser.session import BrowserSession, SessionManager


def _browser():
    browser = MagicMock()
    browser.is_running.return_value = True
    browser.get_cookies = AsyncMock(return_value=[])
    browser.stop = AsyncMock()
    return browser


@pytest.mark.asyncio
async def test_pinned_session_limit(monkeypatch):
    monkeypatch.setenv("MAX_PINNED_BROWSER_SESSIONS", "1")
    manager = SessionManager()
    manager._sessions["one"] = BrowserSession("one", 1, _browser())
    manager._sessions["two"] = BrowserSession("two", 2, _browser())
    assert await manager.set_persistent("one") is True
    with pytest.raises(RuntimeError, match="capacity"):
        await manager.set_persistent("two")


@pytest.mark.asyncio
async def test_close_all_cancels_cleanup_and_releases_capacity(monkeypatch):
    monkeypatch.setenv("MAX_ACTIVE_BROWSER_SESSIONS", "1")
    manager = SessionManager()
    browser = _browser()
    session = BrowserSession("one", 1, browser, runtime_type="persistent_native")
    manager._sessions["one"] = session
    await manager._capacity.acquire()
    manager._capacity_profiles.add("one")
    manager._start_cleanup_task()
    task = manager._cleanup_task
    await manager.close_all()
    assert task.cancelled()
    assert manager.list_sessions() == []
    assert manager._capacity._value == 1
    browser.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_session_releases_capacity_when_browser_stop_fails(monkeypatch):
    monkeypatch.setenv("MAX_ACTIVE_BROWSER_SESSIONS", "1")
    manager = SessionManager()
    browser = _browser()
    browser.stop.side_effect = RuntimeError("stop failed")
    manager._sessions["one"] = BrowserSession(
        "one", 1, browser, runtime_type="persistent_native"
    )
    await manager._capacity.acquire()
    manager._capacity_profiles.add("one")

    with pytest.raises(RuntimeError, match="stop failed"):
        await manager.close_session("one")

    assert manager._capacity._value == 1


def test_session_reuse_requires_runtime_and_route_match():
    session = BrowserSession(
        "one",
        1,
        _browser(),
        route_identity="route-a",
        runtime_type="legacy_injected",
    )
    assert SessionManager._can_reuse_session(
        session, "route-a", "legacy_injected"
    )
    assert not SessionManager._can_reuse_session(
        session, "route-a", "persistent_native"
    )
    assert not SessionManager._can_reuse_session(
        session, "route-b", "legacy_injected"
    )
