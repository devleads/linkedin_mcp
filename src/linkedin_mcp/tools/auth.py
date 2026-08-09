"""Authentication tools for LinkedIn MCP Server."""

import logging
from typing import Optional, List

import pyotp

from linkedin_mcp.browser.session import get_session_manager, BrowserSession
from linkedin_mcp.browser.human import HumanBehavior
from linkedin_mcp.db import get_db
from linkedin_mcp.db.repository import ProfileRepository, CookieRepository
from linkedin_mcp.security import decrypt_secret

logger = logging.getLogger(__name__)


def _is_closed_browser_error(value: object) -> bool:
    """Return True when error text indicates closed page/context/browser."""
    text = str(value or "").lower()
    indicators = [
        "target page, context or browser has been closed",
        "browser has been closed",
        "context has been closed",
        "page has been closed",
    ]
    return any(token in text for token in indicators)


async def set_cookies(
    profile_id: str,
    li_at: str,
    jsessionid: Optional[str] = None,
    cookies: Optional[List[dict]] = None,
) -> dict:
    """Set LinkedIn authentication cookies for a profile.
    
    Use this for purchased accounts - set li_at cookie directly
    without going through login flow.
    
    Args:
        profile_id: Profile UUID
        li_at: LinkedIn auth token (li_at cookie value)
        jsessionid: Optional JSESSIONID cookie value
        cookies: Optional list of all cookies in format [{"name": "...", "value": "...", "domain": "..."}, ...]
                 If provided, these will be stored in addition to li_at.
                 Export from browser DevTools: Application > Cookies > linkedin.com
    
    Returns:
        Status dict with result
    """
    try:
        with get_db() as db:
            profile_repo = ProfileRepository(db)
            profile = profile_repo.get_by_uuid(profile_id)
            
            if not profile:
                return {
                    "status": "error",
                    "message": f"Profile {profile_id} not found",
                }
            
            cookie_repo = CookieRepository(db)
            cookies_set = []
            
            # If full cookie list provided, store all of them
            if cookies:
                for cookie in cookies:
                    if "linkedin.com" in cookie.get("domain", ""):
                        cookie_repo.set_cookie(
                            profile_id=profile.id,
                            name=cookie["name"],
                            value=cookie["value"],
                            domain=cookie.get("domain", ".linkedin.com"),
                            path=cookie.get("path", "/"),
                            secure=cookie.get("secure", True),
                            http_only=cookie.get("httpOnly", True),
                            same_site=cookie.get("sameSite", "None"),
                            expires=cookie.get("expires"),
                        )
                        cookies_set.append(cookie["name"])
                logger.info(f"Set {len(cookies_set)} cookies from full cookie list")
            else:
                # Legacy mode: just li_at and optionally JSESSIONID
                cookie_repo.set_cookie(
                    profile_id=profile.id,
                    name="li_at",
                    value=li_at,
                )
                cookies_set.append("li_at")
                
                if jsessionid:
                    cookie_repo.set_cookie(
                        profile_id=profile.id,
                        name="JSESSIONID",
                        value=jsessionid,
                    )
                    cookies_set.append("JSESSIONID")
        
        logger.info(f"Set cookies for profile {profile_id[:8]}...")
        
        return {
            "status": "ok",
            "profile_id": profile_id,
            "cookies_set": cookies_set,
        }
        
    except Exception as e:
        logger.error(f"Failed to set cookies: {e}")
        return {
            "status": "error",
            "message": str(e),
        }


async def login(
    profile_id: str,
    email: Optional[str] = None,
    password: Optional[str] = None,
    totp_code: Optional[str] = None,
) -> dict:
    """Login to LinkedIn with credentials.
    
    First attempts to use stored cookies. If that fails or no cookies exist,
    performs full login with email/password and optional 2FA.
    
    Args:
        profile_id: Profile UUID
        email: LinkedIn email (uses profile email if not provided)
        password: LinkedIn password (uses profile password if not provided)
        totp_code: 2FA code if required (or uses profile's TOTP secret)
    
    Returns:
        Status dict with login result
    """
    return await ensure_logged_in(
        profile_id=profile_id,
        email=email,
        password=password,
        totp_code=totp_code,
    )


async def ensure_logged_in(
    profile_id: str,
    email: Optional[str] = None,
    password: Optional[str] = None,
    totp_code: Optional[str] = None,
    reuse_existing_session: bool = True,
) -> dict:
    """Ensure a profile has an authenticated LinkedIn session.

    Reusable helper for other tools that need a logged-in session.
    It prefers existing cookie auth, then falls back to credentials from
    function args or the profiles table.

    When reuse_existing_session is True, it will keep operating in the current
    browser session (if active) to mimic human flow in the same window/tab.
    """
    try:
        creds = _load_profile_credentials(profile_id, email=email, password=password)
        if creds.get("status") == "error":
            return creds

        session_manager = get_session_manager()
        session = session_manager.get_session(profile_id) if reuse_existing_session else None
        if session is not None and not session.browser.is_running():
            session = None
        if session is None:
            session = await session_manager.create_session(profile_id)

        if await _check_logged_in(session):
            return {
                "status": "ok",
                "profile_id": profile_id,
                "method": "cookies",
                "message": "Already logged in via stored cookies",
            }

        login_email = creds["email"]
        login_password = creds["password"]
        totp_secret = creds["totp_secret"]

        if not login_email or not login_password:
            return {
                "status": "error",
                "message": "Email/password not found in profile and not provided",
            }

        credential_login = await _login_with_credentials(
            session=session,
            email=login_email,
            password=login_password,
            totp_code=totp_code,
            totp_secret=totp_secret,
        )
        if credential_login.get("status") != "ok" and _is_closed_browser_error(credential_login.get("message")):
            logger.warning("[ensure_logged_in] Session was closed during login; retrying with a fresh session")
            session = await session_manager.create_session(profile_id, force_new=True)
            credential_login = await _login_with_credentials(
                session=session,
                email=login_email,
                password=login_password,
                totp_code=totp_code,
                totp_secret=totp_secret,
            )

        if credential_login.get("status") != "ok":
            credential_login.setdefault("profile_id", profile_id)
            return credential_login

        if await _check_logged_in(session):
            browser_cookies = await session.browser.get_cookies(["https://www.linkedin.com"])
            with get_db() as db:
                cookie_repo = CookieRepository(db)
                cookie_repo.set_from_playwright(session.profile_db_id, browser_cookies)

            return {
                "status": "ok",
                "profile_id": profile_id,
                "method": "credentials",
                "message": "Login successful",
            }

        return {
            "status": "error",
            "profile_id": profile_id,
            "message": "Login failed - could not verify logged in state",
        }

    except Exception as e:
        logger.error(f"Login failed: {e}")
        return {
            "status": "error",
            "profile_id": profile_id,
            "message": str(e),
        }


def _load_profile_credentials(
    profile_id: str,
    email: Optional[str] = None,
    password: Optional[str] = None,
) -> dict:
    """Load login credentials from profiles table with optional overrides."""
    with get_db() as db:
        profile_repo = ProfileRepository(db)
        profile = profile_repo.get_by_uuid(profile_id)

        if not profile:
            return {
                "status": "error",
                "message": f"Profile {profile_id} not found",
            }

        return {
            "status": "ok",
            "email": email or profile.linkedin_email,
            "password": password or decrypt_secret(profile.linkedin_password_encrypted),
            "totp_secret": profile.totp_secret,
        }


async def _login_with_credentials(
    session: BrowserSession,
    email: str,
    password: str,
    totp_code: Optional[str] = None,
    totp_secret: Optional[str] = None,
) -> dict:
    """Perform the interactive LinkedIn credential login flow."""
    human = HumanBehavior()
    browser = session.browser

    try:
        await browser.clear_cookies()
    except Exception as exc:
        logger.warning(f"[login] Failed to clear stale browser cookies before credential login: {exc}")

    await browser.navigate("https://www.linkedin.com/login")
    await human.page_load_delay()

    username_selectors = [
        "#username",
        "input[name='session_key']",
    ]
    for selector in username_selectors:
        try:
            if await browser.wait_for_selector(selector, timeout=1500):
                if not await browser.type_text(selector, email):
                    return {"status": "error", "message": "Failed to enter email"}
                await human.delay(500, 1000)
                break
        except Exception:
            continue

    password_selectors = [
        "#password",
        "input[name='session_password']",
        "input[autocomplete*='current-password']",
    ]

    password_entered = False
    for selector in password_selectors:
        try:
            if await browser.wait_for_selector(selector, timeout=2500):
                if await browser.type_text(selector, password):
                    password_entered = True
                    break
        except Exception:
            continue

    if not password_entered:
        return {"status": "error", "message": "Failed to enter password"}

    await human.delay(300, 700)

    submit_selectors = [
        "button[type='submit']",
        "button[data-litms-control-urn='login-submit']",
        ".login__form button[type='submit']",
    ]
    submitted = False
    for selector in submit_selectors:
        try:
            if await browser.wait_for_selector(selector, timeout=2000):
                if await browser.click(selector):
                    submitted = True
                    break
        except Exception:
            continue

    if not submitted:
        return {"status": "error", "message": "Failed to click login button"}

    await human.page_load_delay()

    current_url = await browser.get_current_url()
    if "checkpoint" in current_url or "two-step-verification" in current_url:
        code = totp_code
        if not code and totp_secret:
            code = pyotp.TOTP(totp_secret).now()

        if not code:
            return {
                "status": "2fa_required",
                "message": "2FA code required but not provided and no totp_secret in profile",
            }

        await human.delay(1000, 2000)

        selectors = [
            "input[name='pin']",
            "input#input__phone_verification_pin",
            "input.two-step-verification__input",
        ]

        entered = False
        for selector in selectors:
            if await browser.wait_for_selector(selector, timeout=3000):
                if await browser.type_text(selector, code):
                    entered = True
                    break

        if not entered:
            return {"status": "error", "message": "Failed to enter 2FA code"}

        await human.delay(500, 1000)

        if not await browser.click("button[type='submit']"):
            return {"status": "error", "message": "Failed to submit 2FA"}

        await human.page_load_delay()

    return {"status": "ok"}


async def _check_logged_in(session: BrowserSession) -> bool:
    """Check if session is logged in to LinkedIn."""
    try:
        browser = session.browser

        probe_urls = [
            "https://www.linkedin.com/feed/",
            "https://www.linkedin.com/mynetwork/",
        ]

        for probe_url in probe_urls:
            try:
                await browser.navigate(probe_url)
                await HumanBehavior.delay(1200, 2000)
            except Exception:
                continue

            current_url = (await browser.get_current_url() or "").lower()

            # Explicit unauth/challenge endpoints.
            if any(token in current_url for token in ["/checkpoint/", "/challenge/", "captcha", "two-step-verification"]):
                return False
            if "login" in current_url or "authwall" in current_url:
                continue

            # Broader signed-in indicators across evolving LinkedIn shells.
            logged_in_dom = await browser.evaluate("""
                () => {
                    const isVisible = (el) => {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        if (style.display === 'none' || style.visibility === 'hidden') return false;
                        const rect = el.getBoundingClientRect();
                        return rect.width > 0 && rect.height > 0;
                    };

                    const selectors = [
                        '#global-nav',
                        'header nav',
                        '[data-test-global-nav]',
                        'a[href*="/feed/"]',
                        'a[href*="/mynetwork/"]',
                        'a[href*="/messaging/"]',
                        'button[aria-label*="Me" i]',
                    ];

                    for (const selector of selectors) {
                        const nodes = document.querySelectorAll(selector);
                        for (const node of nodes) {
                            if (isVisible(node)) return true;
                        }
                    }

                    const bodyText = (document.body && document.body.innerText || '').toLowerCase();
                    if (bodyText.includes('start a post') || bodyText.includes('home') && bodyText.includes('my network')) {
                        return true;
                    }

                    return false;
                }
            """)

            if logged_in_dom:
                return True

        return False
        
    except Exception as e:
        logger.warning(f"Login check failed: {e}")
        return False


async def get_session_status(profile_id: str) -> dict:
    """Get status of a browser session.
    
    Args:
        profile_id: Profile UUID
    
    Returns:
        Session status information
    """
    session_manager = get_session_manager()
    session = session_manager.get_session(profile_id)
    
    if not session:
        return {
            "status": "no_session",
            "profile_id": profile_id,
        }
    
    # Check if has auth cookies in database
    with get_db() as db:
        cookie_repo = CookieRepository(db)
        has_auth = cookie_repo.has_auth(session.profile_db_id)
    
    return {
        "status": "active",
        "profile_id": profile_id,
        "browser_running": session.browser.is_running(),
        "persistent": session_manager.is_persistent(profile_id),
        "has_cookies": has_auth,
        "created_at": session.created_at.isoformat(),
        "last_activity": session.last_activity.isoformat(),
    }


async def open_manual_browser(profile_id: str, url: Optional[str] = None) -> dict:
    """Open a persistent browser window for manual profile actions.

    The session is pinned and excluded from idle timeout cleanup until
    explicitly closed or unpinned.
    """
    target_url = url or "https://www.linkedin.com/"

    try:
        with get_db() as db:
            profile_repo = ProfileRepository(db)
            profile = profile_repo.get_by_uuid(profile_id)
            if not profile:
                return {
                    "status": "error",
                    "message": f"Profile {profile_id} not found",
                }

        session_manager = get_session_manager()
        session = await session_manager.create_session(profile_id)
        browser = session.browser

        await browser.navigate(target_url)
        await session_manager.set_persistent(profile_id, persistent=True)

        return {
            "status": "ok",
            "profile_id": profile_id,
            "message": "Manual browser opened and pinned (no idle auto-close)",
            "persistent": True,
            "current_url": await browser.get_current_url(),
        }
    except Exception as e:
        logger.error(f"Failed to open manual browser: {e}")
        return {
            "status": "error",
            "message": str(e),
        }


async def save_session_cookies(profile_id: str) -> dict:
    """Persist cookies from an active browser session for a profile."""
    try:
        session_manager = get_session_manager()
        session = session_manager.get_session(profile_id)
        if not session:
            return {
                "status": "error",
                "profile_id": profile_id,
                "message": "No active session found for profile",
            }

        count = await session.save_cookies()
        return {
            "status": "ok",
            "profile_id": profile_id,
            "cookies_saved": count,
            "message": f"Saved {count} LinkedIn cookies from active session",
        }
    except Exception as e:
        logger.error(f"Failed to save session cookies: {e}")
        return {
            "status": "error",
            "profile_id": profile_id,
            "message": str(e),
        }


async def close_session(profile_id: str) -> dict:
    """Close a browser session and save cookies.
    
    Args:
        profile_id: Profile identifier
    
    Returns:
        Status dict
    """
    session_manager = get_session_manager()
    closed = await session_manager.close_session(profile_id)
    
    return {
        "status": "closed" if closed else "not_found",
        "profile_id": profile_id,
    }
