"""Feed tools for LinkedIn MCP Server."""

import logging
import re
import json
import random
from typing import List, Dict, Any, Optional
from urllib.parse import quote, urlencode

from linkedin_mcp.browser.session import get_session_manager
from linkedin_mcp.browser.human import HumanBehavior
from linkedin_mcp.db import get_db
from linkedin_mcp.db.repository import ProfileRepository, CookieRepository
from linkedin_mcp.tools.scrolling import (
    center_first_visible,
    humanize_post_interaction_viewport,
    jittered_safe_scroll_sequence,
)

logger = logging.getLogger(__name__)


def _is_retryable_navigation_error(error: Exception) -> bool:
    """Return True for transient network/proxy navigation failures."""
    message = str(error).lower()
    return any(
        marker in message
        for marker in [
            "err_tunnel_connection_failed",
            "err_connection_reset",
            "err_network_changed",
            "timeout",
            "target page, context or browser has been closed",
        ]
    )


async def _click_button_human_like(
    browser,
    human: HumanBehavior,
    selectors: Optional[List[str]] = None,
    text_candidates: Optional[List[str]] = None,
    scope_selector: Optional[str] = None,
) -> bool:
    """Click a visible/enabled button using human-like cursor interactions."""
    selectors = selectors or []
    text_candidates = [t.lower() for t in (text_candidates or [])]

    for selector in selectors:
        try:
            candidates = await browser.query_selector_all(selector)
            for candidate in candidates:
                try:
                    if not await candidate.is_visible():
                        continue
                    if not await candidate.is_enabled():
                        continue
                    await human.action_delay()
                    clicked = await browser.click_element_human(candidate)
                    if not clicked:
                        continue
                    return True
                except Exception:
                    continue
        except Exception:
            continue

    if not text_candidates:
        return False

    selector_expr = ", ".join(
        [f'button:has-text("{text}")' for text in text_candidates]
        + [f'a:has-text("{text}")' for text in text_candidates]
        + [f'[role="button"]:has-text("{text}")' for text in text_candidates]
    )

    try:
        if scope_selector:
            scope = browser.page.locator(scope_selector).first
            candidates = scope.locator(selector_expr)
        else:
            candidates = browser.page.locator(selector_expr)

        count = await candidates.count()
        for index in range(count):
            candidate = candidates.nth(index)
            try:
                if not await candidate.is_visible():
                    continue
                if not await candidate.is_enabled():
                    continue
                await human.action_delay()
                clicked = await browser.click_element_human(candidate)
                if clicked:
                    return True
            except Exception:
                continue
    except Exception:
        return False

    return False


async def _type_text_human_like(
    element,
    text: str,
    human: HumanBehavior,
    browser,
    clear_first: bool = True,
) -> bool:
    """Type text with human-like behavior."""
    try:
        clicked = await browser.click_element_human(element)
        if not clicked:
            return False

        await human.delay(200, 400)

        if clear_first:
            await element.evaluate(
                """
                (el) => {
                    const tag = (el.tagName || '').toLowerCase();
                    if (tag === 'textarea' || tag === 'input') {
                        el.value = '';
                    } else if (el.isContentEditable) {
                        el.innerHTML = '';
                    }
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                }
                """
            )

        try:
            await element.focus()
        except Exception:
            pass

        # Human-like variable cadence: bursty typing with occasional thought pauses.
        await human.delay(120, 320)
        base_delay = random.randint(55, 130)
        chars_since_break = 0
        next_micro_break = random.randint(10, 24)
        next_cognitive_break = random.randint(42, 86)

        for ch in text:
            if random.random() < 0.18:
                base_delay = int(max(40, min(180, base_delay + random.randint(-14, 16))))

            if ch in ".!?":
                char_delay = random.randint(70, 180)
            elif ch in ",;:":
                char_delay = random.randint(60, 155)
            elif ch == " ":
                char_delay = random.randint(35, 120)
            else:
                char_delay = int(max(35, min(195, random.gauss(base_delay, 20))))

            await browser.page.keyboard.type(ch, delay=char_delay)
            chars_since_break += 1

            if ch in ".!?":
                await human.delay(220, 620)
            elif ch in ",;:":
                await human.delay(120, 300)
            elif ch == " " and random.random() < 0.14:
                await human.delay(45, 160)

            if chars_since_break >= next_micro_break:
                await human.delay(90, 240)
                chars_since_break = 0
                next_micro_break = random.randint(10, 24)

            next_cognitive_break -= 1
            if next_cognitive_break <= 0:
                await human.delay(320, 980)
                next_cognitive_break = random.randint(42, 86)

        return True
    except Exception:
        return False


async def _detect_auth_wall(browser) -> Optional[str]:
    """Detect LinkedIn auth wall / contextual sign-in overlays on page."""
    try:
        current_url = await browser.get_current_url()
        lowered_url = (current_url or "").lower()
        if "authwall" in lowered_url or "/login" in lowered_url or "login-submit" in lowered_url:
            return f"redirected to auth URL: {current_url}"

        auth_state = await browser.evaluate("""
            () => {
                const isVisible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                };

                const checks = [
                    { selector: '.contextual-sign-in-modal', reason: 'contextual-sign-in-modal visible' },
                    { selector: '.contextual-sign-in-modal__sign-in-form', reason: 'contextual sign-in form present' },
                    { selector: 'form[action*="login-submit"]', reason: 'login-submit form present' },
                    { selector: '[data-test-id="nav-header-signin"]', reason: 'guest nav sign-in CTA present' },
                ];

                for (const check of checks) {
                    const node = document.querySelector(check.selector);
                    if (isVisible(node)) {
                        return { blocked: true, reason: check.reason };
                    }
                }

                const pageText = (document.body && document.body.innerText ? document.body.innerText : '').toLowerCase();
                if (pageText.includes('sign in to view more content') ||
                    pageText.includes('create your free account or sign in')) {
                    return { blocked: true, reason: 'public page sign-in prompt text detected' };
                }

                return { blocked: false, reason: '' };
            }
        """)

        if auth_state and auth_state.get("blocked"):
            return auth_state.get("reason") or "auth wall detected"
        return None
    except Exception:
        return None


def _extract_activity_token(post_url: str) -> Optional[str]:
    """Extract LinkedIn activity id token from post URL if present."""
    if not post_url:
        return None

    patterns = [
        r"activity[-:](\d+)",
        r"ugcPost[-:](\d+)",
        r"/posts/[^\s]*-(\d+)(?:[-/?#]|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, post_url)
        if match:
            return match.group(1)
    return None


async def _comment_preflight_auth_check(browser, human: HumanBehavior) -> Optional[str]:
    """Hard auth preflight before comment action."""
    try:
        await browser.navigate("https://www.linkedin.com/feed/")
        await human.page_load_delay()

        auth_wall_reason = await _detect_auth_wall(browser)
        if auth_wall_reason:
            return f"preflight auth wall detected ({auth_wall_reason})"

        nav_ready = await browser.evaluate("""
            () => {
                return !!(
                    document.querySelector('#global-nav') ||
                    document.querySelector('header[role="banner"]') ||
                    document.querySelector('[data-test-global-nav]')
                );
            }
        """)
        if not nav_ready:
            return "preflight failed: authenticated navigation not detected"
        return None
    except Exception as e:
        return f"preflight failed: {e}"


def _is_meaningful_post(post: Optional[Dict[str, Any]]) -> bool:
    """Return True when extracted post has usable signal (not placeholder card)."""
    if not post:
        return False
    if post.get("is_promoted"):
        return False

    author = (post.get("author") or {}).get("name")
    headline = (post.get("author") or {}).get("headline")
    content = post.get("content")
    post_url = post.get("url")
    timestamp = post.get("timestamp")
    engagement = post.get("engagement") or {}
    likes = engagement.get("likes")
    comments = engagement.get("comments")

    text_candidates = [
        (author or "").strip().lower(),
        (headline or "").strip().lower(),
        (content or "").strip().lower(),
    ]
    blocked_fragments = [
        "start a post",
        "new posts",
        "today's puzzles",
        "add to your feed",
        "view all recommendations",
        "promoted",
    ]
    if any(any(fragment in text for fragment in blocked_fragments) for text in text_candidates if text):
        return False

    return any([
        bool(author),
        bool(content),
        bool(post_url),
        bool(timestamp),
        likes is not None,
        comments is not None,
    ])


def _normalize_linkedin_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    value = str(url).strip()
    if not value:
        return None
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if value.startswith("/"):
        return f"https://www.linkedin.com{value}"
    return value


def _normalize_feed_post(post_data: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Normalize parser outputs into stable feed post schema."""
    if not post_data:
        return None

    author_obj = post_data.get("author") if isinstance(post_data.get("author"), dict) else {}
    engagement_obj = post_data.get("engagement") if isinstance(post_data.get("engagement"), dict) else {}

    likes_raw = engagement_obj.get("likes") if "likes" in engagement_obj else post_data.get("likes")
    comments_raw = engagement_obj.get("comments") if "comments" in engagement_obj else post_data.get("comments")
    post_url = post_data.get("post_url") or post_data.get("url")
    activity_urn = post_data.get("activity_urn")
    featured_urn = post_data.get("featured_urn")

    author_name = author_obj.get("name") or post_data.get("author_name")
    author_headline = author_obj.get("headline") or post_data.get("author_headline")
    author_url = _normalize_linkedin_url(author_obj.get("url") or post_data.get("author_url"))

    profile_url = _normalize_linkedin_url(post_data.get("profile_url"))
    company_url = _normalize_linkedin_url(post_data.get("company_url"))

    normalized_post_url = _normalize_linkedin_url(post_url)
    if normalized_post_url:
        post_url = normalized_post_url

    likes = likes_raw if isinstance(likes_raw, int) else _parse_count(str(likes_raw)) if likes_raw else None
    comments = comments_raw if isinstance(comments_raw, int) else _parse_count(str(comments_raw)) if comments_raw else None

    if not post_url:
        urn_value = activity_urn or featured_urn
        if urn_value:
            urn_text = str(urn_value)
            if urn_text.startswith("urn:li:activity:") or urn_text.startswith("urn:li:ugcPost:") or urn_text.startswith("urn:li:share:"):
                post_url = f"https://www.linkedin.com/feed/update/{urn_text}"
            elif urn_text.isdigit():
                post_url = f"https://www.linkedin.com/feed/update/urn:li:activity:{urn_text}"

    candidate_urls = [post_url, author_url]
    if not profile_url:
        profile_url = next((u for u in candidate_urls if u and "/in/" in u), None)
    if not company_url:
        company_url = next((u for u in candidate_urls if u and "/company/" in u), None)

    if not author_url:
        author_url = profile_url or company_url

    return {
        "author": {
            "name": author_name,
            "headline": author_headline,
            "url": author_url,
        },
        "content": post_data.get("content"),
        "engagement": {
            "likes": likes,
            "comments": comments,
        },
        "url": post_url,
        "post_url": post_url,
        "profile_url": profile_url,
        "company_url": company_url,
        "timestamp": post_data.get("timestamp"),
        "is_promoted": bool(post_data.get("is_promoted")),
    }


async def _scroll_feed_for_more(browser, human: HumanBehavior) -> None:
    """Scroll LinkedIn feed with SDUI-aware behavior before fallback page scroll."""
    scroll_amount = max(500, min(1600, human.random_scroll_amount(900)))
    micro_scroll_steps = random.randint(1, 3)

    load_more_clicked = await _click_button_human_like(
        browser,
        human,
        selectors=['button'],
        text_candidates=['load more'],
    )
    if load_more_clicked:
        logger.info("[read_feed] Scrolled via SDUI 'Load more' button")
        await human.delay(2200, 4200)
        return

    scroll_mode = await browser.evaluate("""
        () => {
            const scrollAmount = __SCROLL_AMOUNT__;
            const microSteps = __MICRO_STEPS__;

            const feed = document.querySelector('[role="list"][data-testid="mainFeed"], [data-testid="mainFeed"]');
            if (!feed) return 'no-feed';

            const listItems = Array.from(feed.querySelectorAll('[role="listitem"]'));
            const target = listItems.length > 0
                ? listItems[listItems.length - 1]
                : (feed.lastElementChild || feed);

            if (target && target.scrollIntoView) {
                target.scrollIntoView({ behavior: 'auto', block: 'end' });
            }

            const step = Math.max(250, Math.floor(scrollAmount / Math.max(1, microSteps)));
            for (let i = 0; i < microSteps; i += 1) {
                window.scrollBy(0, step);
            }
            return 'scrolled-listitem';
        }
    """.replace("__SCROLL_AMOUNT__", str(scroll_amount)).replace("__MICRO_STEPS__", str(micro_scroll_steps)))

    if scroll_mode == "scrolled-listitem":
        logger.info(f"[read_feed] Scrolled via SDUI feed container (px={scroll_amount}, steps={micro_scroll_steps})")
        await human.delay(1300, 2800)
    else:
        await browser.scroll_down("page")
        logger.info("[read_feed] Scrolled via generic page scroll")
        await human.delay(1500, 3000)

    if random.random() < 0.25:
        await human.delay(1000, 2200)


async def read_feed(
    profile_id: str,
    max_posts: int = 10,
    scroll_count: int = 3,
) -> dict:
    """Read LinkedIn feed posts.
    
    Args:
        profile_id: Profile UUID
        max_posts: Maximum number of posts to return
        scroll_count: Number of times to scroll for more content
    
    Returns:
        Dict with feed posts
    """
    logger.info(f"[read_feed] Starting for profile {profile_id}")
    
    try:
        # Verify profile exists
        logger.info(f"[read_feed] Checking profile in database...")
        with get_db() as db:
            profile_repo = ProfileRepository(db)
            profile = profile_repo.get_by_uuid(profile_id)
            if not profile:
                logger.error(f"[read_feed] Profile {profile_id} not found in database")
                return {
                    "status": "error",
                    "message": f"Profile {profile_id} not found",
                }
            logger.info(f"[read_feed] Profile found: country={profile.country}, has_fingerprint={profile.fingerprint is not None}")
            
            # Check if cookies exist
            cookie_repo = CookieRepository(db)
            cookies = cookie_repo.to_playwright_format(profile.id)
            logger.info(f"[read_feed] Found {len(cookies)} cookies in database")
            li_at_cookie = next((c for c in cookies if c.get('name') == 'li_at'), None)
            if li_at_cookie:
                logger.info(f"[read_feed] li_at cookie found (length={len(li_at_cookie.get('value', ''))})")
            else:
                logger.warning(f"[read_feed] No li_at cookie found - authentication may fail")
        
        # Get or create session
        logger.info(f"[read_feed] Creating browser session...")
        session_manager = get_session_manager()
        session = await session_manager.create_session(profile_id)
        browser = session.browser
        human = HumanBehavior()
        logger.info(f"[read_feed] Browser session created")
        
        # Navigate to feed
        logger.info(f"[read_feed] Navigating to LinkedIn feed...")
        try:
            await browser.navigate("https://www.linkedin.com/feed/")
        except Exception as nav_error:
            if _is_retryable_navigation_error(nav_error):
                logger.warning(f"[read_feed] Feed navigation failed, rotating session/proxy once: {nav_error}")
                session = await session_manager.create_session(profile_id, force_new=True)
                browser = session.browser
                await browser.navigate("https://www.linkedin.com/feed/")
            else:
                raise
        await human.page_load_delay()
        
        # Check if logged in
        current_url = await browser.get_current_url()
        logger.info(f"[read_feed] Current URL after navigation: {current_url}")
        
        if "login" in current_url or "authwall" in current_url:
            logger.error(f"[read_feed] Redirected to login page - not authenticated")
            # Get page title for more context
            page_title = await browser.get_page_title()
            logger.error(f"[read_feed] Page title: {page_title}")
            return {
                "status": "error",
                "code": "auth_required",
                "message": f"Not logged in - redirected to {current_url}",
                "details": {
                    "current_url": current_url,
                    "page_title": page_title,
                    "li_at_cookie_present": li_at_cookie is not None if 'li_at_cookie' in dir() else False,
                }
            }
        
        # Wait for feed to load - try multiple selectors (desktop and mobile-lite)
        logger.info(f"[read_feed] Waiting for feed content to load...")
        
        # Selectors for different LinkedIn layouts
        feed_selectors = [
            ".feed-shared-update-v2",           # Desktop
            "article[data-activity-urn]",       # Mobile-lite (mwlite)
            "li.feed-item",                     # Mobile-lite container
            "[data-testid='mainFeed']",         # SDUI feed list root
            "[data-component-type='LazyColumn'][data-testid='mainFeed']",
            "[role='list'][data-testid='mainFeed']",
            ".main-feed-activity-card",         # Newer feed card
            "[data-test-id='main-feed-activity-card']",
            "div[data-id='main-feed-card']",
            "div[data-urn^='urn:li:activity']", # Activity container
            ".occludable-update",               # Desktop variant
        ]
        
        feed_found = False
        for selector in feed_selectors:
            if await browser.wait_for_selector(selector, timeout=7000):
                logger.info(f"[read_feed] Found feed with selector: {selector}")
                feed_found = True
                break
        
        if not feed_found:
            # Try to get more diagnostic info
            page_title = await browser.get_page_title()
            page_content = await browser.get_page_content()
            logger.error(f"[read_feed] Feed selector not found. Title: {page_title}")
            logger.error(f"[read_feed] Page content length: {len(page_content)} chars")
            
            feed_probe = await browser.evaluate("""
                () => {
                    const counts = {
                        legacyDesktop: document.querySelectorAll('.feed-shared-update-v2').length,
                        legacyMobile: document.querySelectorAll('article[data-activity-urn], li.feed-item').length,
                        sduiMainFeed: document.querySelectorAll('[data-testid="mainFeed"], [role="list"][data-testid="mainFeed"]').length,
                        mainFeedCard: document.querySelectorAll('.main-feed-activity-card, [data-test-id="main-feed-activity-card"], div[data-id="main-feed-card"]').length,
                        activityUrn: document.querySelectorAll('div[data-urn^="urn:li:activity"]').length,
                    };
                    const hasMain = !!document.querySelector('[role="main"], main');
                    const hasGlobalNav = !!document.querySelector('#global-nav, header[role="banner"]');
                    return { counts, hasMain, hasGlobalNav };
                }
            """)
            logger.info(f"[read_feed] Feed probe: {feed_probe}")

            # Check for common error indicators
            if "challenge" in current_url.lower() or "checkpoint" in current_url.lower():
                logger.error(f"[read_feed] Security challenge detected")
                return {
                    "status": "error",
                    "message": "LinkedIn security challenge detected - manual intervention required",
                    "details": {"current_url": current_url}
                }
            
            has_any_feed_candidates = any((feed_probe.get("counts") or {}).values()) if isinstance(feed_probe, dict) else False
            if has_any_feed_candidates:
                logger.warning("[read_feed] Feed cards detected by probe despite selector wait miss; continuing to extraction")
            else:
                return {
                    "status": "error",
                    "message": "Feed did not load - no feed selectors found",
                    "details": {
                        "current_url": current_url,
                        "page_title": page_title,
                        "content_length": len(page_content),
                        "feed_probe": feed_probe,
                    }
                }
        
        posts = []
        stagnant_scrolls = 0
        
        # Wait a bit more for dynamic content to load (social counts, etc.)
        await human.delay(2000, 3000)
        
        # Scroll and collect posts
        for i in range(scroll_count):
            await human.scroll_delay()
            posts_before = len(posts)

            feed_item_count_before = await browser.evaluate("""
                () => document.querySelectorAll('[role="list"][data-testid="mainFeed"] > div, [data-testid="mainFeed"] > div').length
            """)
            
            # Extract posts from current view
            new_posts = await _extract_feed_posts(browser)
            
            for post in new_posts:
                if post not in posts and len(posts) < max_posts:
                    posts.append(post)
            
            if len(posts) >= max_posts:
                break
            
            # Scroll down (SDUI-aware)
            await _scroll_feed_for_more(browser, human)

            feed_item_count_after = await browser.evaluate("""
                () => document.querySelectorAll('[role="list"][data-testid="mainFeed"] > div, [data-testid="mainFeed"] > div').length
            """)
            logger.info(
                f"[read_feed] Scroll iteration {i + 1}/{scroll_count}: "
                f"mainFeed children before={feed_item_count_before}, after={feed_item_count_after}, "
                f"unique_posts={len(posts)}"
            )

            posts_added = len(posts) - posts_before
            if posts_added <= 0 and feed_item_count_after <= feed_item_count_before:
                stagnant_scrolls += 1
            else:
                stagnant_scrolls = 0

            if stagnant_scrolls >= 3:
                logger.info("[read_feed] Stopping early after repeated no-growth scrolls")
                break
        
        # Save cookies after activity
        browser_cookies = await browser.get_cookies(["https://www.linkedin.com"])
        with get_db() as db:
            cookie_repo = CookieRepository(db)
            cookie_repo.set_from_playwright(session.profile_db_id, browser_cookies)
        
        return {
            "status": "ok",
            "profile_id": profile_id,
            "post_count": len(posts),
            "posts": posts[:max_posts],
        }
        
    except Exception as e:
        logger.error(f"Failed to read feed: {e}")
        return {
            "status": "error",
            "message": str(e),
        }


async def search_posts(
    profile_id: str,
    keywords: List[str],
    max_posts: int = 10,
    scroll_count: int = 3,
) -> dict:
    """Search for LinkedIn posts using desktop browser.
    
    Navigates to LinkedIn search results page, clicks Posts filter,
    and extracts posts from the desktop UI.
    
    Args:
        profile_id: Profile UUID
        keywords: List of keywords to search for
        max_posts: Maximum number of posts to return
        scroll_count: Number of times to scroll for more content
    
    Returns:
        Dict with posts matching the keywords
    """
    if not keywords:
        return {
            "status": "error",
            "message": "At least one keyword is required",
        }
    
    query = " ".join(kw.strip() for kw in keywords if kw.strip())
    
    logger.info(f"[search_posts] Searching for: {query}")
    
    try:
        # Verify profile exists
        with get_db() as db:
            profile_repo = ProfileRepository(db)
            profile = profile_repo.get_by_uuid(profile_id)
            if not profile:
                return {
                    "status": "error",
                    "message": f"Profile {profile_id} not found",
                }
        
        # Get or create session
        session_manager = get_session_manager()
        session = await session_manager.create_session(profile_id)
        browser = session.browser
        human = HumanBehavior()

        # First navigate to feed to establish session, then search
        # This is more human-like than direct navigation to search URL
        logger.info(f"[search_posts] Navigating to feed first...")
        await browser.navigate("https://www.linkedin.com/feed/")
        await human.page_load_delay()
        
        # Check if logged in
        current_url = await browser.get_current_url()
        if "login" in current_url or "authwall" in current_url:
            return {
                "status": "error",
                "message": "Not logged in - redirected to login page",
            }
        
        # Wait for feed to load
        await browser.wait_for_selector('[role="main"]', timeout=10000)
        await human.delay(2000, 3000)
        
        # Now navigate to search results
        encoded_query = quote(query)
        search_url = f"https://www.linkedin.com/search/results/content/?keywords={encoded_query}&origin=GLOBAL_SEARCH_HEADER"
        
        logger.info(f"[search_posts] Navigating to search: {search_url}")
        await browser.navigate(search_url)
        await human.page_load_delay()
        
        # Wait for search results to load
        await browser.wait_for_selector('[role="main"]', timeout=15000)
        await human.delay(1000, 2000)
        
        # Wait for loader to disappear and content to load
        try:
            # Wait for loader to disappear
            await browser.evaluate("""
                () => new Promise((resolve) => {
                    const checkLoader = () => {
                        const loader = document.querySelector('[data-testid="loader"]');
                        if (!loader) {
                            resolve(true);
                        } else {
                            setTimeout(checkLoader, 500);
                        }
                    };
                    checkLoader();
                    // Timeout after 10 seconds
                    setTimeout(() => resolve(false), 10000);
                })
            """)
        except Exception:
            pass
        
        await human.delay(2000, 3000)
        
        all_posts = []
        original_url = await browser.get_current_url()
        
        # Scroll and extract posts
        for scroll_num in range(scroll_count):
            # Touch session to prevent idle cleanup during long scrolling
            session.touch()
            
            logger.info(f"[search_posts] Scroll {scroll_num + 1}/{scroll_count}")
            
            # Extract posts from current view
            try:
                posts = await _extract_desktop_search_posts(browser)
                
                for post in posts:
                    # Avoid duplicates by checking URL
                    if post.get("url") and not any(p.get("url") == post.get("url") for p in all_posts):
                        all_posts.append(post)
                
                logger.info(f"[search_posts] Total posts collected: {len(all_posts)}")
            except Exception as e:
                logger.warning(f"[search_posts] Error extracting posts: {e}")
                # Wait for page to stabilize after navigation
                await human.delay(2000, 3000)
                continue
            
            if len(all_posts) >= max_posts:
                break
            
            # Scroll down with shared jittered strategy
            scroll_ok = await jittered_safe_scroll_sequence(
                browser,
                human,
                steps=2,
                base_pixels=400,
                delay_min_ms=800,
                delay_max_ms=1500,
                on_navigation_delay_min_ms=3000,
                on_navigation_delay_max_ms=4000,
            )
            
            if scroll_ok:
                await browser.safe_scroll_to_bottom()
                await human.delay(1500, 2500)  # Longer delay after scroll to bottom
            else:
                # Page navigated during scroll
                logger.warning(f"[search_posts] Page navigated during scroll, waiting...")
                await human.delay(3000, 4000)
                
                # Check if we navigated away from search results
                try:
                    current_url = await browser.get_current_url()
                    if "search/results/content" not in current_url:
                        logger.warning(f"[search_posts] Navigated away from search: {current_url}")
                        await browser.navigate(original_url)
                        await human.delay(2000, 3000)
                    else:
                        await browser.wait_for_selector('[role="main"]', timeout=10000)
                except Exception:
                    pass
            
            # Try to click "Load more" button if present
            load_more_clicked = await browser.safe_evaluate("""
                () => {
                    const buttons = document.querySelectorAll('button');
                    for (const btn of buttons) {
                        const text = btn.textContent.trim().toLowerCase();
                        if (text === 'load more' || text.includes('load more')) {
                            btn.scrollIntoView({behavior: 'smooth', block: 'center'});
                            return true;
                        }
                    }
                    return false;
                }
            """, default=False)
            if load_more_clicked:
                await human.delay(500, 800)
                clicked = await _click_button_human_like(
                    browser,
                    human,
                    selectors=['button'],
                    text_candidates=['load more'],
                )
                if clicked:
                    logger.info("[search_posts] Clicked 'Load more' button")
                    await human.delay(1500, 2500)
            
            # Additional small delay for content to render
            await human.delay(500, 1000)
        
        # Save cookies
        browser_cookies = await browser.get_cookies(["https://www.linkedin.com"])
        with get_db() as db:
            cookie_repo = CookieRepository(db)
            cookie_repo.set_from_playwright(session.profile_db_id, browser_cookies)
        
        return {
            "status": "ok",
            "profile_id": profile_id,
            "keywords": keywords,
            "query": query,
            "post_count": len(all_posts[:max_posts]),
            "posts": all_posts[:max_posts],
        }
        
    except Exception as e:
        logger.error(f"Failed to search posts: {e}")
        import traceback
        traceback.print_exc()
        return {
            "status": "error",
            "message": str(e),
        }


async def _extract_desktop_search_posts(browser) -> List[Dict[str, Any]]:
    """Extract posts from desktop search results page using new React UI selectors."""
    
    js_extract = """
    () => {
        const posts = [];
        const seenContent = new Set();
        
        // Find all post containers with role="listitem"
        const postContainers = document.querySelectorAll('[role="listitem"]');
        
        console.log('Found ' + postContainers.length + ' listitem containers');
        
        for (const container of postContainers) {
            // Must have expandable text box (post content)
            const contentEl = container.querySelector('[data-testid="expandable-text-box"]');
            if (!contentEl) continue;
            
            const content = contentEl.textContent.trim();
            if (!content || content.length < 20) continue;
            
            // Skip duplicates by content snippet
            const contentKey = content.substring(0, 100);
            if (seenContent.has(contentKey)) continue;
            seenContent.add(contentKey);
            try {
                const post = {
                    author_name: null,
                    author_headline: null,
                    author_url: null,
                    content: null,
                    timestamp: null,
                    url: null,
                    likes: null,
                    comments: null
                };
                
                // Author name - look for profile link with nested p tag containing name
                const authorLinks = container.querySelectorAll('a[href*="/in/"], a[href*="/company/"]');
                for (const authorLink of authorLinks) {
                    const href = authorLink.getAttribute('href') || '';
                    if ((href.includes('/in/') || href.includes('/company/')) && !href.includes('miniProfile')) {
                        // Look for p tag with the bold name class pattern
                        const pEl = authorLink.querySelector('p._34794bbe, p[class*="_34794bbe"]');
                        if (pEl) {
                            const name = pEl.textContent.trim();
                            if (name && name.length > 1 && name.length < 100) {
                                post.author_name = name;
                                post.author_url = href;
                                break;
                            }
                        }
                        // Fallback: any p tag inside the link
                        if (!post.author_name) {
                            const anyP = authorLink.querySelector('p');
                            if (anyP) {
                                const name = anyP.textContent.trim();
                                if (name && name.length > 1 && name.length < 80 && !name.includes('•')) {
                                    post.author_name = name;
                                    post.author_url = href;
                                    break;
                                }
                            }
                        }
                    }
                }
                
                // Author headline - look for text that looks like a job title
                // Usually appears after the author name in a separate element
                const allParagraphs = container.querySelectorAll('p');
                for (const p of allParagraphs) {
                    const text = p.textContent.trim();
                    // Skip if it's the name, content, or timestamp
                    if (text && 
                        text !== post.author_name && 
                        text.length > 15 && 
                        text.length < 200 &&
                        !text.includes('•') &&
                        !text.match(/^\\d+[hdwmy]/) &&
                        !text.startsWith('#')) {
                        // Check if it looks like a headline (contains job-related words or structure)
                        if (!post.author_headline) {
                            // Skip if this is the post content
                            const contentEl = container.querySelector('[data-testid="expandable-text-box"]');
                            if (contentEl && contentEl.textContent.includes(text)) {
                                continue;
                            }
                            post.author_headline = text;
                            break;
                        }
                    }
                }
                
                // Post content - already extracted above
                post.content = content;
                
                // Timestamp - look for text with time indicators (e.g., "3d", "15m", "2h", "50m •")
                const allText = container.querySelectorAll('p, span');
                for (const el of allText) {
                    const text = el.textContent.trim();
                    // Match patterns like "3d", "15m", "2h", "1w", "3mo", "1y", "50m •"
                    if (text.match(/^\d+[hdwmy]$/) || 
                        text.match(/^\d+mo$/) ||
                        text.match(/^\d+[mhdwy]\s*•/) || 
                        text.match(/^\d+\s*(hour|day|week|month|year|min)/i)) {
                        post.timestamp = text.split('•')[0].trim();
                        break;
                    }
                }
                
                // Post URL - look for feed/update links
                const postLinks = container.querySelectorAll('a[href*="/feed/update/"], a[href*="ugcPost"], a[href*="activity:"]');
                for (const pLink of postLinks) {
                    const pHref = pLink.getAttribute('href');
                    if (pHref && (pHref.includes('/feed/update/') || pHref.includes('ugcPost') || pHref.includes('activity:'))) {
                        post.url = pHref;
                        break;
                    }
                }
                
                // Engagement - robust parsing for modern desktop search cards
                const parseCountFromText = (value) => {
                    const text = (value || '').trim().toLowerCase();
                    if (!text) return null;
                    const m = text.match(/(\d+(?:[.,]\d+)?)\s*([km])?/i);
                    if (!m) return null;
                    const num = parseFloat(m[1].replace(',', '.'));
                    if (Number.isNaN(num)) return null;
                    const suffix = (m[2] || '').toLowerCase();
                    let multiplier = 1;
                    if (suffix === 'k') multiplier = 1000;
                    if (suffix === 'm') multiplier = 1000000;
                    return String(Math.round(num * multiplier));
                };

                const socialRoot =
                    container.querySelector('[class*="social-details-social-counts"]') ||
                    container.querySelector('[class*="social-details"]') ||
                    container.querySelector('[class*="feed-shared-social-counts"]') ||
                    container;

                const explicitLikeNode =
                    socialRoot.querySelector('.social-details-social-counts__reactions-count') ||
                    socialRoot.querySelector('[aria-label*="reaction" i]') ||
                    socialRoot.querySelector('[aria-label*="like" i]');
                if (explicitLikeNode) {
                    const likeText =
                        explicitLikeNode.getAttribute('aria-label') ||
                        explicitLikeNode.textContent || '';
                    const parsed = parseCountFromText(likeText);
                    if (parsed) post.likes = parsed;
                }

                const explicitCommentNode =
                    socialRoot.querySelector('.social-details-social-counts__comments') ||
                    socialRoot.querySelector('[aria-label*="comment" i]') ||
                    socialRoot.querySelector('button[aria-label*="comment" i]');
                if (explicitCommentNode) {
                    const commentText =
                        explicitCommentNode.getAttribute('aria-label') ||
                        explicitCommentNode.textContent || '';
                    const parsed = parseCountFromText(commentText);
                    if (parsed) post.comments = parsed;
                }

                const engagementNodes = socialRoot.querySelectorAll('span, button, a, div');
                for (const node of engagementNodes) {
                    const text = (node.getAttribute('aria-label') || node.textContent || '').trim();
                    if (!text || text.length > 80) continue;
                    const lowered = text.toLowerCase();

                    if (!post.likes && (lowered.includes('reaction') || lowered.includes('like'))) {
                        const parsed = parseCountFromText(text);
                        if (parsed) post.likes = parsed;
                    }

                    if (!post.comments && lowered.includes('comment')) {
                        const parsed = parseCountFromText(text);
                        if (parsed) post.comments = parsed;
                    }

                    if (post.likes && post.comments) break;
                }
                
                // Only add if we have meaningful content (post content is required)
                if (post.content) {
                    posts.push(post);
                }
            } catch (e) {
                console.error('Error parsing post:', e);
            }
        }
        
        return posts;
    }
    """
    
    try:
        raw_posts = await browser.evaluate(js_extract)
        
        posts = []
        for raw in raw_posts:
            post = {
                "author": {
                    "name": raw.get("author_name"),
                    "headline": raw.get("author_headline"),
                    "url": raw.get("author_url"),
                },
                "content": raw.get("content"),
                "engagement": {
                    "likes": _parse_count(raw.get("likes")) if raw.get("likes") else None,
                    "comments": _parse_count(raw.get("comments")) if raw.get("comments") else None,
                },
                "url": raw.get("url"),
                "timestamp": raw.get("timestamp"),
            }
            posts.append(post)
        
        return posts
        
    except Exception as e:
        logger.error(f"[_extract_desktop_search_posts] Error: {e}")
        return []


async def _extract_feed_posts(browser) -> List[Dict[str, Any]]:
    """Extract posts from current feed view."""
    posts = []
    
    # Try multiple selectors for post containers (desktop and mobile-lite)
    # Note: For mobile-lite, we select the parent .feed-item li which contains both
    # the article and the social counts section
    post_selectors = [
        ("[data-testid='mainFeed'] [role='listitem']", "mobile"),
        ("[role='list'][data-testid='mainFeed'] [role='listitem']", "mobile"),
        (".feed-shared-update-v2", "desktop"),           # Desktop
        ("li.feed-item", "mobile"),                      # Mobile-lite - select parent li
        ("article[data-activity-urn]", "mobile"),        # Mobile-lite fallback
        ("[data-testid='mainFeed'] > div", "desktop"),   # SDUI feed children
        ("[role='list'][data-testid='mainFeed'] > div", "desktop"),
        (".main-feed-activity-card", "mobile"),          # New feed cards
        ("[data-test-id='main-feed-activity-card']", "mobile"),
        ("div[data-id='main-feed-card']", "mobile"),
        ("div[data-urn^='urn:li:activity']", "desktop"),
        (".occludable-update", "desktop"),               # Desktop variant
    ]
    
    try:
        post_elements = []
        layout_type = "desktop"
        
        for selector, layout in post_selectors:
            elements = await browser.query_selector_all(selector)
            if elements:
                logger.info(f"Found {len(elements)} posts with selector: {selector} (layout: {layout})")
                post_elements = elements
                layout_type = layout
                break
        
        for element in post_elements:
            try:
                if layout_type == "mobile":
                    post_data = await _parse_mobile_post_element(browser, element)
                    if not post_data:
                        post_data = await _parse_post_element(browser, element)
                else:
                    post_data = await _parse_post_element(browser, element)
                    if not post_data:
                        post_data = await _parse_mobile_post_element(browser, element)
                normalized_post = _normalize_feed_post(post_data)
                if _is_meaningful_post(normalized_post):
                    posts.append(normalized_post)
            except Exception as e:
                logger.debug(f"Failed to parse post: {e}")
                continue
        
    except Exception as e:
        logger.error(f"Failed to extract posts: {e}")
    
    return posts


async def _extract_search_posts(browser) -> List[Dict[str, Any]]:
    """Extract posts from desktop search results page."""
    posts = []
    
    # Desktop search results selectors
    post_selectors = [
        ".feed-shared-update-v2",                    # Standard feed posts
        ".reusable-search__result-container",        # Search result containers
        "div[data-urn^='urn:li:activity']",          # Activity URN containers
    ]
    
    try:
        post_elements = []
        
        for selector in post_selectors:
            elements = await browser.query_selector_all(selector)
            if elements:
                logger.info(f"[_extract_search_posts] Found {len(elements)} posts with selector: {selector}")
                post_elements = elements
                break
        
        for element in post_elements:
            try:
                post_data = await _parse_search_post_element(browser, element)
                if post_data:
                    posts.append(post_data)
            except Exception as e:
                logger.debug(f"Failed to parse search post: {e}")
                continue
        
    except Exception as e:
        logger.error(f"Failed to extract search posts: {e}")
    
    return posts


async def _parse_search_post_element(browser, element) -> Optional[Dict[str, Any]]:
    """Parse a single post element from desktop search results using JavaScript."""
    try:
        post_data = await element.evaluate(r"""
            (el) => {
                const data = {
                    author_name: null,
                    author_headline: null,
                    author_url: null,
                    content: null,
                    likes: null,
                    comments: null,
                    timestamp: null,
                    url: null
                };
                
                // Author name - try multiple selectors
                const authorSelectors = [
                    '.update-components-actor__name span[aria-hidden="true"]',
                    '.update-components-actor__name',
                    '.feed-shared-actor__name',
                    '.entity-result__title-text a',
                    'a.app-aware-link span[aria-hidden="true"]'
                ];
                for (const sel of authorSelectors) {
                    const el2 = el.querySelector(sel);
                    if (el2 && el2.textContent.trim()) {
                        data.author_name = el2.textContent.trim();
                        break;
                    }
                }
                
                // Author headline
                const headlineSelectors = [
                    '.update-components-actor__description',
                    '.feed-shared-actor__description',
                    '.entity-result__primary-subtitle'
                ];
                for (const sel of headlineSelectors) {
                    const el2 = el.querySelector(sel);
                    if (el2 && el2.textContent.trim()) {
                        data.author_headline = el2.textContent.trim();
                        break;
                    }
                }
                
                // Author URL
                const authorLinkSelectors = [
                    '.update-components-actor__container-link',
                    '.feed-shared-actor__container-link',
                    'a.app-aware-link[href*="/in/"]'
                ];
                for (const sel of authorLinkSelectors) {
                    const el2 = el.querySelector(sel);
                    if (el2) {
                        data.author_url = el2.getAttribute('href');
                        break;
                    }
                }
                
                // Post content
                const contentSelectors = [
                    '.feed-shared-update-v2__description',
                    '.feed-shared-text',
                    '.update-components-text',
                    '.break-words'
                ];
                for (const sel of contentSelectors) {
                    const el2 = el.querySelector(sel);
                    if (el2 && el2.textContent.trim()) {
                        data.content = el2.textContent.trim();
                        break;
                    }
                }
                
                // Likes/reactions
                const likesSelectors = [
                    '.social-details-social-counts__reactions-count',
                    '.social-details-social-counts__count-value'
                ];
                for (const sel of likesSelectors) {
                    const el2 = el.querySelector(sel);
                    if (el2 && el2.textContent.trim()) {
                        data.likes = el2.textContent.trim();
                        break;
                    }
                }
                
                // Comments count
                const commentsEl = el.querySelector('.social-details-social-counts__comments');
                if (commentsEl) {
                    data.comments = commentsEl.textContent.trim();
                }
                
                // Timestamp
                const timeSelectors = [
                    '.update-components-actor__sub-description',
                    'time',
                    '.feed-shared-actor__sub-description'
                ];
                for (const sel of timeSelectors) {
                    const el2 = el.querySelector(sel);
                    if (el2 && el2.textContent.trim()) {
                        data.timestamp = el2.textContent.trim();
                        break;
                    }
                }
                
                // Post URL - look for activity link
                const urlSelectors = [
                    'a[href*="/feed/update/"]',
                    'a[data-urn]',
                    '.feed-shared-control-menu__trigger'
                ];
                for (const sel of urlSelectors) {
                    const el2 = el.querySelector(sel);
                    if (el2) {
                        const href = el2.getAttribute('href');
                        if (href && href.includes('/feed/update/')) {
                            data.url = href;
                            break;
                        }
                    }
                }
                
                // Try to get URL from data-urn attribute
                if (!data.url) {
                    const urn = el.getAttribute('data-urn');
                    if (urn && urn.includes('activity')) {
                        const activityId = urn.split(':').pop();
                        data.url = '/feed/update/urn:li:activity:' + activityId;
                    }
                }
                
                return data;
            }
        """)
        
        if not post_data:
            return None
        
        # Parse engagement counts
        likes = _parse_count(post_data.get("likes")) if post_data.get("likes") else None
        comments = _parse_count(post_data.get("comments")) if post_data.get("comments") else None
        
        return {
            "author": {
                "name": post_data.get("author_name"),
                "headline": post_data.get("author_headline"),
                "url": post_data.get("author_url"),
            },
            "content": post_data.get("content"),
            "engagement": {
                "likes": likes,
                "comments": comments,
            },
            "url": post_data.get("url"),
            "timestamp": post_data.get("timestamp"),
        }
        
    except Exception as e:
        logger.debug(f"Failed to parse search post element: {e}")
        return None


async def _parse_post_element(browser, element) -> Optional[Dict[str, Any]]:
    """Parse a single post element."""
    try:
        def _normalize_post_href(href: Optional[str]) -> Optional[str]:
            if not href:
                return None
            value = href.strip()
            if not value:
                return None
            if value.startswith("http://") or value.startswith("https://"):
                return value
            if value.startswith("/"):
                return f"https://www.linkedin.com{value}"
            return value

        def _extract_activity_urn(value: Optional[str]) -> Optional[str]:
            if not value:
                return None
            text = str(value)

            direct = re.search(r"urn:li:(activity|ugcPost|share):(\d{8,})", text, re.IGNORECASE)
            if direct:
                return f"urn:li:{direct.group(1)}:{direct.group(2)}"

            encoded = re.search(r"urn%3Ali%3A(activity|ugcPost|share)%3A(\d{8,})", text, re.IGNORECASE)
            if encoded:
                return f"urn:li:{encoded.group(1)}:{encoded.group(2)}"

            update_urn = re.search(
                r"updateUrn=urn%253Ali%253A(activity|ugcPost|share)%253A(\d{8,})",
                text,
                re.IGNORECASE,
            ) or re.search(
                r"updateUrn=urn%3Ali%3A(activity|ugcPost|share)%3A(\d{8,})",
                text,
                re.IGNORECASE,
            )
            if update_urn:
                return f"urn:li:{update_urn.group(1)}:{update_urn.group(2)}"

            return None

        # Extract author info
        author_name = None
        author_headline = None
        author_url = None
        
        author_elem = await element.query_selector(".update-components-actor__name")
        if author_elem:
            author_name = await author_elem.inner_text()
            author_name = author_name.strip() if author_name else None
        
        headline_elem = await element.query_selector(".update-components-actor__description")
        if headline_elem:
            author_headline = await headline_elem.inner_text()
            author_headline = author_headline.strip() if author_headline else None
        
        author_link = await element.query_selector(".update-components-actor__container-link")
        if author_link:
            author_url = await author_link.get_attribute("href")
        
        # Extract post content
        content = None
        content_elem = await element.query_selector(".feed-shared-update-v2__description")
        if content_elem:
            content = await content_elem.inner_text()
            content = content.strip() if content else None
        
        # Extract engagement metrics
        likes = None
        comments = None
        
        reactions_elem = await element.query_selector(".social-details-social-counts__reactions-count")
        if reactions_elem:
            likes_text = await reactions_elem.inner_text()
            likes = _parse_count(likes_text)
        
        comments_elem = await element.query_selector(".social-details-social-counts__comments")
        if comments_elem:
            comments_text = await comments_elem.inner_text()
            comments = _parse_count(comments_text)
        
        # Extract post URL
        post_url = None
        url_selectors = [
            "a[href*='/feed/update/']",
            "a[href*='updateUrn=']",
            "a[href*='urn%3Ali%3Aactivity%3A']",
            "a[href*='urn%3Ali%3AugcPost%3A']",
            "a[href*='/posts/']",
            "a[data-urn]",
        ]
        for selector in url_selectors:
            candidate = await element.query_selector(selector)
            if not candidate:
                continue
            candidate_href = await candidate.get_attribute("href")
            normalized_href = _normalize_post_href(candidate_href)
            if not normalized_href:
                continue

            post_url = normalized_href
            if "/feed/update/" in normalized_href or "/posts/" in normalized_href:
                break

            urn = _extract_activity_urn(normalized_href)
            if urn:
                post_url = f"https://www.linkedin.com/feed/update/{urn}"
                break

        if not post_url:
            for attr in ["data-urn", "data-activity-urn", "data-id"]:
                attr_value = await element.get_attribute(attr)
                urn = _extract_activity_urn(attr_value)
                if urn:
                    post_url = f"https://www.linkedin.com/feed/update/{urn}"
                    break

        if not post_url:
            urn_node = await element.query_selector("[data-urn], [data-activity-urn]")
            if urn_node:
                for attr in ["data-urn", "data-activity-urn"]:
                    attr_value = await urn_node.get_attribute(attr)
                    urn = _extract_activity_urn(attr_value)
                    if urn:
                        post_url = f"https://www.linkedin.com/feed/update/{urn}"
                        break
                if not post_url:
                    node_href = _normalize_post_href(await urn_node.get_attribute("href"))
                    urn = _extract_activity_urn(node_href)
                    if urn:
                        post_url = f"https://www.linkedin.com/feed/update/{urn}"
        
        # Extract timestamp
        timestamp = None
        time_elem = await element.query_selector(".update-components-actor__sub-description")
        if time_elem:
            timestamp = await time_elem.inner_text()
            timestamp = timestamp.strip() if timestamp else None
        
        return {
            "author": {
                "name": author_name,
                "headline": author_headline,
                "url": author_url,
            },
            "content": content,
            "engagement": {
                "likes": likes,
                "comments": comments,
            },
            "url": post_url,
            "timestamp": timestamp,
        }
        
    except Exception as e:
        logger.debug(f"Failed to parse post element: {e}")
        return None


async def _parse_mobile_post_element(browser, element) -> Optional[Dict[str, Any]]:
    """Parse a single post element from mobile-lite layout using JavaScript."""
    try:
        # Use JavaScript to extract all data at once for better reliability
        post_data = await element.evaluate(r"""
            (el) => {
                const cleanText = (value) => (value || '').replace(/\s+/g, ' ').trim();
                const normalizeHref = (href) => {
                    if (!href) return null;
                    if (href.startsWith('http://') || href.startsWith('https://')) return href;
                    if (href.startsWith('/')) return `https://www.linkedin.com${href}`;
                    return href;
                };
                const isFeedHomeUrl = (href) => {
                    if (!href) return false;
                    return /^https?:\/\/www\.linkedin\.com\/feed\/?(?:[?#].*)?$/i.test(href);
                };
                const isPostLikeUrl = (href) => {
                    if (!href) return false;
                    const value = href.toLowerCase();
                    return (
                        value.includes('/feed/update/')
                        || value.includes('/posts/')
                        || value.includes('/recent-activity/')
                        || value.includes('updateurn=')
                        || value.includes('urn%3ali%3aactivity%3a')
                        || value.includes('urn%3ali%3augcpost%3a')
                        || value.includes('urn%3ali%3ashare%3a')
                    );
                };
                const extractActivityUrn = (value) => {
                    if (!value) return null;
                    const text = String(value);

                    const direct = text.match(/urn:li:activity:(\d{8,})/i);
                    if (direct) return `urn:li:activity:${direct[1]}`;

                    const directUgc = text.match(/urn:li:ugcPost:(\d{8,})/i);
                    if (directUgc) return `urn:li:ugcPost:${directUgc[1]}`;

                    const directShare = text.match(/urn:li:share:(\d{8,})/i);
                    if (directShare) return `urn:li:share:${directShare[1]}`;

                    const encoded = text.match(/urn%3Ali%3Aactivity%3A(\d{8,})/i);
                    if (encoded) return `urn:li:activity:${encoded[1]}`;

                    const encodedUgc = text.match(/urn%3Ali%3AugcPost%3A(\d{8,})/i);
                    if (encodedUgc) return `urn:li:ugcPost:${encodedUgc[1]}`;

                    const encodedShare = text.match(/urn%3Ali%3Ashare%3A(\d{8,})/i);
                    if (encodedShare) return `urn:li:share:${encodedShare[1]}`;

                    const updateUrnActivity = text.match(/updateUrn=urn%253Ali%253Aactivity%253A(\d{8,})/i)
                        || text.match(/updateUrn=urn%3Ali%3Aactivity%3A(\d{8,})/i);
                    if (updateUrnActivity) return `urn:li:activity:${updateUrnActivity[1]}`;

                    const updateUrnUgc = text.match(/updateUrn=urn%253Ali%253AugcPost%253A(\d{8,})/i)
                        || text.match(/updateUrn=urn%3Ali%3AugcPost%3A(\d{8,})/i);
                    if (updateUrnUgc) return `urn:li:ugcPost:${updateUrnUgc[1]}`;

                    const loose = text.match(/(?:activity[:\/-])(\d{8,})/i);
                    if (loose) return `urn:li:activity:${loose[1]}`;

                    return null;
                };

                const data = {
                    activity_urn: el.getAttribute('data-activity-urn'),
                    featured_urn: el.getAttribute('data-featured-activity-urn'),
                    author_name: null,
                    author_headline: null,
                    author_url: null,
                    profile_url: null,
                    company_url: null,
                    content: null,
                    likes: null,
                    comments: null,
                    timestamp: null,
                    is_promoted: false,
                };

                const hasPromotedBadge = Array.from(el.querySelectorAll('p, span')).some((node) => {
                    const text = cleanText(node.textContent).toLowerCase();
                    return text === 'promoted';
                });
                const hasPromotedLink = !!el.querySelector('a[href*="li_fat_id="]');
                if (hasPromotedBadge || hasPromotedLink) {
                    data.is_promoted = true;
                }
                
                // Author - look for the entity lockup or direct link
                const actorLink = el.querySelector('a[data-tracking-control-name*="feed-actor-name"]');
                if (actorLink) {
                    data.author_name = cleanText(actorLink.textContent);
                    data.author_url = actorLink.getAttribute('href');
                }
                
                // Fallback: try entity lockup structure
                if (!data.author_name) {
                    const entityLockup = el.querySelector('[data-test-id="main-feed-activity-card__entity-lockup"]');
                    if (entityLockup) {
                        const nameLink = entityLockup.querySelector('a[data-tracking-control-name*="feed-actor-name"]');
                        if (nameLink) {
                            data.author_name = cleanText(nameLink.textContent);
                            if (!data.author_url) {
                                data.author_url = nameLink.getAttribute('href');
                            }
                        }
                    }
                }

                // SDUI fallback: score potential actor links in the card header area
                if (!data.author_name) {
                    const blockedTerms = [
                        'follow', 'like', 'comment', 'repost', 'send', 'reply',
                        'load more', 'start a post', 'new posts', 'sort by'
                    ];
                    const candidates = Array.from(el.querySelectorAll('a[href]'));
                    let best = null;
                    for (const node of candidates) {
                        const href = node.getAttribute('href') || '';
                        const text = cleanText(node.textContent);
                        if (!text || text.length < 2 || text.length > 100) continue;
                        const lower = text.toLowerCase();
                        if (blockedTerms.some((term) => lower === term || lower.includes(term))) continue;

                        let score = 0;
                        if (href.includes('/in/')) score += 3;
                        if (href.includes('/company/')) score += 3;
                        if (href.includes('/posts/')) score += 1;
                        if (node.closest('[aria-label*="profile" i], [aria-label*="company" i]')) score += 2;
                        if (node.closest('[componentkey]')) score += 1;
                        if (/^[A-Z][^\n]{1,80}$/.test(text)) score += 1;

                        if (!best || score > best.score) {
                            best = { text, href, score };
                        }
                    }
                    if (best && best.score >= 3) {
                        data.author_name = best.text;
                        data.author_url = best.href;
                    }
                }
                
                // Author headline - look for p tag with truncate class
                const headlineEl = el.querySelector('[data-test-id="main-feed-activity-card__entity-lockup"] p.truncate');
                if (headlineEl) {
                    data.author_headline = headlineEl.textContent.trim();
                }
                
                // Timestamp - look for time element
                const timeEl = el.querySelector('time');
                if (timeEl) {
                    data.timestamp = cleanText(timeEl.textContent);
                }
                
                // Fallback: Author from header link or any profile/company link
                if (!data.author_name) {
                    const fallbackSelectors = [
                        '.main-feed-activity-card__header a.link-styled',
                        'a[data-tracking-control-name*="actor"]',
                        'a[href*="/in/"]',
                        'a[href*="/company/"]'
                    ];
                    for (const sel of fallbackSelectors) {
                        const link = el.querySelector(sel);
                        if (link) {
                            const text = cleanText(link.textContent);
                            if (text && text.length > 1 && !text.includes('http')) {
                                data.author_name = text;
                                if (!data.author_url) {
                                    data.author_url = link.getAttribute('href');
                                }
                                break;
                            }
                        }
                    }
                }
                
                // Extract follower count for companies
                if (!data.author_headline && data.author_url && data.author_url.includes('/company/')) {
                    const ddElements = el.querySelectorAll('dd, p');
                    for (const dd of ddElements) {
                        const text = cleanText(dd.textContent);
                        if (text.includes('follower')) {
                            data.author_headline = text;
                            break;
                        }
                    }
                }

                // Headline fallback near actor area (avoid post body / CTA text)
                if (!data.author_headline) {
                    const headlineCandidates = Array.from(el.querySelectorAll('p, span')).map((node) => cleanText(node.textContent));
                    for (const text of headlineCandidates) {
                        if (!text || text.length < 8 || text.length > 180) continue;
                        const lower = text.toLowerCase();
                        if (lower.includes('followers') || lower.includes('connections')) {
                            data.author_headline = text;
                            break;
                        }
                        if (/\b(ceo|founder|manager|engineer|director|consultant|specialist)\b/i.test(text)) {
                            data.author_headline = text;
                            break;
                        }
                    }
                }
                
                // Content - look for the main text content
                const contentSelectors = [
                    '[data-testid="expandable-text-box"]',
                    '.attributed-text-segment-list__content',
                    '.main-feed-activity-card__content .break-words',
                    '[data-id="main-feed-card"] .break-words.text-color-text',
                    '.feed-shared-text',
                    '.break-words.text-color-text'
                ];
                for (const sel of contentSelectors) {
                    const contentEl = el.querySelector(sel);
                    if (contentEl) {
                        const cloned = contentEl.cloneNode(true);
                        cloned.querySelectorAll('[data-testid="expandable-text-button"], button').forEach((btn) => btn.remove());
                        data.content = cleanText(cloned.textContent || contentEl.textContent);
                        if (data.content) break;
                    }
                }

                if (data.content && data.content.toLowerCase().includes('start a post')) {
                    data.content = null;
                }
                
                // Engagement counts - try multiple approaches
                // 1. Look for social-details-social-counts section
                const socialDetails = el.querySelector('.social-details-social-counts');
                if (socialDetails) {
                    const allText = socialDetails.textContent;
                    // Extract numbers from text like "42 reactions" or "5 comments"
                    const reactionMatch = allText.match(/(\d+)\s*(?:reaction|like)/i);
                    if (reactionMatch) {
                        data.likes = parseInt(reactionMatch[1], 10);
                    }
                    const commentMatch = allText.match(/(\d+)\s*comment/i);
                    if (commentMatch) {
                        data.comments = parseInt(commentMatch[1], 10);
                    }
                }
                
                // Engagement - social counts section (try multiple selectors)
                const socialCountsSelectors = [
                    '[data-id="social-counts"]',
                    'section[data-id="social-counts"]',
                    '.social-counts',
                    '[data-feed-control="social_counts"]'
                ];
                
                let socialCounts = null;
                for (const sel of socialCountsSelectors) {
                    socialCounts = el.querySelector(sel);
                    if (socialCounts) break;
                }
                
                // Also try to find reactions/comments directly in the element
                if (!socialCounts) {
                    // Look for reactions button anywhere in the post
                    const reactionsBtn = el.querySelector('button[data-feed-action="showReactions"]');
                    if (reactionsBtn) {
                        const text = reactionsBtn.textContent.trim();
                        const match = text.match(/([\d,\.]+)\s*([kKmM])?/);
                        if (match) {
                            let num = parseFloat(match[1].replace(/,/g, ''));
                            if (match[2] && match[2].toLowerCase() === 'k') num *= 1000;
                            if (match[2] && match[2].toLowerCase() === 'm') num *= 1000000;
                            data.likes = Math.round(num);
                        }
                    }
                    
                    // Look for comments link anywhere in the post
                    const commentsLink = el.querySelector('a[data-feed-action="showComments"], a[href*="comments"]');
                    if (commentsLink) {
                        const text = commentsLink.textContent.trim();
                        const match = text.match(/([\d,]+)/);
                        if (match) {
                            data.comments = parseInt(match[1].replace(/,/g, ''), 10);
                        }
                    }
                }
                
                if (socialCounts) {
                    // Likes/reactions - look for button with showReactions action
                    const reactionsBtn = socialCounts.querySelector('button[data-feed-action="showReactions"]');
                    if (reactionsBtn) {
                        const text = reactionsBtn.textContent.trim();
                        const match = text.match(/([\d,\.]+)\s*([kKmM])?/);
                        if (match) {
                            let num = parseFloat(match[1].replace(/,/g, ''));
                            if (match[2] && match[2].toLowerCase() === 'k') num *= 1000;
                            if (match[2] && match[2].toLowerCase() === 'm') num *= 1000000;
                            data.likes = Math.round(num);
                        }
                    }
                    
                    // Comments - look for link with showComments action or href containing comment
                    const commentsLink = socialCounts.querySelector('a[data-feed-action="showComments"], a[href*="comment"]');
                    if (commentsLink) {
                        const text = commentsLink.textContent.trim();
                        const match = text.match(/([\d,]+)/);
                        if (match) {
                            data.comments = parseInt(match[1].replace(/,/g, ''), 10);
                        }
                    }
                }
                
                // Fallback: try to find engagement from social action bar
                if (data.likes === null) {
                    const likeText = el.querySelector('.social-details-social-counts__reactions-count, .social-details-social-counts__item:first-child');
                    if (likeText) {
                        const text = likeText.textContent.trim();
                        const match = text.match(/([\d,]+)/);
                        if (match) {
                            data.likes = parseInt(match[1].replace(/,/g, ''), 10);
                        }
                    }
                }
                
                if (data.comments === null) {
                    const commentText = el.querySelector('.social-details-social-counts__comments, .social-details-social-counts__item:last-child');
                    if (commentText) {
                        const text = commentText.textContent.trim();
                        const match = text.match(/([\d,]+)/);
                        if (match) {
                            data.comments = parseInt(match[1].replace(/,/g, ''), 10);
                        }
                    }
                }

                // Broad fallback for SDUI: parse counts/timestamp from post text
                const parseCompactCount = (raw) => {
                    if (!raw) return null;
                    const match = raw.match(/([\d,.]+)\s*([kKmM])?/);
                    if (!match) return null;
                    let num = parseFloat((match[1] || '').replace(/,/g, ''));
                    if (Number.isNaN(num)) return null;
                    const suffix = (match[2] || '').toLowerCase();
                    if (suffix === 'k') num *= 1000;
                    if (suffix === 'm') num *= 1000000;
                    return Math.round(num);
                };

                const allText = (el.innerText || '').replace(/\s+/g, ' ').trim();
                if (data.likes === null) {
                    const likesMatch = allText.match(/([\d,.]+\s*[kKmM]?)\s*(?:reactions?|likes?)/i);
                    if (likesMatch) data.likes = parseCompactCount(likesMatch[1]);
                }
                if (data.comments === null) {
                    const commentsMatch = allText.match(/([\d,.]+\s*[kKmM]?)\s*comments?/i);
                    if (commentsMatch) data.comments = parseCompactCount(commentsMatch[1]);
                }

                if (!data.timestamp) {
                    const timeMatch = allText.match(/\b(\d+\s*(?:s|m|h|d|w|mo|yr|y))\b/i);
                    if (timeMatch) data.timestamp = timeMatch[1];
                }

                // URL fallback: direct feed/update links, then URN in markup
                const updateLink = el.querySelector('a[href*="/feed/update/"]');
                if (updateLink) {
                    data.url = normalizeHref(updateLink.getAttribute('href'));
                }

                if (!data.url) {
                    const encodedUpdateLink = el.querySelector('a[href*="urn%3Ali%3Aactivity%3A"]');
                    if (encodedUpdateLink) {
                        data.url = normalizeHref(encodedUpdateLink.getAttribute('href'));
                    }
                }

                if (!data.activity_urn && data.url) {
                    data.activity_urn = extractActivityUrn(data.url);
                }

                if (!data.activity_urn) {
                    const nodes = [el, ...Array.from(el.querySelectorAll('*')).slice(0, 220)];
                    for (const node of nodes) {
                        const names = node.getAttributeNames ? node.getAttributeNames() : [];
                        for (const name of names) {
                            const value = node.getAttribute(name);
                            const urn = extractActivityUrn(value);
                            if (urn) {
                                data.activity_urn = urn;
                                break;
                            }
                        }
                        if (data.activity_urn) break;
                    }
                }

                if (!data.activity_urn) {
                    const html = el.innerHTML || '';
                    data.activity_urn = extractActivityUrn(html);
                }

                if (!data.url && data.activity_urn) {
                    data.url = `https://www.linkedin.com/feed/update/${data.activity_urn}`;
                }

                if (!data.url) {
                    const candidates = Array.from(el.querySelectorAll('a[href]'));
                    let bestUrl = null;
                    let bestScore = -1;

                    for (const node of candidates) {
                        const href = normalizeHref(node.getAttribute('href'));
                        if (!href) continue;
                        if (!href.includes('linkedin.com')) continue;
                        if (isFeedHomeUrl(href)) continue;
                        if (href.includes('/safety/go?')) continue;
                        if (!isPostLikeUrl(href)) continue;

                        let score = 0;
                        if (href.includes('/feed/update/')) score += 10;
                        if (href.includes('/posts/')) score += 8;
                        if (href.includes('/recent-activity/')) score += 6;
                        if (href.includes('/search/')) score -= 4;

                        if (node.closest('[data-testid="expandable-text-box"]')) score -= 6;

                        if (score > bestScore) {
                            bestScore = score;
                            bestUrl = href;
                        }
                    }

                    if (bestUrl && bestScore > 0) {
                        data.url = bestUrl;
                    }
                }

                if (data.author_url) {
                    data.author_url = normalizeHref(data.author_url);
                }

                if (!data.profile_url || !data.company_url) {
                    const profileCompanyLinks = Array.from(el.querySelectorAll('a[href]'));
                    for (const link of profileCompanyLinks) {
                        const href = normalizeHref(link.getAttribute('href'));
                        if (!href) continue;
                        if (!href.includes('linkedin.com')) continue;
                        if (!data.profile_url && href.includes('/in/')) {
                            data.profile_url = href;
                        }
                        if (!data.company_url && href.includes('/company/')) {
                            data.company_url = href;
                        }
                        if (data.profile_url && data.company_url) break;
                    }
                }

                if (!data.profile_url && data.author_url && data.author_url.includes('/in/')) {
                    data.profile_url = data.author_url;
                }
                if (!data.company_url && data.author_url && data.author_url.includes('/company/')) {
                    data.company_url = data.author_url;
                }
                
                return data;
            }
        """)
        
        # Build post URL from URN
        activity_urn = post_data.get("activity_urn")
        featured_urn = post_data.get("featured_urn")
        if activity_urn and not post_data.get("url"):
            post_data["url"] = f"https://www.linkedin.com/feed/update/{activity_urn}"
        elif featured_urn and not post_data.get("url"):
            post_data["url"] = f"https://www.linkedin.com/feed/update/{featured_urn}"
        
        # Return flat structure
        return post_data
        
    except Exception as e:
        logger.debug(f"Failed to parse mobile post element: {e}")
        return None


def _parse_count(text: str) -> Optional[int]:
    """Parse engagement count from text like '1,234', '1.2K', or '42 comments'."""
    if not text:
        return None
    
    text = text.strip().lower()
    
    # Skip if text is too long (likely not a count)
    if len(text) > 50:
        return None
    
    # Skip if it looks like a URL or tracking ID
    if 'http' in text or 'urn:' in text or 'activity' in text:
        return None
    
    # Remove commas
    text = text.replace(",", "")
    
    # Handle K/M suffixes
    multiplier = 1
    if "k" in text:
        multiplier = 1000
        text = text.replace("k", "")
    elif "m" in text:
        multiplier = 1000000
        text = text.replace("m", "")
    
    # Extract number - prefer numbers at the start of the string
    match = re.match(r"^\s*([\d.]+)", text)
    if not match:
        # Try finding a standalone number
        match = re.search(r"\b([\d.]+)\b", text)
    
    if match:
        try:
            count = int(float(match.group(1)) * multiplier)
            # Sanity check - engagement counts rarely exceed 1M for regular posts
            if count > 10000000:
                return None
            return count
        except ValueError:
            pass
    
    return None


async def get_post(
    profile_id: str,
    post_url: str,
) -> dict:
    """Get a LinkedIn post by URL.
    
    Args:
        profile_id: Profile UUID
        post_url: Full LinkedIn post URL or path (e.g., /feed/update/urn:li:activity:...)
    
    Returns:
        Dict with post details
    """
    logger.info(f"[get_post] Getting post: {post_url}")
    
    try:
        # Verify profile exists
        with get_db() as db:
            profile_repo = ProfileRepository(db)
            profile = profile_repo.get_by_uuid(profile_id)
            if not profile:
                return {
                    "status": "error",
                    "message": f"Profile {profile_id} not found",
                }
        
        # Get or create session
        session_manager = get_session_manager()
        session = await session_manager.create_session(profile_id)
        browser = session.browser
        human = HumanBehavior()
        
        # Normalize URL
        if not post_url.startswith("http"):
            post_url = f"https://www.linkedin.com{post_url}"
        
        # Navigate to post (with like-style recovery)
        try:
            await browser.navigate(post_url)
        except Exception as nav_error:
            nav_error_text = str(nav_error)
            logger.warning(f"[comment_post] Primary navigation failed: {nav_error_text}")

            try:
                await browser.navigate(post_url, wait_until="commit", timeout=20000)
                logger.info("[comment_post] Recovery navigation succeeded with wait_until=commit")
            except Exception as retry_error:
                retry_error_text = str(retry_error)
                logger.warning(f"[comment_post] Recovery navigation failed: {retry_error_text}")

                current_url_after_failure = await browser.get_current_url()
                has_post_ui = await browser.evaluate("""
                    () => {
                        return !!(
                            document.querySelector('article[data-activity-urn]') ||
                            document.querySelector('.feed-shared-update-v2') ||
                            document.querySelector('[role="main"]')
                        );
                    }
                """)
                if has_post_ui:
                    logger.info(
                        "[comment_post] Continuing despite navigation timeout; post UI is present "
                        f"(current_url={current_url_after_failure})"
                    )
                else:
                    raise nav_error

        await human.page_load_delay()
        
        # Check if logged in
        current_url = await browser.get_current_url()
        if "login" in current_url or "authwall" in current_url:
            return {
                "status": "error",
                "message": "Not logged in - please login first",
            }

        auth_wall_reason = await _detect_auth_wall(browser)
        if auth_wall_reason:
            logger.warning(f"[get_post] Auth wall detected before parsing post: {auth_wall_reason}")
            return {
                "status": "error",
                "message": f"Not logged in / auth wall detected ({auth_wall_reason})",
            }
        
        # Wait for post content
        post_selectors = [
            "article[data-activity-urn]",
            "li.feed-item",
            ".main-feed-activity-card",
        ]
        
        post_found = False
        for selector in post_selectors:
            if await browser.wait_for_selector(selector, timeout=5000):
                post_found = True
                logger.info(f"[get_post] Found post with selector: {selector}")
                break
        
        if not post_found:
            return {
                "status": "error",
                "message": "Post not found or not accessible",
            }
        
        # Extract post data
        post_element = await browser.query_selector(post_selectors[0])
        if not post_element:
            post_element = await browser.query_selector(post_selectors[1])
        
        if post_element:
            # Wait for page to settle and scroll to load all elements
            await human.delay(2000, 3000)
            
            # Scroll to bottom to load comments and engagement data
            await browser.safe_scroll_to_bottom()
            await human.delay(1000, 1500)
            
            # Scroll article into view
            await browser.safe_evaluate("""
                const article = document.querySelector('article[data-activity-urn]');
                if (article) {
                    article.scrollIntoView({ behavior: 'auto', block: 'center' });
                }
            """)
            await human.delay(1000, 1500)
            
            # Now parse the post data after scrolling
            post_data = await _parse_mobile_post_element(browser, post_element)
            logger.info(f"[get_post] Parsed post data: author_name={post_data.get('author_name') if post_data else None}, likes={post_data.get('likes') if post_data else None}, comments={post_data.get('comments') if post_data else None}")
            
            # Debug: Check what engagement elements exist
            engagement_debug = await browser.evaluate("""
                () => {
                    const socialDetails = document.querySelector('.social-details-social-counts');
                    const socialCounts = document.querySelector('[data-id="social-counts"]');
                    return {
                        hasSocialDetails: !!socialDetails,
                        socialDetailsText: socialDetails ? socialDetails.textContent.trim() : null,
                        hasSocialCounts: !!socialCounts,
                        socialCountsText: socialCounts ? socialCounts.textContent.trim() : null
                    };
                }
            """)
            logger.info(f"[get_post] Engagement debug: {engagement_debug}")
            
            if post_data:
                post_data["url"] = post_url
                
                # Check if user has liked the post
                is_liked = False
                try:
                    # Check for like button - it has data-feed-action-type="unlikeUpdate" when liked
                    like_button = await browser.query_selector('button[data-feed-control="like_toggle"]')
                    if like_button:
                        # Check data-feed-action-type attribute
                        action_type = await like_button.get_attribute("data-feed-action-type")
                        is_liked = action_type == "unlikeUpdate"
                        logger.info(f"[get_post] Like button action type: {action_type}, is_liked: {is_liked}")
                    
                    # Also check for selected reaction button with aria-pressed="true"
                    if not is_liked:
                        selected_reaction = await browser.query_selector('button[aria-pressed="true"][data-reaction-type="LIKE"]')
                        if selected_reaction:
                            is_liked = True
                            logger.info(f"[get_post] Found selected LIKE reaction button")
                except Exception as e:
                    logger.debug(f"[get_post] Could not check like status: {e}")
                
                post_data["is_liked"] = is_liked
                
                # Check if user has commented on the post
                has_commented = False
                user_comments = []
                
                try:
                    # Scroll to comments section to ensure they're loaded
                    await browser.evaluate("""
                        const commentsSection = document.querySelector('.comments-list, #comment-box-wrapper');
                        if (commentsSection) {
                            commentsSection.scrollIntoView({ behavior: 'auto', block: 'center' });
                        }
                    """)
                    await human.delay(1000, 1500)
                    
                    # Get current user's profile image for matching
                    user_image_src = await browser.evaluate("""
                        const img = document.querySelector('.comment-box__image');
                        return img ? img.src : null;
                    """)
                    logger.info(f"[get_post] User profile image src: {user_image_src[:50] if user_image_src else 'None'}...")
                    
                    # Find all comments
                    comments_exist = await browser.query_selector('.comments-list')
                    
                    if comments_exist:
                        comment_items = await browser.query_selector_all('.comment')
                        logger.info(f"[get_post] Found {len(comment_items)} total comments")
                        
                        for idx, comment_item in enumerate(comment_items):
                            try:
                                # Check if this comment is from the current user
                                is_user_comment = await browser.evaluate("""
                                    (element, userImageSrc) => {
                                        const img = element.querySelector('img');
                                        if (img && userImageSrc && img.src === userImageSrc) {
                                            return true;
                                        }
                                        // Also check for edit/delete buttons (only visible on own comments)
                                        const hasEditButton = element.querySelector('[data-feed-action="edit-comment"]');
                                        const hasDeleteButton = element.querySelector('[data-feed-action="delete-comment"]');
                                        return hasEditButton || hasDeleteButton;
                                    }
                                """, comment_item, user_image_src)
                                
                                if is_user_comment:
                                    # Extract comment text
                                    comment_text = await browser.evaluate("""
                                        (element) => {
                                            const textEl = element.querySelector('.comment__text');
                                            return textEl ? textEl.textContent.trim() : '';
                                        }
                                    """, comment_item)
                                    
                                    user_comments.append({
                                        "text": comment_text,
                                        "index": idx,
                                    })
                                    logger.info(f"[get_post] Found user comment: {comment_text[:50]}...")
                            
                            except Exception as e:
                                logger.debug(f"[get_post] Error processing comment {idx}: {e}")
                                continue
                        
                        has_commented = len(user_comments) > 0
                    else:
                        logger.info(f"[get_post] No comments list found on page")
                
                except Exception as e:
                    logger.error(f"[get_post] Could not check comment status: {e}")
                
                post_data["has_commented"] = has_commented
                post_data["user_comments"] = user_comments
                post_data["user_comment_count"] = len(user_comments)
                
                # Save cookies after activity
                browser_cookies = await browser.get_cookies(["https://www.linkedin.com"])
                with get_db() as db:
                    cookie_repo = CookieRepository(db)
                    cookie_repo.set_from_playwright(session.profile_db_id, browser_cookies)
                
                return {
                    "status": "ok",
                    "profile_id": profile_id,
                    "post": post_data,
                }
        
        return {
            "status": "error",
            "message": "Failed to extract post data",
        }
        
    except Exception as e:
        logger.error(f"Failed to get post: {e}")
        import traceback
        traceback.print_exc()
        return {
            "status": "error",
            "message": str(e),
        }


async def like_post(
    profile_id: str,
    post_url: str,
) -> dict:
    """Like a LinkedIn post.
    
    Args:
        profile_id: Profile UUID
        post_url: Full LinkedIn post URL or path
    
    Returns:
        Dict with operation status
    """
    logger.info(f"[like_post] Liking post: {post_url}")

    try:
        prep = await _prepare_post_action_context(
            profile_id=profile_id,
            post_url=post_url,
            action_name="like_post",
            viewport_selectors=[
                'button[data-feed-control="like_toggle"]',
                'button[aria-label*="Like" i]',
                'button[aria-label*="React Like" i]',
                '[class*="feed-shared-social-actions"] button',
                'article[data-activity-urn]',
                '.feed-shared-update-v2',
            ],
            center_selectors=[
                'button[data-feed-control="like_toggle"]',
                'button[aria-label*="Like" i]',
                'button[aria-label*="React Like" i]',
                '[class*="feed-shared-social-actions"] button',
                'article[data-activity-urn]',
                '.feed-shared-update-v2',
            ],
            scan_base_pixels=650,
        )
        if prep.get("status") != "ok":
            return prep

        session = prep["session"]
        browser = prep["browser"]
        human = prep["human"]
        layout_type = prep["layout_type"]
        normalized_post_url = prep["post_url"]

        if layout_type == "mobile":
            # Mobile: use existing mobile selectors
            return await _like_post_mobile(browser, human, profile_id, session)
        else:
            # Desktop: use new React UI selectors
            return await _like_post_desktop(browser, human, profile_id, session, normalized_post_url)

    except Exception as e:
        logger.error(f"Failed to like post: {e}")
        import traceback
        traceback.print_exc()
        return {
            "status": "error",
            "message": str(e),
        }


async def _prepare_post_action_context(
    profile_id: str,
    post_url: str,
    action_name: str,
    viewport_selectors: List[str],
    center_selectors: List[str],
    scan_base_pixels: int = 650,
) -> Dict[str, Any]:
    """Shared preparation for post interactions (navigate once, detect layout, prep viewport)."""
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
    human = HumanBehavior()

    if not post_url.startswith("http"):
        post_url = f"https://www.linkedin.com{post_url}"

    logger.info(f"[{action_name}] Navigating to: {post_url}")
    nav_error = None
    for attempt in range(1, 4):
        try:
            await browser.navigate(post_url, wait_until="commit", timeout=25000)
            nav_error = None
            break
        except Exception as e:
            nav_error = e
            message = str(e).lower()
            is_retryable = _is_retryable_navigation_error(e)
            is_closed_context = (
                "target page, context or browser has been closed" in message
                or "target closed" in message
            )
            logger.warning(f"[{action_name}] Navigation attempt {attempt}/3 failed: {e}")
            if attempt < 3 and is_retryable:
                if is_closed_context or attempt == 2:
                    logger.warning(f"[{action_name}] Rotating browser session/proxy before final navigation retry")
                    session = await session_manager.create_session(profile_id, force_new=True)
                    browser = session.browser
                await human.delay(1200, 2400)
                continue
            raise

    if nav_error is not None:
        raise nav_error

    await human.page_load_delay()

    current_url = await browser.get_current_url()
    if "login" in current_url or "authwall" in current_url:
        return {
            "status": "error",
            "message": "Not logged in - please login first",
        }

    is_mobile = "/mwlite/" in current_url
    layout_type = "mobile" if is_mobile else "desktop"

    if not is_mobile:
        mobile_check = await browser.evaluate(
            """
            () => {
                return !!document.querySelector('article[data-activity-urn]');
            }
            """
        )
        if mobile_check:
            layout_type = "mobile"

    logger.info(f"[{action_name}] Detected layout: {layout_type}")

    if layout_type == "mobile":
        await browser.wait_for_selector("article[data-activity-urn]", timeout=10000)
        logger.info(f"[{action_name}] Mobile article found")
    else:
        try:
            await browser.wait_for_selector('[role="main"]', timeout=10000)
            logger.info(f"[{action_name}] Desktop main content found")
        except Exception:
            pass

    await human.delay(2000, 3000)

    await humanize_post_interaction_viewport(
        browser,
        human,
        selectors=viewport_selectors,
        scan_steps=2,
        scan_base_pixels=scan_base_pixels,
    )

    auth_wall_reason = await _detect_auth_wall(browser)
    if auth_wall_reason:
        logger.warning(f"[{action_name}] Auth wall detected after scrolling: {auth_wall_reason}")
        return {
            "status": "error",
            "message": f"Not logged in / auth wall detected ({auth_wall_reason})",
        }

    await center_first_visible(
        browser,
        human,
        selectors=center_selectors,
        block="center",
        settle_min_ms=500,
        settle_max_ms=1000,
    )

    return {
        "status": "ok",
        "session": session,
        "browser": browser,
        "human": human,
        "layout_type": layout_type,
        "post_url": post_url,
    }


async def _like_post_mobile(browser, human, profile_id: str, session) -> dict:
    """Like a post on mobile layout."""
    try:
        # Wait for like button
        try:
            await browser.wait_for_selector('button[data-feed-control="like_toggle"]', timeout=10000)
            logger.info("[like_post_mobile] Like button found")
        except Exception as e:
            logger.error(f"[like_post_mobile] Like button not found: {e}")
            return {"status": "error", "message": "Like button not found"}
        
        like_button = await browser.query_selector('button[data-feed-control="like_toggle"]')
        
        if not like_button:
            return {"status": "error", "message": "Like button not found"}

        await center_first_visible(
            browser,
            human,
            selectors=['button[data-feed-control="like_toggle"]', 'article[data-activity-urn]'],
            block="center",
            settle_min_ms=500,
            settle_max_ms=900,
        )
        
        # Check if already liked
        aria_pressed = await like_button.get_attribute("aria-pressed")
        if aria_pressed == "true":
            logger.info("[like_post_mobile] Post already liked")
            return {
                "status": "ok",
                "profile_id": profile_id,
                "message": "Post was already liked",
                "already_liked": True,
            }
        
        # Click like button
        is_visible = await like_button.is_visible()
        if is_visible:
            await human.delay(500, 1000)
            clicked = await browser.click_element_human(like_button)
            if not clicked:
                return {"status": "error", "message": "Like button not clickable"}
        else:
            return {"status": "error", "message": "Like button not visible"}
        
        logger.info("[like_post_mobile] Post liked successfully")
        
        # Save cookies
        browser_cookies = await browser.get_cookies(["https://www.linkedin.com"])
        with get_db() as db:
            cookie_repo = CookieRepository(db)
            cookie_repo.set_from_playwright(session.profile_db_id, browser_cookies)
        
        return {
            "status": "ok",
            "profile_id": profile_id,
            "message": "Post liked successfully",
            "already_liked": False,
        }
    except Exception as e:
        logger.error(f"[like_post_mobile] Error: {e}")
        return {"status": "error", "message": str(e)}


async def _like_post_desktop(browser, human, profile_id: str, session, post_url: str) -> dict:
    """Like a post on desktop layout (new React UI)."""
    try:
        activity_token = _extract_activity_token(post_url)
        activity_token_literal = json.dumps(activity_token or "")

        like_result = {"status": "not_found"}
        for attempt in range(1, 5):
            like_result = await browser.evaluate(
                """
                () => {
                    document.querySelectorAll('[data-mcp-like-target="true"]').forEach((node) => {
                        node.removeAttribute('data-mcp-like-target');
                    });
                    const normalizedToken = (__ACTIVITY_TOKEN__ || '').trim().toLowerCase();
                    const isVisible = (el) => {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        if (style.display === 'none' || style.visibility === 'hidden') return false;
                        const rect = el.getBoundingClientRect();
                        return rect.width > 0 && rect.height > 0;
                    };

                    const roots = Array.from(document.querySelectorAll(
                        '[data-activity-urn], article[data-activity-urn], .feed-shared-update-v2, .occludable-update, [data-urn]'
                    ));

                    const matchRootByToken = (root) => {
                        if (!normalizedToken) return false;
                        const attrs = [
                            root.getAttribute('data-activity-urn') || '',
                            root.getAttribute('data-urn') || '',
                            root.id || '',
                        ].join(' ').toLowerCase();
                        if (attrs.includes(normalizedToken)) return true;
                        return Array.from(root.querySelectorAll('a[href*="/feed/update/"], a[href*="/posts/"]'))
                            .some((a) => ((a.getAttribute('href') || '').toLowerCase()).includes(normalizedToken));
                    };

                    let targetRoot = null;
                    if (normalizedToken) {
                        targetRoot = roots.find((root) => matchRootByToken(root)) || null;
                    }
                    if (!targetRoot) {
                        targetRoot = roots.find((root) => isVisible(root)) || document.querySelector('[role="main"]') || document;
                    }

                    const candidates = Array.from(targetRoot.querySelectorAll('button')).filter((btn) => isVisible(btn) && !btn.disabled);
                    for (const btn of candidates) {
                        const aria = (
                            btn.getAttribute('aria-label') ||
                            btn.getAttribute('title') ||
                            btn.innerText ||
                            btn.textContent || ''
                        ).trim().toLowerCase();
                        if (!aria) continue;

                        const likelyLike =
                            aria.includes('react like') ||
                            aria.includes('like this post') ||
                            aria === 'like' ||
                            (aria.includes('like') && !aria.includes('comment') && !aria.includes('repost') && !aria.includes('share') && !aria.includes('send'));
                        if (!likelyLike) continue;

                        const alreadyLiked =
                            btn.getAttribute('aria-pressed') === 'true' ||
                            aria.includes('unlike') ||
                            aria.includes('remove your like');
                        if (alreadyLiked) {
                            return { status: 'already_liked' };
                        }
                        btn.setAttribute('data-mcp-like-target', 'true');
                        return { status: 'target_marked' };
                    }

                    const bar = targetRoot.querySelector('[class*="social-actions"], [class*="feed-shared-social-actions"], [data-test-id*="social-actions"]');
                    if (bar) {
                        const barButtons = Array.from(bar.querySelectorAll('button')).filter((btn) => isVisible(btn) && !btn.disabled);
                        if (barButtons.length > 0) {
                            const first = barButtons[0];
                            if (first.getAttribute('aria-pressed') === 'true') {
                                return { status: 'already_liked' };
                            }
                            first.setAttribute('data-mcp-like-target', 'true');
                            return { status: 'target_marked' };
                        }
                    }

                    return { status: 'not_found' };
                }
                """.replace("__ACTIVITY_TOKEN__", activity_token_literal)
            )

            logger.info(f"[like_post_desktop] Attempt {attempt}/4 result: {like_result}")
            if like_result.get('status') == 'target_marked':
                target_button = await browser.query_selector('[data-mcp-like-target="true"]')
                if target_button and await browser.click_element_human(target_button):
                    like_result = {"status": "clicked"}
                else:
                    like_result = {"status": "not_found"}
            if like_result.get('status') != 'not_found':
                break

            await center_first_visible(
                browser,
                human,
                selectors=[
                    'article[data-activity-urn]',
                    '.feed-shared-update-v2',
                    '[class*="social-actions"]',
                    '[class*="feed-shared-social-actions"]',
                    'button[aria-label*="Like" i]',
                    'button[aria-label*="React" i]',
                ],
                block="center",
                settle_min_ms=700,
                settle_max_ms=1300,
            )
            await human.delay(900, 1700)
        
        if like_result.get('status') == 'already_liked':
            return {
                "status": "ok",
                "profile_id": profile_id,
                "message": "Post was already liked",
                "already_liked": True,
            }

        if like_result.get('status') == 'not_found':
            fallback_selectors = [
                'button[data-feed-control="like_toggle"]',
                'button[aria-label*="Reaction button state" i]',
                'button[aria-label*="React Like" i]',
                'button[aria-label*="Like" i]',
                '[class*="feed-shared-social-actions"] button',
                '[class*="social-actions"] button',
            ]
            for selector in fallback_selectors:
                try:
                    candidates = await browser.query_selector_all(selector)
                except Exception:
                    continue

                for btn in candidates:
                    try:
                        if not await btn.is_visible():
                            continue
                        if not await btn.is_enabled():
                            continue

                        aria = ((await btn.get_attribute("aria-label")) or "").strip().lower()
                        title = ((await btn.get_attribute("title")) or "").strip().lower()
                        text = ((await btn.inner_text()) or "").strip().lower()
                        combined = " ".join([aria, title, text])

                        likely_like = (
                            "react like" in combined
                            or "like this post" in combined
                            or combined == "like"
                            or (
                                "reaction button state" in combined
                                and "no reaction" in combined
                            )
                            or (
                                "like" in combined
                                and "comment" not in combined
                                and "repost" not in combined
                                and "share" not in combined
                                and "send" not in combined
                            )
                        )
                        if not likely_like:
                            continue

                        already_liked = (
                            (await btn.get_attribute("aria-pressed")) == "true"
                            or "unlike" in combined
                            or "remove your like" in combined
                        )
                        if already_liked:
                            return {
                                "status": "ok",
                                "profile_id": profile_id,
                                "message": "Post was already liked",
                                "already_liked": True,
                            }

                        if await browser.click_element_human(btn):
                            like_result = {"status": "clicked"}
                            break
                    except Exception:
                        continue

                if like_result.get('status') == 'clicked':
                    break

        if like_result.get('status') == 'not_found':
            return {"status": "error", "message": "Like button not found on desktop"}
        
        await human.delay(1000, 1500)
        logger.info("[like_post_desktop] Post liked successfully")
        
        # Save cookies
        browser_cookies = await browser.get_cookies(["https://www.linkedin.com"])
        with get_db() as db:
            cookie_repo = CookieRepository(db)
            cookie_repo.set_from_playwright(session.profile_db_id, browser_cookies)
        
        return {
            "status": "ok",
            "profile_id": profile_id,
            "message": "Post liked successfully",
            "already_liked": False,
        }
    except Exception as e:
        logger.error(f"[like_post_desktop] Error: {e}")
        return {"status": "error", "message": str(e)}


async def comment_post(
    profile_id: str,
    post_url: str,
    comment_text: str,
) -> dict:
    """Comment on a LinkedIn post.
    
    Args:
        profile_id: Profile UUID
        post_url: Full LinkedIn post URL or path
        comment_text: Comment text to post
    
    Returns:
        Dict with operation status
    """
    logger.info(f"[comment_post] Commenting on post: {post_url}")

    try:
        prep = await _prepare_post_action_context(
            profile_id=profile_id,
            post_url=post_url,
            action_name="comment_post",
            viewport_selectors=[
                'article[data-activity-urn]',
                '.feed-shared-update-v2',
                '[role="main"] article',
                'button[aria-label*="comment" i]',
                'form.comments-comment-box__form',
            ],
            center_selectors=[
                'button[aria-label*="comment" i]',
                'form.comments-comment-box__form',
                'article[data-activity-urn]',
                '.feed-shared-update-v2',
            ],
            scan_base_pixels=600,
        )
        if prep.get("status") != "ok":
            return prep

        session = prep["session"]
        browser = prep["browser"]
        human = prep["human"]
        layout_type = prep["layout_type"]
        normalized_post_url = prep["post_url"]

        if layout_type == "mobile":
            return await _comment_post_mobile(browser, human, profile_id, session, comment_text)
        return await _comment_post_desktop(browser, human, profile_id, session, comment_text, normalized_post_url)

    except Exception as e:
        logger.error(f"Failed to comment on post: {e}")
        import traceback
        traceback.print_exc()
        return {
            "status": "error",
            "message": str(e),
        }


async def like_and_comment_post(
    profile_id: str,
    post_url: str,
    comment_text: str,
) -> dict:
    """Like and comment on a LinkedIn post in one page load.

    Args:
        profile_id: Profile UUID
        post_url: Full LinkedIn post URL or path
        comment_text: Comment text to post

    Returns:
        Dict with per-action results and combined status
    """
    logger.info(f"[like_and_comment_post] Running combined action on: {post_url}")

    try:
        prep = await _prepare_post_action_context(
            profile_id=profile_id,
            post_url=post_url,
            action_name="like_and_comment_post",
            viewport_selectors=[
                'button[data-feed-control="like_toggle"]',
                'button[aria-label*="Like" i]',
                'button[aria-label*="React Like" i]',
                'button[aria-label*="comment" i]',
                'form.comments-comment-box__form',
                'article[data-activity-urn]',
                '.feed-shared-update-v2',
                '[role="main"] article',
            ],
            center_selectors=[
                'button[data-feed-control="like_toggle"]',
                'button[aria-label*="Like" i]',
                'button[aria-label*="comment" i]',
                'form.comments-comment-box__form',
                'article[data-activity-urn]',
                '.feed-shared-update-v2',
            ],
            scan_base_pixels=650,
        )
        if prep.get("status") != "ok":
            return prep

        session = prep["session"]
        browser = prep["browser"]
        human = prep["human"]
        layout_type = prep["layout_type"]
        normalized_post_url = prep["post_url"]

        if layout_type == "mobile":
            like_result = await _like_post_mobile(browser, human, profile_id, session)
            await human.delay(700, 1200)
            comment_result = await _comment_post_mobile(browser, human, profile_id, session, comment_text)
        else:
            like_result = await _like_post_desktop(browser, human, profile_id, session, normalized_post_url)
            await human.delay(700, 1200)
            comment_result = await _comment_post_desktop(browser, human, profile_id, session, comment_text, normalized_post_url)

        like_ok = isinstance(like_result, dict) and like_result.get("status") == "ok"
        comment_ok = isinstance(comment_result, dict) and comment_result.get("status") == "ok"

        if like_ok and comment_ok:
            return {
                "status": "ok",
                "profile_id": profile_id,
                "post_url": normalized_post_url,
                "message": "Post liked and commented successfully",
                "page_loaded_once": True,
                "like_result": like_result,
                "comment_result": comment_result,
            }

        return {
            "status": "error",
            "profile_id": profile_id,
            "post_url": normalized_post_url,
            "message": "Combined action did not fully succeed",
            "page_loaded_once": True,
            "like_result": like_result,
            "comment_result": comment_result,
        }

    except Exception as e:
        logger.error(f"Failed to like and comment post: {e}")
        import traceback
        traceback.print_exc()
        return {
            "status": "error",
            "message": str(e),
        }


async def _comment_post_mobile(browser, human, profile_id: str, session, comment_text: str) -> dict:
    """Comment on a post using mobile layout."""
    try:
        auth_wall_reason = await _detect_auth_wall(browser)
        if auth_wall_reason:
            return {
                "status": "error",
                "message": f"Cannot comment: auth wall detected ({auth_wall_reason})",
            }

        # Find comment textarea
        comment_textarea_selectors = [
            '#comment-editable-container',
            'div[contenteditable="true"][data-placeholder-default*="comment"]',
            'div[contenteditable="true"][role="textbox"]',
            'textarea[name="commentText"]',
        ]
        
        comment_textarea = None
        for selector in comment_textarea_selectors:
            try:
                await browser.wait_for_selector(selector, timeout=5000)
                comment_textarea = await browser.query_selector(selector)
                if comment_textarea:
                    logger.info(f"[comment_post_mobile] Found textarea: {selector}")
                    break
            except:
                continue
        
        if not comment_textarea:
            return {"status": "error", "message": "Comment textarea not found"}
        
        # Center comment editor in viewport
        await center_first_visible(
            browser,
            human,
            selectors=[
                '#comment-editable-container',
                'div[contenteditable="true"][data-placeholder-default*="comment"]',
                'div[contenteditable="true"][role="textbox"]',
                'textarea[name="commentText"]',
            ],
            block="center",
            settle_min_ms=800,
            settle_max_ms=1300,
        )
        
        is_visible = await comment_textarea.is_visible()
        if is_visible:
            clicked = await browser.click_element_human(comment_textarea)
            if not clicked:
                return {"status": "error", "message": "Comment textarea not clickable"}
        else:
            return {"status": "error", "message": "Comment textarea not visible"}
        
        await human.delay(500, 1000)
        
        # Type comment
        if not await _type_text_human_like(comment_textarea, comment_text, human, browser=browser):
            return {"status": "error", "message": "Failed to type comment"}
        await human.delay(1000, 1500)
        
        # Find and click submit button
        submit_button_selectors = [
            '#post-comment-button',
            'button[data-feed-control="feed-comment_post"]',
            'button.comment-box__post-btn',
        ]

        submit_clicked = await _click_button_human_like(
            browser,
            human,
            selectors=submit_button_selectors,
            text_candidates=["post", "comment"],
        )
        if not submit_clicked:
            return {"status": "error", "message": "Submit button not found"}
        
        await human.delay(2000, 3000)
        logger.info("[comment_post_mobile] Comment posted successfully")
        
        # Save cookies
        browser_cookies = await browser.get_cookies(["https://www.linkedin.com"])
        with get_db() as db:
            cookie_repo = CookieRepository(db)
            cookie_repo.set_from_playwright(session.profile_db_id, browser_cookies)
        
        return {
            "status": "ok",
            "profile_id": profile_id,
            "message": "Comment posted successfully",
            "comment_text": comment_text,
        }
    except Exception as e:
        logger.error(f"[comment_post_mobile] Error: {e}")
        return {"status": "error", "message": str(e)}


async def _comment_post_desktop(browser, human, profile_id: str, session, comment_text: str, post_url: str) -> dict:
    """Comment on a post using desktop layout (new React UI)."""
    try:
        auth_wall_reason = await _detect_auth_wall(browser)
        if auth_wall_reason:
            return {
                "status": "error",
                "message": f"Cannot comment: auth wall detected ({auth_wall_reason})",
            }

        activity_token = _extract_activity_token(post_url)
        activity_token_literal = json.dumps(activity_token or "")

        # Scope comment interaction to target post container.
        comment_result_js = """
            () => {
                document.querySelectorAll('[data-mcp-target-comment-button="true"]').forEach((node) => {
                    node.removeAttribute('data-mcp-target-comment-button');
                });
                const isVisible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                };

                const roots = Array.from(document.querySelectorAll('[data-activity-urn], article[data-activity-urn], .feed-shared-update-v2, .occludable-update'));
                const normalizedToken = (__ACTIVITY_TOKEN__ || '').trim();

                let targetRoot = null;
                if (normalizedToken) {
                    targetRoot = roots.find((root) => {
                        const attrs = [
                            root.getAttribute('data-activity-urn') || '',
                            root.getAttribute('data-urn') || '',
                            root.id || '',
                        ].join(' ').toLowerCase();
                        return attrs.includes(normalizedToken.toLowerCase());
                    }) || null;
                }

                if (!targetRoot) {
                    targetRoot = roots.find((r) => isVisible(r)) || document.querySelector('[role="main"]') || document;
                }

                const buttons = targetRoot.querySelectorAll('button, [role="button"]');
                for (const btn of buttons) {
                    if (!isVisible(btn) || btn.disabled) continue;
                    const ariaLabel = (btn.getAttribute('aria-label') || '').toLowerCase();
                    const text = (btn.innerText || btn.textContent || '').trim().toLowerCase();
                    if (ariaLabel.includes('comment') || text === 'comment') {
                        btn.setAttribute('data-mcp-target-comment-button', 'true');
                        const form = targetRoot.querySelector('form.comments-comment-box__form') ||
                                     targetRoot.querySelector('.comments-comment-box__form');
                        if (form) {
                            form.setAttribute('data-mcp-target-comment-form', 'true');
                        }
                        return { status: 'comment_button_marked', scoped: true };
                    }
                }

                const scopedInput = targetRoot.querySelector('form.comments-comment-box__form .ql-editor[contenteditable="true"], form.comments-comment-box__form [contenteditable="true"][role="textbox"]');
                if (scopedInput && isVisible(scopedInput)) {
                    const form = scopedInput.closest('form.comments-comment-box__form, .comments-comment-box__form');
                    if (form) {
                        form.setAttribute('data-mcp-target-comment-form', 'true');
                    }
                    return { status: 'input_already_visible', scoped: true };
                }

                return { status: 'comment_button_not_found', scoped: false };
            }
        """.replace("__ACTIVITY_TOKEN__", activity_token_literal)
        comment_result = await browser.evaluate(comment_result_js)

        if comment_result.get('status') == 'comment_button_marked':
            comment_btn = await browser.query_selector('[data-mcp-target-comment-button="true"]')
            if comment_btn and await browser.click_element_human(comment_btn):
                comment_result = {"status": "comment_button_clicked", "scoped": True}
            else:
                comment_result = {"status": "comment_button_not_found", "scoped": False}
        
        logger.info(f"[comment_post_desktop] Initial result: {comment_result}")

        if comment_result.get('status') == 'comment_button_not_found':
            fallback_comment_clicked = await _click_button_human_like(
                browser,
                human,
                selectors=[
                    'button[aria-label*="comment" i]',
                    '[role="button"][aria-label*="comment" i]',
                    '[class*="social-actions"] button',
                    '[class*="feed-shared-social-actions"] button',
                ],
                text_candidates=['comment'],
                scope_selector='main, [role="main"], article, [data-activity-urn], .feed-shared-update-v2',
            )
            if fallback_comment_clicked:
                comment_result = {"status": "comment_button_clicked", "scoped": False}
                await human.delay(700, 1200)
            else:
                auth_wall_reason = await _detect_auth_wall(browser)
                if auth_wall_reason:
                    return {
                        "status": "error",
                        "message": f"Cannot comment: auth wall detected ({auth_wall_reason})",
                    }
                return {"status": "error", "message": "Comment button not found on desktop"}
        
        # Find and focus comment input in scoped comment form only.
        comment_input_selectors = [
            '[data-mcp-target-comment-form="true"] .ql-editor[contenteditable="true"]',
            '[data-mcp-target-comment-form="true"] [contenteditable="true"][role="textbox"]',
            'form.comments-comment-box__form .ql-editor[contenteditable="true"]',
            'form.comments-comment-box__form [contenteditable="true"][role="textbox"]',
            '.comments-comment-box__form .ql-editor[contenteditable="true"]',
            '.comments-comment-box__form [contenteditable="true"][role="textbox"]',
            '.tiptap.ProseMirror[contenteditable="true"]',
            'div[aria-label*="Text editor for creating comment" i][contenteditable="true"]',
            '[contenteditable="true"][data-placeholder*="comment" i]',
            '[contenteditable="true"][aria-label*="comment" i]',
            'textarea[name*="comment" i]',
            'textarea[placeholder*="comment" i]',
        ]

        reopen_comment_js = """
            () => {
                document.querySelectorAll('[data-mcp-reopen-comment-button="true"]').forEach((node) => {
                    node.removeAttribute('data-mcp-reopen-comment-button');
                });
                const isVisible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') return false;
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                };

                const normalizedToken = (__ACTIVITY_TOKEN__ || '').trim().toLowerCase();
                const roots = Array.from(document.querySelectorAll('[data-activity-urn], article[data-activity-urn], .feed-shared-update-v2, .occludable-update'));

                let targetRoot = null;
                if (normalizedToken) {
                    targetRoot = roots.find((root) => {
                        const attrs = [
                            root.getAttribute('data-activity-urn') || '',
                            root.getAttribute('data-urn') || '',
                            root.id || '',
                        ].join(' ').toLowerCase();
                        return attrs.includes(normalizedToken);
                    }) || null;
                }
                if (!targetRoot) {
                    targetRoot = roots.find((r) => isVisible(r)) || document.querySelector('[role="main"]') || document;
                }

                const scopedForm = targetRoot.querySelector('form.comments-comment-box__form, .comments-comment-box__form');
                if (scopedForm) {
                    scopedForm.setAttribute('data-mcp-target-comment-form', 'true');
                    const scopedInput = scopedForm.querySelector('.ql-editor[contenteditable="true"], [contenteditable="true"][role="textbox"]');
                    if (scopedInput && isVisible(scopedInput)) {
                        scopedInput.focus();
                        return 'focused_existing_input';
                    }
                }

                const buttons = Array.from(targetRoot.querySelectorAll('button, [role="button"]'));
                for (const btn of buttons) {
                    if (!isVisible(btn) || btn.disabled) continue;
                    const label = (btn.getAttribute('aria-label') || btn.innerText || btn.textContent || '').trim().toLowerCase();
                    if (!label) continue;
                    if (label.includes('comment') || label === 'comment') {
                        btn.setAttribute('data-mcp-reopen-comment-button', 'true');
                        return 'marked_comment_again';
                    }
                }

                return 'no_recovery_action';
            }
        """.replace("__ACTIVITY_TOKEN__", activity_token_literal)

        comment_input = None
        for attempt in range(1, 7):
            await center_first_visible(
                browser,
                human,
                selectors=['[data-mcp-target-comment-form="true"]', '.comments-comment-box__form', '[contenteditable="true"][role="textbox"]'],
                block="center",
                settle_min_ms=450,
                settle_max_ms=900,
            )

            for selector in comment_input_selectors:
                try:
                    await browser.wait_for_selector(selector, timeout=2200)
                except Exception:
                    pass

                try:
                    comment_input = await browser.query_selector(selector)
                    if comment_input:
                        is_visible = await comment_input.is_visible()
                        if is_visible:
                            logger.info(f"[comment_post_desktop] Found comment input on attempt {attempt}/6: {selector}")
                            break
                        comment_input = None
                except Exception:
                    continue

            if comment_input:
                break

            if attempt in (2, 4):
                recovery_result = await browser.evaluate(reopen_comment_js)
                if recovery_result == 'marked_comment_again':
                    recovery_btn = await browser.query_selector('[data-mcp-reopen-comment-button="true"]')
                    if recovery_btn and await browser.click_element_human(recovery_btn):
                        recovery_result = 'clicked_comment_again'
                    else:
                        recovery_result = 'no_recovery_action'
                logger.info(f"[comment_post_desktop] Recovery click attempt {attempt}/6: {recovery_result}")

            await human.delay(700, 1200)
        
        if not comment_input:
            try:
                focused_marked = await browser.evaluate(
                    """
                    () => {
                        document.querySelectorAll('[data-mcp-active-comment-input="true"]').forEach((node) => {
                            node.removeAttribute('data-mcp-active-comment-input');
                        });
                        const active = document.activeElement;
                        if (!active) return false;
                        const tag = (active.tagName || '').toLowerCase();
                        const isTypeable = tag === 'textarea' || tag === 'input' || !!active.isContentEditable;
                        if (!isTypeable) return false;
                        active.setAttribute('data-mcp-active-comment-input', 'true');
                        return true;
                    }
                    """
                )
                if focused_marked:
                    comment_input = await browser.query_selector('[data-mcp-active-comment-input="true"]')
            except Exception:
                pass

        if not comment_input:
            auth_wall_reason = await _detect_auth_wall(browser)
            if auth_wall_reason:
                return {
                    "status": "error",
                    "message": f"Cannot comment: auth wall detected ({auth_wall_reason})",
                }
            return {"status": "error", "message": "Comment input field not found"}
        
        # Type the comment with resilient retries for TipTap/ProseMirror variants.
        typed_ok = False
        for type_attempt in range(1, 4):
            typed = await _type_text_human_like(comment_input, comment_text, human, browser=browser)

            has_typed_text = await browser.evaluate(
                """
                () => {
                    const isVisible = (el) => {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        if (style.display === 'none' || style.visibility === 'hidden') return false;
                        const rect = el.getBoundingClientRect();
                        return rect.width > 0 && rect.height > 0;
                    };

                    const editors = Array.from(document.querySelectorAll(
                        '.tiptap.ProseMirror[contenteditable="true"], div[aria-label*="Text editor for creating comment"][contenteditable="true"], form.comments-comment-box__form [contenteditable="true"][role="textbox"], .comments-comment-box__form [contenteditable="true"][role="textbox"], textarea[name*="comment" i], textarea[placeholder*="comment" i]'
                    )).filter((el) => isVisible(el));

                    if (editors.length === 0) return false;
                    const focused = editors.find((el) => el.classList?.contains('ProseMirror-focused')) || document.activeElement;
                    const target = (focused && editors.includes(focused)) ? focused : editors[0];

                    if (!target) return false;
                    const tag = (target.tagName || '').toLowerCase();
                    const value = (tag === 'textarea' || tag === 'input')
                        ? (target.value || '')
                        : (target.innerText || target.textContent || '');
                    return value.trim().length > 0;
                }
                """
            )

            if typed and has_typed_text:
                typed_ok = True
                break

            try:
                await browser.click_element_human(comment_input)
                await human.delay(150, 350)
                await browser.page.keyboard.type(comment_text, delay=human.get_typing_speed())
            except Exception:
                pass

            has_typed_text = await browser.evaluate(
                """
                () => {
                    const active = document.activeElement;
                    if (!active) return false;
                    const tag = (active.tagName || '').toLowerCase();
                    const value = (tag === 'textarea' || tag === 'input')
                        ? (active.value || '')
                        : (active.innerText || active.textContent || '');
                    return value.trim().length > 0;
                }
                """
            )
            if has_typed_text:
                typed_ok = True
                break

            logger.info(f"[comment_post_desktop] Typing retry {type_attempt}/3 did not stick yet")
            await human.delay(350, 650)

        if not typed_ok:
            return {"status": "error", "message": "Failed to type comment"}

        await human.delay(1000, 1500)
        
        logger.info("[comment_post_desktop] Comment text entered")
        
        # Find and click submit/post button
        submit_button_selectors = [
            'button.comments-comment-box__submit-button--cr',
            'button.comments-comment-box__submit-button',
            '[componentkey*="commentButtonSection"] button',
            '[class*="commentButtonSection"] button',
            'button[type="submit"]',
            'button[aria-label*="post comment" i]',
            'button[aria-label*="post" i]',
            'button[aria-label*="reply" i]',
            'button[aria-label*="post" i]',
            'button:has-text("Comment")',
            'button:has-text("Post")',
            'button:has-text("Reply")',
        ]

        submit_clicked = await _click_button_human_like(
            browser,
            human,
            selectors=submit_button_selectors,
            text_candidates=["comment", "post", "reply"],
            scope_selector='form.comments-comment-box__form, .comments-comment-box__form, [data-testid="ui-core-tiptap-text-editor-wrapper"], [aria-label*="Text editor for creating comment" i]',
        )
        if not submit_clicked:
            submit_clicked = await _click_button_human_like(
                browser,
                human,
                selectors=submit_button_selectors,
                text_candidates=["comment", "post", "reply"],
                scope_selector='main, [role="main"], article, [data-activity-urn], .feed-shared-update-v2',
            )
        if not submit_clicked:
            return {"status": "error", "message": "Submit button not found"}
        logger.info("[comment_post_desktop] Clicked submit button")
        
        await human.delay(2000, 3000)
        logger.info("[comment_post_desktop] Comment posted successfully")
        
        # Save cookies
        browser_cookies = await browser.get_cookies(["https://www.linkedin.com"])
        with get_db() as db:
            cookie_repo = CookieRepository(db)
            cookie_repo.set_from_playwright(session.profile_db_id, browser_cookies)
        
        return {
            "status": "ok",
            "profile_id": profile_id,
            "message": "Comment posted successfully",
            "comment_text": comment_text,
        }
    except Exception as e:
        logger.error(f"[comment_post_desktop] Error: {e}")
        return {"status": "error", "message": str(e)}


async def _write_post_content(browser, human, content: str, image_path: Optional[str], log_prefix: str) -> dict:
    """Shared helper to write post content and upload image.
    
    Args:
        browser: StealthBrowser instance
        human: HumanBehavior instance
        content: Post text content
        image_path: Optional path to image file
        log_prefix: Logging prefix for context
    
    Returns:
        Dict with status and any error message
    """
    # Look for text editor - mobile LinkedIn uses div.textarea[contenteditable]
    editor_selectors = [
        '.ql-editor[contenteditable="true"]',
        '.editor-content .ql-editor',
        'div.textarea[contenteditable="true"]',  # Mobile share modal
        '.modal-content div[contenteditable="true"]',  # Share modal content
        'div[contenteditable="true"][data-placeholder]',  # With placeholder
        'div[contenteditable="true"][aria-label*="editor"]',
        'div[contenteditable="true"][role="textbox"]',
        'textarea[name="share-text"]',
        '#share-text',
        'div[contenteditable="true"]',
        'textarea',
    ]
    
    editor = None
    for selector in editor_selectors:
        if await browser.wait_for_selector(selector, timeout=5000):
            editor = await browser.query_selector(selector)
            if editor:
                logger.info(f"[{log_prefix}] Found editor: {selector}")
                break
    
    if not editor:
        return {"status": "error", "message": "Could not find post editor"}
    
    # Click on editor to focus
    await human.action_delay()
    if not await browser.click_element_human(editor):
        return {"status": "error", "message": "Could not focus post editor"}
    await human.delay(300, 500)
    
    # Upload image FIRST if provided (before typing content)
    # This ensures we don't waste time typing if image upload fails
    if image_path:
        logger.info(f"[{log_prefix}] Uploading image first: {image_path}")
        
        # Look for image upload button/input - mobile uses #image-upload
        image_input_selectors = [
            '#image-upload',  # Mobile share modal
            'input#image-upload[type="file"]',
            'input[type="file"][accept*="image"]',
            'input[type="file"]',
        ]
        
        image_input = None
        image_input_selector = None
        for selector in image_input_selectors:
            image_input = await browser.query_selector(selector)
            if image_input:
                image_input_selector = selector
                logger.info(f"[{log_prefix}] Found image input: {selector}")
                break
        
        if not image_input:
            # Try clicking image button first to reveal input
            image_button_selectors = [
                'button[aria-label*="image"]',
                'button[aria-label*="photo"]',
                'button[data-tracking-control-name*="image"]',
                '.share-box-feed-entry__image-upload',
                'li[aria-label*="image"] button',
                'li[aria-label*="photo"] button',
            ]
            
            for selector in image_button_selectors:
                image_button = await browser.query_selector(selector)
                if image_button:
                    logger.info(f"[{log_prefix}] Clicking image button: {selector}")
                    if not await browser.click_element_human(image_button):
                        continue
                    await human.delay(500, 1000)
                    
                    # Now look for file input again
                    for input_selector in image_input_selectors:
                        image_input = await browser.query_selector(input_selector)
                        if image_input:
                            image_input_selector = input_selector
                            break
                    break
        
        uploaded_via_chooser = False
        direct_upload_failed = False
        image_uploaded = False

        if image_input and image_input_selector:
            # Upload the file
            try:
                await browser.locator_set_input_files(image_input_selector, [image_path])
                logger.info(f"[{log_prefix}] Image uploaded successfully")
                image_uploaded = True
                await human.delay(2000, 3000)  # Wait for image to process
            except Exception as e:
                logger.warning(f"[{log_prefix}] Direct file input upload failed, trying file chooser fallback: {e}")
                direct_upload_failed = True

        if not image_input or not image_input_selector:
            logger.info(f"[{log_prefix}] File input not found, trying file chooser fallback")

        if (not image_input or not image_input_selector) or direct_upload_failed:
            chooser_selectors = [
                'button[aria-label="Add media"]',
                'button[aria-label*="photo"]',
                'button[aria-label*="image"]',
                'button[data-control-name*="media"]',
                'button[data-tracking-control-name*="image"]',
            ]
            for chooser_selector in chooser_selectors:
                try:
                    upload_success = await browser.upload_file_via_chooser(
                        chooser_selector,
                        [image_path],
                        timeout=10000,
                    )
                except Exception:
                    upload_success = False
                if upload_success:
                    logger.info(f"[{log_prefix}] Image uploaded via chooser: {chooser_selector}")
                    uploaded_via_chooser = True
                    image_uploaded = True
                    await human.delay(2000, 3000)
                    break

            if not uploaded_via_chooser and (not image_input or not image_input_selector):
                logger.error(f"[{log_prefix}] Could not find image upload input")
                return {"status": "error", "message": "Could not find image upload input"}

            if direct_upload_failed and not uploaded_via_chooser:
                logger.error(f"[{log_prefix}] Image upload failed via both direct input and chooser fallback")
                return {"status": "error", "message": "Image upload failed"}

        # LinkedIn may open a media Editor modal after image selection; advance it.
        if image_uploaded:
            modal_advanced = False
            for _ in range(8):
                editor_modal_result = "editor_no_action"
                advanced = await _click_button_human_like(
                    browser,
                    human,
                    selectors=[
                        '[data-test-modal] button',
                        '.artdeco-modal button',
                        '.share-box-v2__modal button',
                        'button.artdeco-button--primary',
                    ],
                    text_candidates=['next', 'done'],
                    scope_selector='[data-test-modal], .artdeco-modal, .share-box-v2__modal',
                )
                if advanced:
                    editor_modal_result = 'clicked:next_or_done'
                logger.info(f"[{log_prefix}] Image editor modal handling result: {editor_modal_result}")

                if editor_modal_result == "no_modal":
                    await human.delay(500, 800)
                    continue
                if editor_modal_result == "not_editor":
                    break
                if isinstance(editor_modal_result, str) and editor_modal_result.startswith("clicked:"):
                    modal_advanced = True
                    await human.delay(2000, 3000)
                    break

                await human.delay(500, 800)

            # DOM often re-renders after media step; re-find editor before writing text.
            if modal_advanced:
                refreshed_editor = None
                for selector in editor_selectors:
                    refreshed_editor = await browser.query_selector(selector)
                    if refreshed_editor:
                        logger.info(f"[{log_prefix}] Re-found editor after media step: {selector}")
                        editor = refreshed_editor
                        break
    
    # Set the post content AFTER image is uploaded
    # Check if it's a textarea or contenteditable div
    tag_name = await editor.evaluate("el => el.tagName.toLowerCase()")
    logger.info(f"[{log_prefix}] Editor tag: {tag_name}")
    
    if tag_name == "textarea":
        await editor.fill(content)
    else:
        # For contenteditable divs, use JavaScript to set content directly
        # This avoids timeout issues with long content when using type()
        await editor.evaluate("""(el, text) => {
            el.focus();
            el.innerText = text;
            // Trigger input event so LinkedIn detects the change
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
        }""", content)
        logger.info(f"[{log_prefix}] Content set via JavaScript ({len(content)} chars)")
    
    await human.delay(1000, 2000)
    
    return {"status": "ok"}


async def _submit_post(browser, human, log_prefix: str) -> dict:
    """Shared helper to submit a post.
    
    Args:
        browser: StealthBrowser instance
        human: HumanBehavior instance
        log_prefix: Logging prefix for context
    
    Returns:
        Dict with status and any error message
    """
    # Find and click post/submit button - mobile uses button.post-button
    submit_button_selectors = [
        'button.post-button',  # Mobile share modal
        '.post-button-wrapper button',
        'button[data-tracking-control-name="post"]',
        'button[data-tracking-control-name="share_post"]',
        'button.share-actions__primary-action',
        '.share-box_actions button',
        'button.artdeco-button--primary',
        'button[aria-label*="Post"]',
        'button[aria-label*="Publish"]',
        '#share-submit-btn',
    ]
    
    submit_button = None
    for selector in submit_button_selectors:
        candidate = await browser.query_selector(selector)
        if not candidate:
            continue
        try:
            button_text = (await candidate.inner_text() or "").strip().lower()
        except Exception:
            button_text = ""
        if "manage" in button_text:
            continue
        if button_text and ("post" not in button_text and "publish" not in button_text):
            continue
        submit_button = candidate
        logger.info(f"[{log_prefix}] Found submit button: {selector} - '{button_text}'")
        break
    
    if not submit_button:
        logger.info(f"[{log_prefix}] No submit button found via selectors, trying text-based human click")

    await human.delay(500, 1000)

    submitted = False
    for _ in range(8):
        advanced_editor = await _click_button_human_like(
            browser,
            human,
            selectors=[
                '[data-test-modal] button',
                '.artdeco-modal button',
                '.share-box-v2__modal button',
            ],
            text_candidates=['next', 'done'],
            scope_selector='[data-test-modal], .artdeco-modal, .share-box-v2__modal',
        )
        if advanced_editor:
            await human.delay(1500, 2200)
            continue

        submitted = await _click_button_human_like(
            browser,
            human,
            selectors=submit_button_selectors + [
                '[aria-labelledby="share-to-linkedin-modal__header"] .share-box_actions .share-actions__primary-action',
                '[aria-labelledby="share-to-linkedin-modal__header"] .share-box_actions button',
            ],
            text_candidates=['post', 'publish'],
            scope_selector='[data-test-modal], .artdeco-modal, .share-box-v2__modal, [aria-labelledby="share-to-linkedin-modal__header"], .share-box_actions',
        )
        if submitted:
            break

        await human.delay(900, 1400)

    logger.info(f"[{log_prefix}] Post button click result: {'clicked' if submitted else 'not_found'}")
    if not submitted:
        return {"status": "error", "message": "Could not find post submit button"}
    
    await human.delay(3000, 5000)  # Wait for post to be submitted
    
    return {"status": "ok"}


async def create_post(
    profile_id: str,
    content: str,
    image_path: Optional[str] = None,
) -> dict:
    """Create a post from the personal account.
    
    Args:
        profile_id: Profile UUID
        content: Post text content
        image_path: Optional path to image file to attach
    
    Returns:
        Dict with post result
    """
    logger.info(f"[create_post] Starting for profile {profile_id}")
    logger.info(f"[create_post] Content length: {len(content)}")
    logger.info(f"[create_post] Image path: {image_path}")
    
    try:
        # Verify profile exists
        with get_db() as db:
            profile_repo = ProfileRepository(db)
            profile = profile_repo.get_by_uuid(profile_id)
            if not profile:
                return {
                    "status": "error",
                    "message": f"Profile {profile_id} not found",
                }
        
        # Validate image path if provided
        if image_path:
            import os
            if not os.path.exists(image_path):
                return {
                    "status": "error",
                    "message": f"Image file not found: {image_path}",
                }
        
        # Get or create session
        session_manager = get_session_manager()
        session = await session_manager.create_session(profile_id)
        browser = session.browser
        human = HumanBehavior()
        
        # Navigate to share page
        share_url = "https://www.linkedin.com/share"
        logger.info(f"[create_post] Navigating to: {share_url}")
        
        await browser.navigate(share_url)
        await human.page_load_delay()
        
        # Check if logged in
        current_url = await browser.get_current_url()
        logger.info(f"[create_post] Current URL: {current_url}")
        
        if "login" in current_url or "authwall" in current_url:
            return {
                "status": "error",
                "message": "Not logged in - please login first",
            }
        
        await human.delay(1000, 2000)
        
        # Write content and upload image
        write_result = await _write_post_content(browser, human, content, image_path, "create_post")
        if write_result["status"] != "ok":
            return write_result
        
        # Submit the post
        submit_result = await _submit_post(browser, human, "create_post")
        if submit_result["status"] != "ok":
            return submit_result
        
        # Verify post was created
        current_url = await browser.get_current_url()
        logger.info(f"[create_post] After submit URL: {current_url}")
        
        # Save cookies after activity
        browser_cookies = await browser.get_cookies(["https://www.linkedin.com"])
        with get_db() as db:
            cookie_repo = CookieRepository(db)
            cookie_repo.set_from_playwright(session.profile_db_id, browser_cookies)
        
        return {
            "status": "ok",
            "profile_id": profile_id,
            "message": "Post created successfully",
            "content_preview": content[:200] + "..." if len(content) > 200 else content,
            "has_image": image_path is not None,
        }
        
    except Exception as e:
        logger.error(f"Failed to create post: {e}")
        import traceback
        traceback.print_exc()
        return {
            "status": "error",
            "message": str(e),
        }


async def create_company_post(
    profile_id: str,
    company_url: str,
    content: str,
    image_path: Optional[str] = None,
) -> dict:
    """Create a post on behalf of a company page via desktop admin dashboard.
    
    Args:
        profile_id: Profile UUID (must have admin access to the company)
        company_url: LinkedIn company page URL
        content: Post text content
        image_path: Optional path to image file to attach
    
    Returns:
        Dict with post result
    """
    logger.info(f"[create_company_post] Starting for profile {profile_id}")
    logger.info(f"[create_company_post] Company URL: {company_url}")
    logger.info(f"[create_company_post] Content length: {len(content)}")
    logger.info(f"[create_company_post] Image path: {image_path}")
    
    try:
        # Verify profile exists
        with get_db() as db:
            profile_repo = ProfileRepository(db)
            profile = profile_repo.get_by_uuid(profile_id)
            if not profile:
                return {
                    "status": "error",
                    "message": f"Profile {profile_id} not found",
                }
        
        # Validate image path if provided
        if image_path:
            import os
            if not os.path.exists(image_path):
                return {
                    "status": "error",
                    "message": f"Image file not found: {image_path}",
                }
        
        # Get or create session
        session_manager = get_session_manager()
        session = await session_manager.create_session(profile_id)
        browser = session.browser
        human = HumanBehavior()
        
        # Extract company vanity name or ID from URL
        # URL formats: https://www.linkedin.com/company/masterlabs-ai/ or /company/106122782/
        company_identifier = company_url.rstrip('/').split('/company/')[-1].split('/')[0]
        logger.info(f"[create_company_post] Company identifier: {company_identifier}")
        
        # Navigate to company admin dashboard (desktop)
        admin_url = f"https://www.linkedin.com/company/{company_identifier}/admin/dashboard/"
        logger.info(f"[create_company_post] Navigating to admin dashboard: {admin_url}")
        
        await browser.navigate(admin_url)
        await human.page_load_delay()
        
        # Check if logged in
        current_url = await browser.get_current_url()
        logger.info(f"[create_company_post] Current URL: {current_url}")
        
        if "login" in current_url or "authwall" in current_url:
            return {
                "status": "error",
                "message": "Not logged in - please login first",
            }
        
        await human.delay(1000, 2000)
        
        # Step 1: Click the "Create" button in admin navigation
        logger.info("[create_company_post] Looking for Create button...")
        create_button = None
        create_button_selectors = [
            'button.org-organizational-page-admin-navigation__cta',
            'button:has-text("Create")',
            '.org-organizational-page-admin-navigation__ctas button',
        ]
        
        for selector in create_button_selectors:
            try:
                create_button = await browser.query_selector(selector)
                if create_button:
                    button_text = await create_button.inner_text()
                    if "Create" in button_text:
                        logger.info(f"[create_company_post] Found Create button: {selector}")
                        break
                    create_button = None
            except Exception:
                pass
        
        if not create_button:
            clicked = await _click_button_human_like(
                browser,
                human,
                selectors=create_button_selectors,
                text_candidates=['create'],
                scope_selector='main, [role="main"], .org-organizational-page-admin-navigation__ctas',
            )
            if not clicked:
                return {"status": "error", "message": "Could not find Create button on admin dashboard"}
            logger.info("[create_company_post] Clicked Create button via human fallback")
        else:
            await human.action_delay()
            clicked = await browser.click_element_human(create_button)
            if not clicked:
                return {"status": "error", "message": "Could not click Create button"}
            logger.info("[create_company_post] Clicked Create button")
        
        await human.delay(1000, 2000)
        
        # Step 2: Wait for modal and click "Start a post"
        logger.info("[create_company_post] Looking for 'Start a post' in modal...")
        
        # Wait for modal to appear
        try:
            await browser.wait_for_selector('[data-test-modal]', timeout=5000)
        except Exception:
            await browser.wait_for_selector('.artdeco-modal', timeout=5000)
        
        await human.delay(500, 1000)
        
        # Click "Start a post" link
        start_post_link = None
        start_post_selectors = [
            'a[data-test-org-menu-item="POSTS"]',
            'a#org-menu-POSTS',
            'a[href*="share=true"]',
        ]
        
        for selector in start_post_selectors:
            try:
                start_post_link = await browser.query_selector(selector)
                if start_post_link:
                    logger.info(f"[create_company_post] Found Start a post link: {selector}")
                    break
            except Exception:
                pass
        
        if not start_post_link:
            has_modal = await browser.safe_evaluate(
                """
                () => !!document.querySelector('[data-test-modal], .artdeco-modal')
                """,
                default=False,
            )
            if not has_modal:
                return {"status": "error", "message": "Create modal did not appear"}
            clicked = await _click_button_human_like(
                browser,
                human,
                selectors=start_post_selectors + ['[data-test-modal] a', '.artdeco-modal a'],
                text_candidates=['start a post'],
                scope_selector='[data-test-modal], .artdeco-modal',
            )
            if not clicked:
                return {"status": "error", "message": "Could not find 'Start a post' option in modal"}
            logger.info("[create_company_post] Clicked 'Start a post' via human fallback")
        else:
            await human.action_delay()
            clicked = await browser.click_element_human(start_post_link)
            if not clicked:
                return {"status": "error", "message": "Could not click 'Start a post' link"}
            logger.info("[create_company_post] Clicked 'Start a post' link")
        
        # The "Start a post" link navigates to a new page with share=true parameter
        # Wait for page navigation and share modal to appear
        logger.info("[create_company_post] Waiting for page navigation and share modal...")
        await human.delay(3000, 4000)
        
        # Wait for the share modal to appear on the new page
        try:
            await browser.wait_for_selector('.share-box-v2__modal, .share-box, .ql-editor', timeout=15000)
            logger.info("[create_company_post] Share modal appeared")
        except Exception as e:
            logger.warning(f"[create_company_post] Timeout waiting for share modal: {e}")
            # Try to check current URL
            current_url = await browser.get_current_url()
            logger.info(f"[create_company_post] Current URL after click: {current_url}")
        
        await human.delay(2000, 3000)
        
        # Step 4: Write content using desktop editor (Quill editor)
        logger.info("[create_company_post] Looking for text editor...")
        editor_selectors = [
            '.ql-editor[contenteditable="true"]',
            '.editor-content .ql-editor',
            'div[contenteditable="true"][data-placeholder]',
            'div[contenteditable="true"][aria-label*="editor"]',
            'div[contenteditable="true"][role="textbox"]',
        ]
        
        editor = None
        for selector in editor_selectors:
            try:
                # Wait for selector with timeout
                if await browser.wait_for_selector(selector, timeout=5000):
                    editor = await browser.query_selector(selector)
                    if editor:
                        logger.info(f"[create_company_post] Found editor: {selector}")
                        break
            except Exception:
                pass
        
        if not editor:
            # Log what's on the page for debugging
            current_url = await browser.get_current_url()
            logger.error(f"[create_company_post] Could not find editor. Current URL: {current_url}")
            return {"status": "error", "message": "Could not find post editor in share modal"}
        
        # Click to focus editor
        await human.action_delay()
        if not await browser.click_element_human(editor):
            return {"status": "error", "message": "Could not focus editor"}
        await human.delay(300, 500)
        
        # Step 5: Upload image if provided (before typing content)
        if image_path:
            logger.info(f"[create_company_post] Uploading image: {image_path}")
            
            try:
                # Desktop LinkedIn "Add media" button opens a native file chooser dialog
                # We must use expect_file_chooser to intercept it BEFORE clicking
                upload_success = await browser.upload_file_via_chooser(
                    'button[aria-label="Add media"]',
                    [image_path],
                    timeout=10000
                )
                
                if not upload_success:
                    logger.error("[create_company_post] Image upload via file chooser failed")
                    return {"status": "error", "message": "Image upload failed - could not set file in chooser"}
                
                logger.info("[create_company_post] Image file selected via chooser")
                await human.delay(2000, 3000)  # Wait for image to load in editor
                
                # After selecting image, LinkedIn shows an "Editor" modal with "Next" button
                # We need to click "Next" to proceed with the image upload
                logger.info("[create_company_post] Looking for Next button in Editor modal...")
                next_clicked = await _click_button_human_like(
                    browser,
                    human,
                    selectors=[
                        '[data-test-modal] button',
                        '.artdeco-modal button',
                        'button.artdeco-button--primary',
                    ],
                    text_candidates=['next'],
                    scope_selector='[data-test-modal], .artdeco-modal',
                )

                if next_clicked:
                    logger.info("[create_company_post] Clicked Next button in Editor modal")
                    await human.delay(3000, 4000)  # Wait for modal transition
                else:
                    logger.warning("[create_company_post] Next button not found, trying to continue...")
                
                # Wait for the share modal to return with image attached
                await human.delay(2000, 3000)
                
                # Verify image was uploaded by checking for preview or media container
                image_uploaded = await browser.evaluate("""
                    () => {
                        // Check for image preview in share modal
                        const modal = document.querySelector('.share-box-v2__modal, .share-box, .artdeco-modal');
                        if (!modal) return false;
                        
                        // Look for uploaded media indicators
                        const mediaContainer = modal.querySelector('.share-creation-state__media, .media-preview, [class*="media"]');
                        if (mediaContainer && mediaContainer.querySelector('img')) return true;
                        
                        // Check for any image that appeared after upload
                        const images = modal.querySelectorAll('img');
                        for (const img of images) {
                            const rect = img.getBoundingClientRect();
                            if (rect.width > 50 && rect.height > 50) return true;
                        }
                        
                        return false;
                    }
                """)
                
                if image_uploaded:
                    logger.info("[create_company_post] Image upload verified - preview found")
                else:
                    logger.warning("[create_company_post] Could not verify image upload, continuing anyway...")
                
            except Exception as e:
                logger.error(f"[create_company_post] Image upload failed: {e}")
                return {"status": "error", "message": f"Image upload failed: {e}"}
        
        # Step 6: Re-find editor (DOM may have changed after image upload) and set content
        logger.info("[create_company_post] Re-finding editor after image upload...")
        editor = None
        for selector in editor_selectors:
            try:
                editor = await browser.query_selector(selector)
                if editor:
                    logger.info(f"[create_company_post] Re-found editor: {selector}")
                    break
            except Exception:
                pass
        
        if not editor:
            return {"status": "error", "message": "Could not find editor after image upload"}
        
        # Click to focus editor
        await human.action_delay()
        if not await browser.click_element_human(editor):
            return {"status": "error", "message": "Could not focus editor after image upload"}
        await human.delay(300, 500)
        
        # Set post content via JavaScript (use innerText to avoid TrustedHTML CSP)
        await editor.evaluate("""(el, text) => {
            el.focus();
            el.innerText = text;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
        }""", content)
        logger.info(f"[create_company_post] Content set ({len(content)} chars)")
        
        await human.delay(1000, 2000)
        
        # Step 7: Click Post button
        logger.info("[create_company_post] Looking for Post button...")
        await human.delay(500, 1000)

        clicked = await _click_button_human_like(
            browser,
            human,
            selectors=[
                'button.share-actions__primary-action',
                '.share-box_actions button',
                'button.artdeco-button--primary',
            ],
            text_candidates=['post', 'publish'],
            scope_selector='[data-test-modal], .artdeco-modal, .share-box-v2__modal, .share-box_actions',
        )

        logger.info(f"[create_company_post] Post button click result: {'clicked' if clicked else 'not_found'}")

        if not clicked:
            return {"status": "error", "message": "Could not find Post button"}
        
        # Wait for post to be submitted
        await human.delay(3000, 5000)
        
        # Verify post was created
        current_url = await browser.get_current_url()
        logger.info(f"[create_company_post] After submit URL: {current_url}")
        
        # Save cookies after activity
        browser_cookies = await browser.get_cookies(["https://www.linkedin.com"])
        with get_db() as db:
            cookie_repo = CookieRepository(db)
            cookie_repo.set_from_playwright(session.profile_db_id, browser_cookies)
        
        return {
            "status": "ok",
            "profile_id": profile_id,
            "company_url": company_url,
            "message": "Company post created successfully",
            "content_preview": content[:200] + "..." if len(content) > 200 else content,
            "has_image": image_path is not None,
        }
        
    except Exception as e:
        logger.error(f"Failed to create company post: {e}")
        import traceback
        traceback.print_exc()
        return {
            "status": "error",
            "message": str(e),
        }
