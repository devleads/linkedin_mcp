"""One-time database storage-state migration safety tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from linkedin_mcp.browser.stealth import BrowserConfig, StealthBrowser
from linkedin_mcp.models.profile import ProfileFingerprint


@pytest.mark.asyncio
async def test_local_storage_values_are_json_encoded():
    fingerprint = ProfileFingerprint(user_agent="ua", platform="Linux x86_64")
    browser = StealthBrowser(BrowserConfig("profile", fingerprint, "UTC"))
    browser._context = MagicMock()
    browser._context.add_cookies = AsyncMock()
    browser._context.add_init_script = AsyncMock()
    state = {
        "cookies": [],
        "origins": [{
            "origin": "https://www.linkedin.com",
            "localStorage": [{"name": "quote'key", "value": "line1\nline2'\\"}],
        }],
    }
    await browser.set_storage_state(state)
    script = browser._context.add_init_script.await_args.args[0]
    assert '"quote\'key"' in script
    assert "line1\\nline2" in script
