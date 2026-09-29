"""Opt-in smoke test for the installed Chrome channel and native surfaces."""

import os
from pathlib import Path

import pytest
from patchright.async_api import async_playwright


pytestmark = pytest.mark.browser_integration


@pytest.mark.asyncio
async def test_native_chrome_surfaces_are_stable_across_reload(tmp_path):
    if os.getenv("RUN_BROWSER_INTEGRATION") != "1":
        pytest.skip("Set RUN_BROWSER_INTEGRATION=1 in the dedicated browser job")

    fixture = Path(__file__).parent / "fixtures" / "fingerprint_probe.html"
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(tmp_path / "profile"),
            channel=os.getenv("BROWSER_CHANNEL", "chrome"),
            headless=os.getenv("HEADLESS", "false").lower() == "true",
            no_viewport=True,
            locale="en-US",
            timezone_id="UTC",
        )
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(fixture.as_uri())
            first = await page.evaluate("window.browserProbe()")
            await page.reload()
            second = await page.evaluate("window.browserProbe()")
            assert first == second
            assert "Headless" not in first["userAgent"]
            assert first["languages"]
            assert first["timezone"] == "UTC"
            assert first["webdriver"] is False
            assert first["webdriverOwn"] is False
            assert first["pluginsNativeType"] is True
            assert first["pluginsLength"] > 0
            assert first["firstPluginType"] == "[object Plugin]"
        finally:
            await context.close()
