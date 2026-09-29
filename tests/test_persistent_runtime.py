"""Tests for persistent Chrome profile ownership."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from linkedin_mcp.browser.persistent_runtime import PersistentChromeRuntime, ProfileInUseError
from linkedin_mcp.browser.stealth import BrowserConfig
from linkedin_mcp.config import Settings
from linkedin_mcp.models.profile import ProfileFingerprint


PROFILE_ID = "d52e8d51-0abe-4a43-8d96-5da195803235"


def _runtime(tmp_path: Path) -> PersistentChromeRuntime:
    settings = Settings(_env_file=None, browser_profile_root=tmp_path)
    fingerprint = ProfileFingerprint(user_agent="unused", platform="Linux x86_64")
    config = BrowserConfig(profile_id=PROFILE_ID, fingerprint=fingerprint, timezone="UTC")
    return PersistentChromeRuntime(config, settings)


def test_profile_path_is_uuid_scoped(tmp_path):
    runtime = _runtime(tmp_path)
    assert runtime.profile_dir == tmp_path.resolve() / PROFILE_ID


def test_profile_lock_prevents_concurrent_process_ownership(tmp_path):
    first = _runtime(tmp_path)
    second = _runtime(tmp_path)
    first._acquire_profile_lock()
    try:
        with pytest.raises(ProfileInUseError):
            second._acquire_profile_lock()
    finally:
        first._release_profile_lock()


def test_invalid_profile_id_is_rejected(tmp_path):
    settings = Settings(_env_file=None, browser_profile_root=tmp_path)
    fingerprint = ProfileFingerprint(user_agent="unused", platform="Linux x86_64")
    config = BrowserConfig(profile_id="../escape", fingerprint=fingerprint, timezone="UTC")
    with pytest.raises(ValueError):
        PersistentChromeRuntime(config, settings)


def test_only_explicit_marker_counts_as_initialized(tmp_path):
    profile_dir = tmp_path / PROFILE_ID
    profile_dir.mkdir()
    (profile_dir / "Local State").write_text("partial", encoding="utf-8")
    runtime = _runtime(tmp_path)
    assert runtime.was_initialized is False

    runtime.mark_initialized({"runtime_type": "persistent_native"})
    assert runtime.was_initialized is True
    restarted = _runtime(tmp_path)
    assert restarted.was_initialized is True


@pytest.mark.asyncio
async def test_start_uses_native_persistent_context_without_identity_overrides(tmp_path):
    runtime = _runtime(tmp_path)
    page = MagicMock()
    page.is_closed.return_value = False
    context = MagicMock(pages=[page])
    context.close = AsyncMock()
    playwright = MagicMock()
    playwright.chromium.launch_persistent_context = AsyncMock(return_value=context)
    playwright.stop = AsyncMock()
    starter = MagicMock()
    starter.start = AsyncMock(return_value=playwright)
    with patch("linkedin_mcp.browser.persistent_runtime.async_playwright", return_value=starter):
        await runtime.start()
        _, kwargs = playwright.chromium.launch_persistent_context.call_args
        assert kwargs["channel"] == "chrome"
        assert kwargs["no_viewport"] is True
        assert "--disable-blink-features=AutomationControlled" in kwargs["args"]
        assert "user_agent" not in kwargs
        assert "viewport" not in kwargs
        assert "is_mobile" not in kwargs
        await runtime.stop()
