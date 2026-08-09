"""Navigation retry helper for transient network errors.

Proxy connections can produce ERR_TIMED_OUT, ERR_CONNECTION_RESET,
ERR_PROXY_CONNECTION_FAILED, etc. These are transient and retryable,
unlike Playwright timeout errors which indicate a real problem.

Usage:
    from linkedin_mcp.browser.navigation import goto_with_retry

    response = await goto_with_retry(page, "https://www.linkedin.com/in/some-profile/")
"""

import asyncio
import logging
import re
from typing import Optional

from patchright.async_api import Page, Response

logger = logging.getLogger(__name__)

# Maximum number of retry attempts for transient network errors.
GOTO_MAX_RETRIES = 3

# Delay between retry attempts in milliseconds.
GOTO_RETRY_DELAY_MS = 3000

# Regex matching transient network/proxy errors that are safe to retry.
# These errors indicate the proxy or network had a temporary issue,
# not that the page itself is broken.
NETWORK_ERROR_RE = re.compile(
    r"ERR_TIMED_OUT|ERR_CONNECTION_RESET|ERR_CONNECTION_REFUSED|"
    r"ERR_PROXY_CONNECTION_FAILED|ERR_TUNNEL_CONNECTION_FAILED|"
    r"ERR_NAME_NOT_RESOLVED|ERR_INTERNET_DISCONNECTED|"
    r"ERR_SOCKET_NOT_CONNECTED|ERR_NETWORK_CHANGED|"
    r"ERR_CONNECTION_CLOSED|ERR_CONNECTION_ABORTED",
    re.IGNORECASE,
)


async def goto_with_retry(
    page: Page,
    url: str,
    wait_until: str = "domcontentloaded",
    timeout: int = 60000,
) -> Optional[Response]:
    """Navigate to a URL with automatic retry on transient network errors.

    Args:
        page: The Patchright Page instance to navigate.
        url: The URL to navigate to.
        wait_until: When to consider navigation complete
                    ("domcontentloaded", "load", or "networkidle").
        timeout: Maximum navigation timeout in milliseconds.

    Returns:
        The Response object from the navigation, or None.

    Raises:
        The last error if all retries are exhausted or a non-retryable
        error occurs.
    """
    last_error: Optional[Exception] = None

    for attempt in range(GOTO_MAX_RETRIES):
        try:
            response = await page.goto(url, wait_until=wait_until, timeout=timeout)
            return response
        except Exception as error:
            last_error = error
            error_msg = str(error)

            # Only retry on transient network/proxy errors.
            is_network_error = bool(NETWORK_ERROR_RE.search(error_msg))
            if not is_network_error or attempt >= GOTO_MAX_RETRIES - 1:
                raise

            logger.warning(
                f"[navigation] Retry {attempt + 1}/{GOTO_MAX_RETRIES} "
                f"for {url}: {error_msg[:120]} — "
                f"retrying in {GOTO_RETRY_DELAY_MS / 1000:.0f}s..."
            )
            await asyncio.sleep(GOTO_RETRY_DELAY_MS / 1000)

    # Should not reach here, but re-raise the last error as a safety net.
    if last_error:
        raise last_error
    return None
