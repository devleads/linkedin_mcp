"""Stealth browser implementation using Patchright."""

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import Optional, Dict, Any, List

from patchright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright

from linkedin_mcp.browser.human import HumanBehavior
from linkedin_mcp.browser.stealth_args import get_stealth_args
from linkedin_mcp.browser.stealth_init import build_stealth_init_script
from linkedin_mcp.browser.navigation import goto_with_retry
from linkedin_mcp.models.profile import ProfileFingerprint

logger = logging.getLogger(__name__)


@dataclass
class BrowserConfig:
    """Configuration for stealth browser instance."""
    profile_id: str
    fingerprint: ProfileFingerprint
    timezone: str  # IANA timezone, e.g., "America/New_York"
    proxy_server: Optional[str] = None
    proxy_username: Optional[str] = None
    proxy_password: Optional[str] = None
    headless: bool = False  # Default: NOT headless (safer for LinkedIn)
    locale: str = "en-US"


class StealthBrowser:
    """Stealth browser powered by Patchright.
    
    Uses Patchright (undetected Playwright fork) to evade bot detection.
    Each instance is isolated with its own browser context, cookies, and storage.
    
    Key anti-detection features:
    - Non-headless mode by default
    - Fingerprint spoofing (platform, WebGL, etc.)
    - Timezone matching proxy country
    - Human-like behavior integration
    """
    
    def __init__(self, config: BrowserConfig):
        self.config = config
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._started = False
        self.human = HumanBehavior()
        self._last_mouse_position: Optional[tuple[float, float]] = None
    
    async def start(self) -> bool:
        """Start browser with stealth configuration.

        Uses comprehensive Chromium launch args to reduce automation
        fingerprinting, and injects stealth init scripts BEFORE any
        page is created so the first page is fully protected.
        """
        if self._started:
            return True
        
        try:
            self._playwright = await async_playwright().start()
            
            # Detect Docker environment for additional sandbox args.
            # Docker runs Linux; Xvfb allows headful mode inside containers,
            # so we check for Linux regardless of headless setting.
            import platform
            is_docker = platform.system() == "Linux"
            
            # Build comprehensive stealth launch args.
            # These disable features that leak automation and enable
            # performance-oriented settings for stable headful mode.
            args = get_stealth_args(headless=self.config.headless, is_docker=is_docker)
            
            launch_options = {
                "headless": self.config.headless,
                "args": args,
            }
            
            # Log proxy status
            if self.config.proxy_server:
                logger.info(f"Proxy server: {self.config.proxy_server}")
                logger.info(f"Proxy username: {self.config.proxy_username[:20]}..." if self.config.proxy_username else "No proxy username")
            else:
                logger.info("Running WITHOUT proxy (profile.country is null)")
            
            # Launch browser with WebRTC disabled
            self._browser = await self._playwright.chromium.launch(**launch_options)
            
            # Build context options with full stealth settings.
            # ignore_https_errors and java_script_enabled are set explicitly
            # to ensure consistent behavior across environments.
            fp = self.config.fingerprint
            context_options = {
                "viewport": {
                    "width": fp.screen_width,
                    "height": fp.screen_height,
                },
                "locale": self.config.locale,
                "timezone_id": self.config.timezone,
                "user_agent": fp.user_agent,
                "color_scheme": "light",
                "ignore_https_errors": True,
                "java_script_enabled": True,
                "is_mobile": False,
                "has_touch": False,
            }
            
            # Add proxy only if configured
            if self.config.proxy_server:
                proxy_options = {
                    "server": self.config.proxy_server,
                }
                if self.config.proxy_username:
                    proxy_options["username"] = self.config.proxy_username
                if self.config.proxy_password:
                    proxy_options["password"] = self.config.proxy_password
                context_options["proxy"] = proxy_options
            
            # Create browser context
            self._context = await self._browser.new_context(**context_options)
            
            # CRITICAL: Apply stealth init scripts BEFORE creating any page.
            # Init scripts only apply to pages created after the script is
            # added. If we create the page first, the first page is unprotected.
            await self._apply_fingerprint_overrides()
            
            # Create initial page (now protected by init scripts)
            self._page = await self._context.new_page()
            
            self._started = True
            logger.info(
                f"Browser started for profile {self.config.profile_id[:8]}... "
                f"(headless={self.config.headless}, timezone={self.config.timezone})"
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to start browser: {e}")
            await self.stop()
            raise
    
    async def _apply_fingerprint_overrides(self) -> None:
        """Apply stealth init scripts to the browser context.
        
        Injects a comprehensive init script that patches browser APIs
        to hide automation signals:
        - navigator.webdriver → undefined
        - navigator.plugins → fake array
        - navigator.platform → match fingerprint
        - window.chrome → { runtime: {} }
        - WebGL vendor/renderer spoofing
        - Canvas fingerprint noise
        - WebRTC disabled (IP leak prevention)
        - Notification/Permissions API fix
        
        This must be called BEFORE any page is created, as init scripts
        only apply to pages created after the script is added.
        """
        if not self._context:
            return
        
        # Build the stealth init script with the profile's fingerprint values.
        fp = self.config.fingerprint
        platform = fp.platform or "MacIntel"
        webgl_vendor = fp.webgl_vendor or "Intel Inc."
        webgl_renderer = fp.webgl_renderer or "Intel Iris OpenGL Engine"
        init_script = build_stealth_init_script(
            platform=platform,
            webgl_vendor=webgl_vendor,
            webgl_renderer=webgl_renderer,
        )
        
        # Add to context — applies to all future pages.
        await self._context.add_init_script(init_script)
        
        logger.debug(f"Applied stealth init scripts for platform={platform}")
    
    async def stop(self) -> None:
        """Stop browser and clean up resources."""
        try:
            if self._context:
                await self._context.close()
                self._context = None
            
            if self._browser:
                await self._browser.close()
                self._browser = None
            
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None
            
            self._page = None
            self._started = False
            
            logger.info(f"Browser stopped for profile {self.config.profile_id[:8]}...")
            
        except Exception as e:
            logger.error(f"Error stopping browser: {e}")
    
    def is_running(self) -> bool:
        """Check if browser is running."""
        return self._started and self._browser is not None and self._browser.is_connected()
    
    @property
    def page(self) -> Optional[Page]:
        """Get the current page instance."""
        return self._page
    
    async def navigate(self, url: str, wait_until: str = "domcontentloaded", timeout: int = 60000) -> Dict[str, Any]:
        """Navigate to URL with human-like delay and idle mouse movement.
        
        Args:
            url: URL to navigate to.
            wait_until: When to consider navigation complete.
            timeout: Navigation timeout in ms (default 60s for proxy connections).
        """
        if not self._page:
            raise RuntimeError("Browser not started")
        
        await self.human.action_delay()
        
        try:
            response = await goto_with_retry(
                self._page, url, wait_until=wait_until, timeout=timeout
            )
            
            await self.human.page_load_delay()
            
            # Simulate idle mouse movement and scroll after page load,
            # mimicking a real user scanning the page after it renders.
            await self.human.human_mouse_and_scroll(self._page)
            
            # Check for redirect loops or auth issues
            final_url = self._page.url
            if "login" in final_url.lower() and "login" not in url.lower():
                logger.warning(f"[navigate] Redirected to login page - session may be invalid")
            
            return {
                "url": final_url,
                "status": response.status if response else None,
            }
        except Exception as e:
            error_msg = str(e)
            if "ERR_TOO_MANY_REDIRECTS" in error_msg:
                logger.error(f"[navigate] Redirect loop detected - cookies may be invalid or expired")
                # Try to get current cookies for debugging
                try:
                    cookies = await self._context.cookies()
                    li_at = next((c for c in cookies if c.get('name') == 'li_at'), None)
                    if li_at:
                        logger.info(f"[navigate] li_at cookie present, expires={li_at.get('expires')}")
                    else:
                        logger.error(f"[navigate] No li_at cookie found in browser context")
                except Exception:
                    pass
            raise
    
    async def click(self, selector: str, timeout: int = 5000) -> bool:
        """Click element with human-like behavior."""
        if not self._page:
            raise RuntimeError("Browser not started")
        
        try:
            return await self.click_human(selector=selector, timeout=timeout)
        except Exception as e:
            logger.warning(f"Click failed for {selector}: {e}")
            return False

    async def click_human(self, selector: str, timeout: int = 5000) -> bool:
        """Click by selector with realistic cursor movement and hover before click."""
        if not self._page:
            raise RuntimeError("Browser not started")

        locator = self._page.locator(selector).first
        await locator.wait_for(state="visible", timeout=timeout)
        return await self._click_locator_human(locator)

    async def click_element_human(self, element: Any, timeout: int = 5000) -> bool:
        """Click an existing element handle with realistic cursor movement.
        
        Includes occasional idle mouse movement before the click to
        simulate a real user scanning the page before interacting.
        """
        if not self._page:
            raise RuntimeError("Browser not started")

        await self.human.action_delay()

        # 30% chance of idle mouse movement before clicking.
        if random.random() < 0.3:
            await self.human.human_mouse_and_scroll(self._page)

        try:
            await element.wait_for_element_state("visible", timeout=timeout)
        except Exception:
            pass

        try:
            await element.scroll_into_view_if_needed(timeout=timeout)
        except Exception:
            pass

        box = await element.bounding_box()
        if not box:
            return False

        target_x, target_y = self._pick_target_point(box)
        await self._move_mouse_humanly(target_x, target_y)
        await self.human.hover_delay()
        await self._page.mouse.down()
        await asyncio.sleep(self.human.click_hold_ms() / 1000)
        await self._page.mouse.up()
        self._last_mouse_position = (target_x, target_y)
        await self.human.post_click_delay()
        return True

    def _pick_target_point(self, box: dict) -> tuple[float, float]:
        """Pick a click point near element center with small jitter, clamped to bounds."""
        center_x = box["x"] + (box["width"] / 2)
        center_y = box["y"] + (box["height"] / 2)
        offset_x, offset_y = self.human.random_viewport_offset()
        target_x = center_x + offset_x
        target_y = center_y + offset_y
        target_x = max(box["x"] + 1, min(box["x"] + box["width"] - 1, target_x))
        target_y = max(box["y"] + 1, min(box["y"] + box["height"] - 1, target_y))
        return target_x, target_y

    async def _click_locator_human(self, locator: Any) -> bool:
        """Execute realistic click flow for a locator.
        
        Includes occasional idle mouse movement before the click to
        simulate a real user scanning the page before interacting.
        """
        if not self._page:
            raise RuntimeError("Browser not started")

        await self.human.action_delay()

        # 30% chance of idle mouse movement before clicking,
        # simulating a user glancing at other content first.
        if random.random() < 0.3:
            await self.human.human_mouse_and_scroll(self._page)

        try:
            await locator.scroll_into_view_if_needed(timeout=3000)
        except Exception:
            pass

        box = await locator.bounding_box()
        if not box:
            return False

        target_x, target_y = self._pick_target_point(box)
        await self._move_mouse_humanly(target_x, target_y)
        await self.human.hover_delay()
        await self._page.mouse.down()
        await asyncio.sleep(self.human.click_hold_ms() / 1000)
        await self._page.mouse.up()
        self._last_mouse_position = (target_x, target_y)
        await self.human.post_click_delay()
        return True

    async def _move_mouse_humanly(self, target_x: float, target_y: float) -> None:
        """Move mouse to target using curved, step-based path."""
        if not self._page:
            raise RuntimeError("Browser not started")

        start = self._last_mouse_position
        if not start:
            viewport = self._page.viewport_size or {"width": 1280, "height": 720}
            start = (
                float(viewport.get("width", 1280)) * random.uniform(0.35, 0.65),
                float(viewport.get("height", 720)) * random.uniform(0.3, 0.7),
            )

        end = (target_x, target_y)
        distance = self.human.distance(start, end)
        steps = self.human.random_mouse_steps(distance)
        path = self.human.build_mouse_path(start, end, steps)

        # Set an initial point so the browser has a known cursor location.
        await self._page.mouse.move(start[0], start[1])
        for x, y in path:
            await self._page.mouse.move(x, y)
            await asyncio.sleep(random.uniform(0.004, 0.02))

        self._last_mouse_position = end
    
    async def type_text(self, selector: str, text: str) -> bool:
        """Type text with human-like character-by-character delays."""
        if not self._page:
            raise RuntimeError("Browser not started")
        
        return await self.human.human_type(self._page, selector, text)
    
    async def scroll(self, pixels: int) -> None:
        """Scroll page with human-like behavior."""
        if not self._page:
            raise RuntimeError("Browser not started")
        
        await self.human.scroll_delay()
        await self._page.evaluate(f"window.scrollBy(0, {pixels})")
    
    async def scroll_down(self, amount: str = "page") -> int:
        """Scroll down with natural variance and human pause. Returns 0 if page navigated.
        
        After scrolling, adds a human_pause to simulate the user reading
        the newly revealed content before taking the next action.
        """
        if amount == "page":
            pixels = self.human.random_scroll_amount(800)
        elif amount == "half":
            pixels = self.human.random_scroll_amount(400)
        else:
            pixels = int(amount)
        
        try:
            await self.scroll(pixels)
            # Human-like pause after scroll to simulate reading.
            await self.human.human_pause(self._page, 300, 1200)
            return pixels
        except Exception as e:
            error_msg = str(e).lower()
            if "context was destroyed" in error_msg or "navigation" in error_msg:
                logger.warning(f"[scroll_down] Page navigated during scroll")
                return 0
            raise
    
    async def get_text(self) -> str:
        """Get all text content from page."""
        if not self._page:
            raise RuntimeError("Browser not started")
        
        return await self._page.evaluate("document.body.innerText || ''")
    
    async def get_html(self) -> str:
        """Get page HTML content."""
        if not self._page:
            raise RuntimeError("Browser not started")
        
        return await self._page.content()
    
    async def screenshot(self, path: Optional[str] = None, full_page: bool = False) -> bytes:
        """Take screenshot."""
        if not self._page:
            raise RuntimeError("Browser not started")
        
        options = {"full_page": full_page}
        if path:
            options["path"] = path
        
        return await self._page.screenshot(**options)
    
    async def set_cookies(self, cookies: List[Dict[str, Any]]) -> int:
        """Set cookies in browser context."""
        if not self._context:
            raise RuntimeError("Browser not started")
        
        # Log important cookies for debugging
        li_at = next((c for c in cookies if c.get('name') == 'li_at'), None)
        jsessionid = next((c for c in cookies if c.get('name') == 'JSESSIONID'), None)
        
        if li_at:
            expires = li_at.get('expires')
            if expires and expires > 0:
                import time
                remaining = expires - time.time()
                if remaining < 0:
                    logger.warning(f"[set_cookies] li_at cookie EXPIRED {-remaining:.0f}s ago!")
                else:
                    logger.info(f"[set_cookies] li_at cookie valid, expires in {remaining/3600:.1f}h")
            else:
                # expires=-1 or None means session cookie (valid until browser closes)
                logger.info(f"[set_cookies] li_at cookie present (session cookie, no expiry)")
        else:
            logger.warning(f"[set_cookies] No li_at cookie - authentication will fail!")
        
        if jsessionid:
            logger.info(f"[set_cookies] JSESSIONID present")
        
        await self._context.add_cookies(cookies)
        logger.info(f"[set_cookies] Added {len(cookies)} cookies to browser context")
        return len(cookies)
    
    async def get_cookies(self, urls: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Get cookies from browser context."""
        if not self._context:
            raise RuntimeError("Browser not started")
        
        if urls:
            return await self._context.cookies(urls)
        return await self._context.cookies()
    
    async def clear_cookies(self) -> None:
        """Clear all cookies."""
        if not self._context:
            raise RuntimeError("Browser not started")
        
        await self._context.clear_cookies()

    async def get_storage_state(self) -> dict:
        """Export the full browser storage state (cookies + localStorage).

        Returns a Playwright storage_state dict that can be persisted to the
        database and later restored via set_storage_state().

        Returns:
            Dict with 'cookies' (list of cookie dicts) and 'origins' (list of
            {origin: str, localStorage: [{name, value}]} entries).
        """
        if not self._context:
            raise RuntimeError("Browser not started")
        return await self._context.storage_state()

    async def set_storage_state(self, state: dict) -> None:
        """Restore browser storage state from a previously exported blob.

        Imports cookies and localStorage origins into the current browser context.
        Cookies are added via add_cookies(); localStorage is injected via an
        init script that runs before page navigation.

        Args:
            state: Playwright storage_state dict with 'cookies' and 'origins'.
        """
        if not self._context:
            raise RuntimeError("Browser not started")

        # Restore cookies
        cookies = state.get("cookies", [])
        if cookies:
            await self._context.add_cookies(cookies)
            logger.info(f"[set_storage_state] Restored {len(cookies)} cookies")

        # Restore localStorage origins by injecting an init script that
        # populates window.localStorage for each origin before any page loads.
        origins = state.get("origins", [])
        for origin_entry in origins:
            origin = origin_entry.get("origin", "")
            items = origin_entry.get("localStorage", [])
            if not origin or not items:
                continue
            # Build a JS snippet that sets localStorage items for this origin.
            # The init script runs on every page load, so we guard by origin.
            js_items = []
            for item in items:
                key = item.get("name", "")
                value = item.get("value", "")
                # Escape for safe JS string embedding
                escaped_key = key.replace("\\", "\\\\").replace("'", "\\'")
                escaped_value = value.replace("\\", "\\\\").replace("'", "\\'")
                js_items.append(f"localStorage.setItem('{escaped_key}', '{escaped_value}');")
            js_code = f"""
            (function() {{
                try {{
                    if (window.location.origin === '{origin}') {{
                        {"\n".join(js_items)}
                    }}
                }} catch(e) {{}}
            }})();
            """
            await self._context.add_init_script(js_code)
            logger.info(f"[set_storage_state] Restored {len(items)} localStorage items for {origin}")
    
    async def evaluate(self, expression: str) -> Any:
        """Evaluate JavaScript expression."""
        if not self._page:
            raise RuntimeError("Browser not started")
        
        return await self._page.evaluate(expression)
    
    async def safe_evaluate(self, expression: str, default: Any = None) -> Any:
        """Evaluate JavaScript expression with error handling for navigation.
        
        Returns default value if page navigates during evaluation.
        """
        if not self._page:
            raise RuntimeError("Browser not started")
        
        try:
            return await self._page.evaluate(expression)
        except Exception as e:
            error_msg = str(e).lower()
            if "context was destroyed" in error_msg or "navigation" in error_msg:
                logger.warning(f"[safe_evaluate] Page navigated during evaluation, returning default")
                return default
            raise
    
    async def safe_scroll(self, x: int = 0, y: int = 500) -> bool:
        """Scroll the page safely, handling navigation errors.
        
        Returns True if scroll succeeded, False if page navigated.
        """
        try:
            await self._page.evaluate(f"window.scrollBy({x}, {y})")
            return True
        except Exception as e:
            error_msg = str(e).lower()
            if "context was destroyed" in error_msg or "navigation" in error_msg:
                logger.warning(f"[safe_scroll] Page navigated during scroll")
                return False
            raise
    
    async def safe_scroll_to(self, x: int = 0, y: int = 0) -> bool:
        """Scroll to absolute position safely, handling navigation errors.
        
        Returns True if scroll succeeded, False if page navigated.
        """
        try:
            await self._page.evaluate(f"window.scrollTo({x}, {y})")
            return True
        except Exception as e:
            error_msg = str(e).lower()
            if "context was destroyed" in error_msg or "navigation" in error_msg:
                logger.warning(f"[safe_scroll_to] Page navigated during scroll")
                return False
            raise
    
    async def safe_scroll_to_bottom(self) -> bool:
        """Scroll to bottom of page safely.
        
        Returns True if scroll succeeded, False if page navigated.
        """
        try:
            await self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            return True
        except Exception as e:
            error_msg = str(e).lower()
            if "context was destroyed" in error_msg or "navigation" in error_msg or "cannot read properties of null" in error_msg:
                logger.warning(f"[safe_scroll_to_bottom] Page navigated during scroll")
                return False
            raise
    
    async def wait_for_selector(self, selector: str, timeout: int = 30000) -> bool:
        """Wait for element to appear."""
        if not self._page:
            raise RuntimeError("Browser not started")
        
        try:
            await self._page.wait_for_selector(selector, timeout=timeout)
            return True
        except Exception:
            return False
    
    async def wait_for_navigation(self, timeout: int = 30000) -> bool:
        """Wait for navigation to complete."""
        if not self._page:
            raise RuntimeError("Browser not started")
        
        try:
            await self._page.wait_for_load_state("domcontentloaded", timeout=timeout)
            return True
        except Exception:
            return False
    
    async def get_current_url(self) -> str:
        """Get current page URL."""
        if not self._page:
            raise RuntimeError("Browser not started")
        return self._page.url
    
    async def get_title(self) -> str:
        """Get current page title."""
        if not self._page:
            raise RuntimeError("Browser not started")
        return await self._page.title()
    
    async def get_page_title(self) -> str:
        """Alias for get_title."""
        return await self.get_title()
    
    async def get_page_content(self) -> str:
        """Get full page HTML content."""
        return await self.get_html()
    
    async def query_selector(self, selector: str) -> Optional[Any]:
        """Query for a single element."""
        if not self._page:
            raise RuntimeError("Browser not started")
        return await self._page.query_selector(selector)
    
    async def query_selector_all(self, selector: str) -> List[Any]:
        """Query for all matching elements."""
        if not self._page:
            raise RuntimeError("Browser not started")
        return await self._page.query_selector_all(selector)
    
    async def set_input_files(self, selector: str, files: List[str]) -> bool:
        """Set files for a file input element.
        
        Args:
            selector: CSS selector for the file input
            files: List of file paths to upload
        
        Returns:
            True if successful, False otherwise
        """
        if not self._page:
            raise RuntimeError("Browser not started")
        
        try:
            await self._page.set_input_files(selector, files)
            return True
        except Exception as e:
            logger.warning(f"set_input_files failed for {selector}: {e}")
            return False
    
    async def locator_set_input_files(self, selector: str, files: List[str]) -> bool:
        """Set files using locator (more reliable for hidden inputs).
        
        Args:
            selector: CSS selector for the file input
            files: List of file paths to upload
        
        Returns:
            True if successful, False otherwise
        """
        if not self._page:
            raise RuntimeError("Browser not started")
        
        try:
            locator = self._page.locator(selector)
            await locator.set_input_files(files)
            return True
        except Exception as e:
            logger.warning(f"locator_set_input_files failed for {selector}: {e}")
            return False
    
    async def upload_file_via_chooser(self, trigger_selector: str, files: List[str], timeout: int = 10000) -> bool:
        """Upload files by clicking a button that triggers a file chooser dialog.
        
        This handles cases where there's no visible file input, but clicking a button
        opens a native file chooser dialog.
        
        Args:
            trigger_selector: CSS selector for the button that triggers file chooser
            files: List of file paths to upload
            timeout: Timeout in milliseconds to wait for file chooser
        
        Returns:
            True if successful, False otherwise
        """
        if not self._page:
            raise RuntimeError("Browser not started")
        
        try:
            async with self._page.expect_file_chooser(timeout=timeout) as fc_info:
                await self._page.click(trigger_selector)
            file_chooser = await fc_info.value
            await file_chooser.set_files(files)
            logger.info(f"File uploaded via chooser: {files}")
            return True
        except Exception as e:
            logger.warning(f"upload_file_via_chooser failed: {e}")
            return False
