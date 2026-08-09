"""Profile tools for LinkedIn MCP Server."""

import logging
from typing import Optional, List, Dict, Any
from urllib.parse import quote

from linkedin_mcp.browser.session import get_session_manager
from linkedin_mcp.browser.human import HumanBehavior
from linkedin_mcp.db import get_db
from linkedin_mcp.db.repository import ProfileRepository
from linkedin_mcp.tools.scrolling import jittered_safe_scroll_sequence

logger = logging.getLogger(__name__)


async def _detect_auth_wall(browser) -> Optional[str]:
    """Detect LinkedIn auth wall / sign-in overlays on the current page."""
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


async def get_profile(
    profile_id: str,
    linkedin_url: str,
    include_activity: bool = False,
    max_posts: int = 5,
) -> dict:
    """Get LinkedIn profile details.
    
    Args:
        profile_id: Profile UUID (your account)
        linkedin_url: URL of the LinkedIn profile to view
        include_activity: Whether to fetch recent posts and comments
        max_posts: Maximum number of recent posts to fetch
    
    Returns:
        Dict with profile information
    """
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
        
        # Navigate to profile
        await browser.navigate(linkedin_url)
        await human.page_load_delay()
        
        # Check if logged in
        current_url = await browser.get_current_url()
        logger.info(f"[get_profile] Current URL: {current_url}")
        
        if "login" in current_url or "authwall" in current_url:
            return {
                "status": "error",
                "message": "Not logged in - please login first",
            }
        
        # Detect layout type from URL first
        is_mobile_url = "mwlite" in current_url or "/m/" in current_url
        logger.info(f"[get_profile] Mobile URL detected: {is_mobile_url}")
        
        # Wait for profile to load - use different detection strategies
        profile_found = False
        layout_type = "mobile" if is_mobile_url else "desktop"
        
        if is_mobile_url:
            # Mobile-lite selectors
            profile_selectors = [
                ".basic-profile-section",
                "section.basic-profile-section",
                "#app-container .basic-profile-section",
            ]
            for selector in profile_selectors:
                logger.info(f"[get_profile] Trying mobile selector: {selector}")
                if await browser.wait_for_selector(selector, timeout=5000):
                    logger.info(f"[get_profile] Found mobile profile with selector: {selector}")
                    profile_found = True
                    layout_type = "mobile"
                    break
        else:
            # Desktop - new React UI uses different structure
            # Wait for main content area and profile name to appear
            desktop_selectors = [
                '[role="main"]',                    # New React UI main area
                '.pv-top-card',                     # Old desktop UI
                'main',                             # Generic main element
            ]
            for selector in desktop_selectors:
                logger.info(f"[get_profile] Trying desktop selector: {selector}")
                if await browser.wait_for_selector(selector, timeout=5000):
                    logger.info(f"[get_profile] Found element with selector: {selector}")
                    profile_found = True
                    break
            
            # Verify it's actually a profile page by checking for profile-specific content
            if profile_found:
                profile_check = await browser.evaluate("""
                    () => {
                        // Check for profile indicators in new React UI
                        const hasProfileTitle = document.title.includes('LinkedIn');
                        const hasProfileH2 = document.querySelector('h2');
                        const hasMessageBtn = document.querySelector('a[href*="messaging"], button[aria-label*="Message"]');
                        const hasFollowers = document.body.innerText.includes('followers') || 
                                            document.body.innerText.includes('connections');
                        
                        // Check for old desktop UI
                        const hasOldUI = document.querySelector('.pv-top-card') !== null;
                        
                        return {
                            hasProfileH2: hasProfileH2 !== null,
                            hasMessageBtn: hasMessageBtn !== null,
                            hasFollowers: hasFollowers,
                            hasOldUI: hasOldUI,
                            isProfile: (hasProfileH2 && hasFollowers) || hasOldUI
                        };
                    }
                """)
                logger.info(f"[get_profile] Profile check: {profile_check}")
                
                if profile_check and profile_check.get('isProfile'):
                    profile_found = True
                    if profile_check.get('hasOldUI'):
                        layout_type = "desktop_old"
                    else:
                        layout_type = "desktop"
                else:
                    profile_found = False
        
        if not profile_found:
            # Fallback: check page content
            logger.warning("[get_profile] Primary selectors failed, checking page content")
            page_html = await browser.get_page_content()
            if "basic-profile-section" in page_html:
                layout_type = "mobile"
                profile_found = True
                logger.info("[get_profile] Found mobile layout via HTML check")
            elif "pv-top-card" in page_html:
                layout_type = "desktop_old"
                profile_found = True
                logger.info("[get_profile] Found old desktop layout via HTML check")
            elif "followers" in page_html.lower() or "connections" in page_html.lower():
                layout_type = "desktop"
                profile_found = True
                logger.info("[get_profile] Found new desktop layout via content check")
        
        if not profile_found:
            return {
                "status": "error",
                "message": "Profile did not load",
            }
        
        logger.info(f"[get_profile] Using layout type: {layout_type}")
        
        # Scroll down to load all sections (About, Experience, etc.)
        await jittered_safe_scroll_sequence(
            browser,
            human,
            steps=3,
            base_pixels=800,
            delay_min_ms=500,
            delay_max_ms=800,
            on_navigation_delay_min_ms=1000,
            on_navigation_delay_max_ms=1500,
        )
        
        # Scroll back to top
        await browser.safe_scroll_to(0, 0)
        await human.delay(300, 500)
        
        # Extract profile data based on layout
        if layout_type == "mobile":
            profile_data = await _extract_mobile_profile_data(browser)
        else:
            profile_data = await _extract_profile_data(browser)
        
        # Fetch activity (posts and comments) if requested
        if include_activity:
            if layout_type == "mobile":
                # Mobile: navigate to activity URLs
                vanity_name = linkedin_url.rstrip('/').split('/in/')[-1].split('/')[0]
                
                posts_url = f"https://www.linkedin.com/mwlite/in/{vanity_name}/recent-activity/posts/"
                logger.info(f"[get_profile] Fetching mobile posts from: {posts_url}")
                await browser.navigate(posts_url)
                await human.page_load_delay()
                posts_data = await _extract_mobile_profile_activity(browser, max_posts, activity_type="posts")
                profile_data["recent_posts"] = posts_data.get("posts", [])
                
                comments_url = f"https://www.linkedin.com/mwlite/in/{vanity_name}/recent-activity/comments/"
                logger.info(f"[get_profile] Fetching mobile comments from: {comments_url}")
                await browser.navigate(comments_url)
                await human.page_load_delay()
                comments_data = await _extract_mobile_profile_activity(browser, max_posts, activity_type="comments")
                profile_data["recent_comments"] = comments_data.get("comments", [])
            else:
                # Desktop: posts are on profile page, comments need clicking tab
                # Extract posts from current profile page (already scrolled)
                logger.info("[get_profile] Extracting posts from profile page")
                posts_data = await _extract_desktop_activity_from_profile(browser, max_posts)
                profile_data["recent_posts"] = posts_data.get("posts", [])
                
                # Click Comments tab and extract comments
                logger.info("[get_profile] Clicking Comments tab for comments")
                comments_data = await _extract_desktop_comments(browser, max_posts)
                profile_data["recent_comments"] = comments_data.get("comments", [])
        
        return {
            "status": "ok",
            "profile_id": profile_id,
            "linkedin_url": linkedin_url,
            "data": profile_data,
        }
        
    except Exception as e:
        logger.error(f"Failed to get profile: {e}")
        return {
            "status": "error",
            "message": str(e),
        }


async def _extract_profile_data(browser) -> Dict[str, Any]:
    """Extract profile data from desktop page (new React UI)."""
    data = {}
    
    try:
        # Use JavaScript to extract all profile data at once from new React UI
        js_extract = """
        () => {
            const result = {};
            const mainContent = document.querySelector('[role="main"]') || document.body;
            
            // Name - find h2 within main content area (not in header/nav)
            // The profile name h2 is typically the first h2 in the main content
            const mainH2s = mainContent.querySelectorAll('h2');
            for (const h2 of mainH2s) {
                const text = h2.innerText.trim();
                // Skip notification badges, empty, or very short text
                if (text && text.length > 2 && text.length < 100 && 
                    !text.includes('notification') && !text.match(/^\\d+$/)) {
                    result.name = text;
                    break;
                }
            }
            
            // Headline - look for the professional headline
            // In new UI, it's often in a specific paragraph or div after the name
            const allParagraphs = mainContent.querySelectorAll('p');
            for (const p of allParagraphs) {
                const text = p.innerText.trim();
                // Headline characteristics: 20-300 chars, contains job-related content
                if (text.length > 20 && text.length < 300 && 
                    !text.includes('followers') && !text.includes('connections') &&
                    !text.includes('Contact info') && !text.includes('mutual') &&
                    !text.includes('celebrating') && !text.includes('years at')) {
                    // Check if it looks like a headline
                    if (text.includes('|') || text.includes('at ') || 
                        text.toLowerCase().includes('ceo') || text.toLowerCase().includes('founder') ||
                        text.toLowerCase().includes('director') || text.toLowerCase().includes('manager') ||
                        text.toLowerCase().includes('engineer') || text.toLowerCase().includes('developer') ||
                        text.toLowerCase().includes('consultant') || text.toLowerCase().includes('specialist') ||
                        text.toLowerCase().includes('enabling') || text.toLowerCase().includes('modernizing') ||
                        text.toLowerCase().includes('building') || text.toLowerCase().includes('leading')) {
                        result.headline = text;
                        break;
                    }
                }
            }
            
            // If no headline found with keywords, try first substantial paragraph
            if (!result.headline) {
                for (const p of allParagraphs) {
                    const text = p.innerText.trim();
                    if (text.length > 30 && text.length < 300 && 
                        !text.includes('followers') && !text.includes('connections') &&
                        !text.includes('celebrating') && !text.includes('years at') &&
                        !text.includes('Contact info')) {
                        result.headline = text;
                        break;
                    }
                }
            }
            
            // Location - look for location text near "Contact info" link
            const bodyText = mainContent.innerText;
            
            // Find the div containing "Contact info" link and look for sibling p with location
            const contactInfoLink = mainContent.querySelector('a[href*="contact-info"]');
            if (contactInfoLink) {
                // The location p is typically in the same parent div as the contact info link
                const parentDiv = contactInfoLink.closest('div');
                if (parentDiv) {
                    // Look for p elements in the same container
                    const siblingPs = parentDiv.querySelectorAll('p');
                    for (const p of siblingPs) {
                        const text = p.innerText.trim();
                        // Location pattern: contains comma, no "Contact info", reasonable length
                        if (text && text.includes(',') && text.length > 5 && text.length < 80 &&
                            !text.includes('Contact info') && !text.includes('·')) {
                            result.location = text;
                            break;
                        }
                    }
                }
            }
            
            // Fallback: regex pattern matching for location
            if (!result.location) {
                // Match "City, Region, Country" pattern followed by Contact info
                const locationMatch = bodyText.match(/([A-Z][a-zA-Z]+,\\s*[A-Z][a-zA-Z]+,\\s*[A-Z][a-zA-Z\\s]+?)\\s*·?\\s*Contact info/i);
                if (locationMatch) {
                    result.location = locationMatch[1].trim();
                }
            }
            
            // About section - look for expandable text or about content
            const aboutSection = mainContent.querySelector('section[id*="about"], div[id*="about"]');
            if (aboutSection) {
                const aboutText = aboutSection.innerText.trim();
                if (aboutText && aboutText.length > 20) {
                    result.about = aboutText;
                }
            }
            // Alternative: look for "About" heading and get following content
            if (!result.about) {
                const aboutHeadings = mainContent.querySelectorAll('h2, h3');
                for (const heading of aboutHeadings) {
                    if (heading.innerText.trim().toLowerCase() === 'about') {
                        const section = heading.closest('section');
                        if (section) {
                            const content = section.innerText.replace(/^About\\s*/i, '').trim();
                            if (content.length > 20) {
                                result.about = content;
                            }
                        }
                        break;
                    }
                }
            }
            
            // Followers/Connections count
            const followersMatch = bodyText.match(/(\\d[\\d,]*\\s*followers)/i);
            if (followersMatch) {
                result.followers = followersMatch[1];
            }
            const connectionsMatch = bodyText.match(/(\\d+\\+?\\s*connections)/i);
            if (connectionsMatch) {
                result.connections = connectionsMatch[1];
            }
            
            // Connection status - check for Message button (indicates connected)
            const isVisible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden') return false;
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            };
            const textOf = (el) => (
                (el?.getAttribute?.('aria-label') || '') + ' ' +
                (el?.getAttribute?.('title') || '') + ' ' +
                (el?.innerText || el?.textContent || '')
            ).trim().toLowerCase();
            const hasConnectIntent = (label) => {
                if (!label) return false;
                if (/\\bconnections?\\b/.test(label)) return false;
                if (label.includes('mutual connections')) return false;
                return /\\bconnect\\b/.test(label) || /\\binvite\\b/.test(label);
            };
            const topcardCandidates = Array.from(mainContent.querySelectorAll(
                'section[componentkey*="topcard" i], section[data-view-name*="top-card" i], section'
            ));
            const topcard = topcardCandidates.find((section) => {
                if (!isVisible(section)) return false;
                if (!section.querySelector('h1, h2')) return false;
                const nodes = Array.from(section.querySelectorAll('a, button, [role="button"]')).filter(isVisible);
                return nodes.some((node) => {
                    const label = textOf(node);
                    const href = (node.getAttribute('href') || '').toLowerCase();
                    return hasConnectIntent(label) ||
                        label.includes('pending') ||
                        label.includes('message') ||
                        href.includes('/messaging/compose/?profileurn=');
                });
            }) || null;
            const actionNodes = topcard
                ? Array.from(topcard.querySelectorAll('a, button, [role="button"]')).filter(isVisible)
                : [];
            const topcardText = topcard ? (topcard.innerText || '').toLowerCase() : '';
            const degreeMatch = topcardText.match(/\\b(1st|2nd|3rd)\\b/);
            const connectionDegree = degreeMatch ? degreeMatch[1] : '';
            if (connectionDegree) {
                result.connection_degree = connectionDegree;
            }
            const pendingBtn = actionNodes.find((node) => {
                const label = textOf(node);
                return label.includes('pending') || label.includes('invitation sent');
            });
            const connectBtn = actionNodes.find((node) => hasConnectIntent(textOf(node)));
            const removeConnectionBtn = actionNodes.find((node) => {
                const label = textOf(node);
                return label.includes('remove connection');
            });
            const messageBtn = actionNodes.find((node) => {
                const label = textOf(node);
                const href = (node.getAttribute('href') || '').toLowerCase();
                if (label.includes('send profile in a message')) return false;
                return label === 'message' ||
                    label.includes(' message') ||
                    href.includes('/messaging/compose/?profileurn=');
            });

            if (connectionDegree === '1st' || removeConnectionBtn) {
                result.connection_status = 'connected';
                result.connection_status_evidence = removeConnectionBtn ? 'remove_connection_action' : 'first_degree_badge';
            } else if (pendingBtn) {
                result.connection_status = 'pending';
                result.connection_status_evidence = 'pending_action';
            } else if (connectBtn) {
                result.connection_status = 'not_connected';
                result.connection_status_evidence = 'connect_action';
            } else if (connectionDegree === '2nd' || connectionDegree === '3rd') {
                result.connection_status = 'not_connected';
                result.connection_status_evidence = 'non_first_degree_badge';
            } else if (messageBtn) {
                result.connection_status = 'unknown';
                result.connection_status_evidence = 'message_action_without_connection_evidence';
            } else {
                result.connection_status = 'unknown';
                result.connection_status_evidence = 'no_topcard_connection_action';
            }
            
            // Current company - look for company links in main content
            const companyLinks = mainContent.querySelectorAll('a[href*="/company/"]');
            for (const link of companyLinks) {
                const companyText = link.innerText.trim();
                // Skip empty or very short/long text
                if (companyText && companyText.length > 2 && companyText.length < 100 &&
                    !companyText.includes('followers') && !companyText.includes('employees')) {
                    result.current_company = companyText;
                    let companyUrl = link.getAttribute('href');
                    if (companyUrl && !companyUrl.startsWith('http')) {
                        companyUrl = 'https://www.linkedin.com' + companyUrl;
                    }
                    result.company_linkedin_url = companyUrl.split('?')[0];
                    break;
                }
            }
            
            // Current role - look for role/title text
            // Often appears as "Title at Company" pattern
            const roleMatch = bodyText.match(/([A-Z][^\\n]{5,60})\\s+at\\s+([A-Z][^\\n]{2,50})/);
            if (roleMatch && roleMatch[1]) {
                const role = roleMatch[1].trim();
                if (!role.includes('celebrating') && !role.includes('years') && 
                    !role.includes('Modernizing') && role.length < 60) {
                    result.current_role = role;
                }
            }
            
            return result;
        }
        """
        
        extracted = await browser.evaluate(js_extract)
        if extracted:
            data.update(extracted)
        
        # Try old desktop UI selectors as fallback
        if not data.get('name'):
            name_elem = await browser.query_selector("h1.text-heading-xlarge")
            if name_elem:
                data["name"] = await name_elem.inner_text()
        
        if not data.get('headline'):
            headline_elem = await browser.query_selector(".text-body-medium.break-words")
            if headline_elem:
                data["headline"] = await headline_elem.inner_text()
        
    except Exception as e:
        logger.error(f"Failed to extract profile data: {e}")
    
    return data


async def _extract_mobile_profile_data(browser) -> Dict[str, Any]:
    """Extract profile data from mobile-lite page using JavaScript for reliability."""
    data = {}
    
    try:
        # Use JavaScript to extract all profile data at once
        js_extract = """
        () => {
            const result = {};
            const profileSection = document.querySelector('.basic-profile-section');
            if (!profileSection) return result;
            
            // Name - h1 in basic-profile-section
            const h1 = profileSection.querySelector('h1');
            if (h1) result.name = h1.innerText.trim();
            
            // Headline - span with empty/no class that has substantial text
            const allSpans = profileSection.querySelectorAll('span');
            for (const span of allSpans) {
                if (span.closest('.ellipsis-menu')) continue;
                if (span.closest('.collapsible-dropdown')) continue;
                if (span.closest('ul[role="menu"]')) continue;
                if (span.closest('.profile-action-container')) continue;
                
                const text = span.innerText.trim();
                const className = span.className.trim();
                
                if (text.length > 20 && (className === '' || className.length < 10)) {
                    if (text.includes('connections') || text.includes('Joined') || text.includes('Contact')) continue;
                    result.headline = text;
                    break;
                }
            }
            
            // Location - div with class 'body-small text-color-text-low-emphasis' with direct text
            const locDivs = profileSection.querySelectorAll('div.body-small.text-color-text-low-emphasis');
            for (const div of locDivs) {
                let directText = '';
                for (const node of div.childNodes) {
                    if (node.nodeType === 3) {
                        directText += node.textContent.trim();
                    }
                }
                if (directText && directText.length > 3) {
                    result.location = directText;
                    break;
                }
            }
            
            // Current company - span with class 'member-current-company'
            const companySpan = profileSection.querySelector('span.member-current-company');
            if (companySpan) {
                result.current_company = companySpan.innerText.trim();
                
                // Try to get company LinkedIn URL from the link
                const companyLink = companySpan.closest('a') || companySpan.querySelector('a') || 
                                   profileSection.querySelector('a[href*="/company/"]');
                if (companyLink) {
                    let companyUrl = companyLink.getAttribute('href');
                    if (companyUrl && companyUrl.includes('/company/')) {
                        if (!companyUrl.startsWith('http')) {
                            companyUrl = 'https://www.linkedin.com' + companyUrl;
                        }
                        // Clean up URL - remove query params
                        companyUrl = companyUrl.split('?')[0];
                        result.company_linkedin_url = companyUrl;
                    }
                }
            }
            
            // Connections count
            const connSpan = profileSection.querySelector('span.whitespace-nowrap');
            if (connSpan && connSpan.innerText.includes('connections')) {
                result.connections = connSpan.innerText.trim();
            }
            
            // Connection status
            const inviteSent = profileSection.querySelector('.invite-sent-msg:not(.hidden)');
            const unfollowLi = document.querySelector('li[aria-label^="Unfollow"]');
            const followLi = document.querySelector('li[aria-label^="Follow"]');
            const connectBtn = profileSection.querySelector('button[data-action="connect-btn"]');
            const removeConnLi = document.querySelector('li[aria-label="Remove Connection"]');
            
            if (removeConnLi) {
                result.connection_status = 'connected';
            } else if (inviteSent && inviteSent.offsetParent !== null) {
                result.connection_status = 'pending';
            } else if (unfollowLi) {
                result.connection_status = 'following';
            } else if (followLi || connectBtn) {
                result.connection_status = 'not_connected';
            } else {
                result.connection_status = 'unknown';
            }
            
            // Profile picture
            const img = document.querySelector('#profile-picture-container img');
            if (img) {
                const url = img.getAttribute('data-delayed-url') || img.getAttribute('src');
                if (url && !url.includes('ghost')) {
                    result.profile_picture = url;
                }
            }
            
            // About/Bio section - try multiple selectors
            let aboutText = null;
            
            // Try section with id containing 'about'
            const aboutSection = document.querySelector('section#about-section, section[id*="about"], #about-section');
            if (aboutSection) {
                const aboutContent = aboutSection.querySelector('.show-more-content, .break-words, p, .text-color-text');
                if (aboutContent) {
                    aboutText = aboutContent.innerText.trim();
                }
            }
            
            // Fallback: look for "About" heading and get next sibling content
            if (!aboutText) {
                const aboutHeadings = document.querySelectorAll('h2, h3, .section-title');
                for (const heading of aboutHeadings) {
                    if (heading.innerText.toLowerCase().includes('about')) {
                        const parent = heading.closest('section') || heading.parentElement;
                        if (parent) {
                            const content = parent.querySelector('.show-more-content, .break-words, p');
                            if (content) {
                                aboutText = content.innerText.trim();
                                break;
                            }
                        }
                    }
                }
            }
            
            // Fallback: look for summary/bio class
            if (!aboutText) {
                const summaryEl = document.querySelector('.summary, .bio, [class*="summary"], [class*="bio"]');
                if (summaryEl) {
                    aboutText = summaryEl.innerText.trim();
                }
            }
            
            if (aboutText && aboutText.length > 20) {
                result.about = aboutText;
            }
            
            // Experience section - get all experiences
            const expSection = document.querySelector('section#experience-section, section[id*="experience"]');
            if (expSection) {
                const experiences = [];
                const expItems = expSection.querySelectorAll('.entity-card, .experience-item, [data-test-id*="experience"]');
                
                for (const item of expItems) {
                    const exp = {};
                    
                    // Role/Title
                    const roleEl = item.querySelector('.text-md.font-bold, h3, .experience-title');
                    if (roleEl) exp.title = roleEl.innerText.trim();
                    
                    // Company
                    const companyEl = item.querySelector('.text-sm, .experience-company');
                    if (companyEl) exp.company = companyEl.innerText.trim();
                    
                    // Company LinkedIn URL - look for link to company page
                    const companyLink = item.querySelector('a[href*="/company/"]');
                    if (companyLink) {
                        let companyUrl = companyLink.getAttribute('href');
                        if (companyUrl) {
                            if (!companyUrl.startsWith('http')) {
                                companyUrl = 'https://www.linkedin.com' + companyUrl;
                            }
                            companyUrl = companyUrl.split('?')[0];
                            exp.company_linkedin_url = companyUrl;
                        }
                    }
                    
                    // Duration
                    const durationEl = item.querySelector('.text-color-text-low-emphasis, .experience-duration');
                    if (durationEl) exp.duration = durationEl.innerText.trim();
                    
                    if (exp.title || exp.company) {
                        experiences.push(exp);
                    }
                }
                
                if (experiences.length > 0) {
                    result.experiences = experiences;
                    result.current_role = experiences[0].title;
                    if (!result.current_company && experiences[0].company) {
                        result.current_company = experiences[0].company;
                    }
                    // Set company_linkedin_url from first experience if not already set
                    if (!result.company_linkedin_url && experiences[0].company_linkedin_url) {
                        result.company_linkedin_url = experiences[0].company_linkedin_url;
                    }
                }
            }
            
            // Also try to find company URL from any company link on the page
            if (!result.company_linkedin_url) {
                const anyCompanyLink = document.querySelector('a[href*="/company/"]');
                if (anyCompanyLink) {
                    let companyUrl = anyCompanyLink.getAttribute('href');
                    if (companyUrl) {
                        if (!companyUrl.startsWith('http')) {
                            companyUrl = 'https://www.linkedin.com' + companyUrl;
                        }
                        companyUrl = companyUrl.split('?')[0];
                        result.company_linkedin_url = companyUrl;
                    }
                }
            }
            
            // Education section
            const eduSection = document.querySelector('section#education-section, section[id*="education"]');
            if (eduSection) {
                const education = [];
                const eduItems = eduSection.querySelectorAll('.entity-card, .education-item');
                
                for (const item of eduItems) {
                    const edu = {};
                    
                    const schoolEl = item.querySelector('.text-md.font-bold, h3');
                    if (schoolEl) edu.school = schoolEl.innerText.trim();
                    
                    const degreeEl = item.querySelector('.text-sm');
                    if (degreeEl) edu.degree = degreeEl.innerText.trim();
                    
                    const yearsEl = item.querySelector('.text-color-text-low-emphasis');
                    if (yearsEl) edu.years = yearsEl.innerText.trim();
                    
                    if (edu.school) {
                        education.push(edu);
                    }
                }
                
                if (education.length > 0) {
                    result.education = education;
                }
            }
            
            // Skills section
            const skillsSection = document.querySelector('section#skills-section, section[id*="skills"]');
            if (skillsSection) {
                const skills = [];
                const skillItems = skillsSection.querySelectorAll('.skill-item, .entity-card');
                
                for (const item of skillItems) {
                    const skillName = item.querySelector('.text-md, h3');
                    if (skillName) {
                        skills.push(skillName.innerText.trim());
                    }
                }
                
                if (skills.length > 0) {
                    result.skills = skills;
                }
            }
            
            return result;
        }
        """
        
        extracted = await browser.evaluate(js_extract)
        if extracted:
            data.update(extracted)
            logger.info(f"[mobile_profile] Extracted via JS: {list(data.keys())}")
        
    except Exception as e:
        logger.error(f"Failed to extract mobile profile data: {e}")
        import traceback
        logger.error(traceback.format_exc())
    
    return data


async def _extract_mobile_profile_activity(browser, max_posts: int = 5, activity_type: str = "posts") -> Dict[str, Any]:
    """Extract recent posts or comments from mobile activity page."""
    result = {"posts": [], "comments": []}
    human = HumanBehavior()
    
    try:
        import asyncio
        await asyncio.sleep(2)  # Give page time to load
        
        # Mobile activity page selectors
        selectors_to_try = [
            '.feed-container',
            '.activity-feed',
            '#app-container',
            'main',
        ]
        
        for selector in selectors_to_try:
            if await browser.wait_for_selector(selector, timeout=3000):
                logger.info(f"[mobile_activity] Found content with selector: {selector}")
                break
        
        # Scroll to load content
        await jittered_safe_scroll_sequence(
            browser,
            human,
            steps=2,
            base_pixels=400,
            delay_min_ms=450,
            delay_max_ms=650,
            on_navigation_delay_min_ms=700,
            on_navigation_delay_max_ms=1200,
        )
        
        # Extract activity using JavaScript
        js_extract = f"""
        () => {{
            const items = [];
            const maxItems = {max_posts};
            const activityType = '{activity_type}';
            
            // Mobile activity items
            const feedItems = document.querySelectorAll('.feed-item, .activity-item, article, [data-urn]');
            const processedUrns = new Set();
            
            for (const item of feedItems) {{
                if (items.length >= maxItems) break;

                // Expand truncated text when possible
                const expandControls = item.querySelectorAll('button, span[role="button"], a[role="button"]');
                for (const control of expandControls) {{
                    const label = (control.innerText || control.getAttribute('aria-label') || '').trim().toLowerCase();
                    if (!label) continue;
                    if (label === 'more' || label === 'see more' || label.endsWith('...more') || label.endsWith('…more')) {{
                        try {{
                            control.click();
                        }} catch (_err) {{}}
                    }}
                }}
                
                // Get post URN or URL
                const urn = item.getAttribute('data-urn') || '';
                if (urn && processedUrns.has(urn)) continue;
                if (urn) processedUrns.add(urn);
                
                // Find post link
                const postLink = item.querySelector('a[href*="/feed/update/"], a[href*="/posts/"]');
                let postUrl = postLink ? postLink.getAttribute('href') : '';
                if (postUrl && !postUrl.startsWith('http')) {{
                    postUrl = 'https://www.linkedin.com' + postUrl;
                }}
                
                // Extract content
                const contentEl = item.querySelector('.feed-shared-text, .update-content, p, .break-words');
                const content = contentEl ? contentEl.innerText.trim() : '';
                
                // Extract timestamp
                const timeEl = item.querySelector('time, .feed-shared-actor__sub-description, .timestamp');
                const timestamp = timeEl ? timeEl.innerText.trim() : '';
                
                // Extract engagement
                const fullText = item.innerText || '';
                let likes = '';
                let commentsCount = '';
                
                const likesMatch = fullText.match(/(\\d[\\d,]*) (reaction|like)/i);
                if (likesMatch) likes = likesMatch[1];
                
                const commentsMatch = fullText.match(/(\\d[\\d,]*) comment/i);
                if (commentsMatch) commentsCount = commentsMatch[1];
                
                if (content || postUrl) {{
                    items.push({{
                        content: content,
                        timestamp: timestamp,
                        likes: likes,
                        comments: commentsCount,
                        url: postUrl
                    }});
                }}
            }}
            
            if (activityType === 'posts') {{
                return {{ posts: items, comments: [] }};
            }} else {{
                return {{ posts: [], comments: items }};
            }}
        }}
        """
        
        extracted = await browser.evaluate(js_extract)
        if extracted:
            result["posts"] = extracted.get("posts", [])
            result["comments"] = extracted.get("comments", [])
            logger.info(f"[mobile_activity] Extracted {len(result['posts'])} posts, {len(result['comments'])} comments")
        
    except Exception as e:
        logger.error(f"Failed to extract mobile profile activity: {e}")
        import traceback
        logger.error(traceback.format_exc())
    
    return result


async def _extract_desktop_activity_from_profile(browser, max_posts: int = 5) -> Dict[str, Any]:
    """Extract recent posts from the profile page Activity section (desktop)."""
    result = {"posts": []}
    
    try:
        import asyncio
        
        # Posts are in a carousel structure on the profile page
        js_extract = f"""
        () => {{
            const items = [];
            const maxItems = {max_posts};
            const processedUrls = new Set();
            
            const cleanText = (value) => (value || '').replace(/\s+/g, ' ').trim();

            // Find carousel items - each post is in a carousel child container
            const carouselItems = document.querySelectorAll('li[data-testid="carousel-child-container"], li[role="listitem"]');
            
            for (const item of carouselItems) {{
                if (items.length >= maxItems) break;

                // Expand truncated text when possible
                const expandControls = item.querySelectorAll('button, span[role="button"], a[role="button"]');
                for (const control of expandControls) {{
                    const label = cleanText(control.innerText || control.getAttribute('aria-label') || '').toLowerCase();
                    if (!label) continue;
                    if (label === 'more' || label === 'see more' || label.endsWith('...more') || label.endsWith('…more')) {{
                        try {{
                            control.click();
                        }} catch (_err) {{}}
                    }}
                }}
                
                // Find the post URL - prefer direct activity links
                const postLink = item.querySelector('a[href*="/feed/update/urn:li:activity:"]') ||
                                 item.querySelector('a[href*="/feed/update/"]');
                if (!postLink) continue;
                
                let postUrl = postLink.getAttribute('href');
                if (!postUrl) continue;
                
                // Normalize URL - remove tracking params
                if (!postUrl.startsWith('http')) {{
                    postUrl = 'https://www.linkedin.com' + postUrl;
                }}
                postUrl = postUrl.split('?')[0];
                
                // Skip duplicates
                if (processedUrls.has(postUrl)) continue;
                processedUrls.add(postUrl);
                
                // Extract post content from the expandable text box using robust selectors
                let content = '';
                const textCandidates = [
                    item.querySelector('[data-testid="expandable-text-box"]'),
                    item.querySelector('p [data-testid="expandable-text-box"]'),
                    item.querySelector('a[href*="/feed/update/"] [data-testid="expandable-text-box"]'),
                ];

                for (const candidate of textCandidates) {{
                    if (!candidate) continue;
                    const candidateText = cleanText(candidate.innerText)
                        .replace(/…\\s*more$/i, '')
                        .trim();
                    if (candidateText && candidateText.length > 10) {{
                        content = candidateText;
                        break;
                    }}
                }}

                // Fallback: find the longest meaningful paragraph inside this activity card
                if (!content) {{
                    const paragraphs = Array.from(item.querySelectorAll('p'));
                    let best = '';
                    for (const p of paragraphs) {{
                        const txt = cleanText(p.innerText)
                            .replace(/…\\s*more$/i, '')
                            .trim();
                        if (!txt) continue;
                        if (/^(like|comment|repost|send|show all)$/i.test(txt)) continue;
                        if (txt.length > best.length) best = txt;
                    }}
                    content = best;
                }}

                content = cleanText(content);

                // Skip cards with no meaningful text content
                if (!content || content.length < 8) continue;
                
                // Extract timestamp (e.g., "4h", "1d", "5d")
                let timestamp = '';
                const allText = item.innerText || '';
                const timeMatch = allText.match(/(\\d+[hdwmy])\\s*•/);
                if (timeMatch) {{
                    timestamp = timeMatch[1];
                }}
                
                // Extract likes count
                let likes = '';
                const likesMatch = allText.match(/(?:and\\s+)?(\\d[\\d,]*)\\s+(?:others?\\s+)?reacted/i) ||
                                  allText.match(/(\\d[\\d,]*)\\s+reactions?/i) ||
                                  allText.match(/(\\d[\\d,]*)\\s+likes?/i);
                if (likesMatch) likes = likesMatch[1];
                
                // Extract comments count
                let comments = '';
                const commentsMatch = allText.match(/(\\d[\\d,]*)\\s+comments?/i);
                if (commentsMatch) comments = commentsMatch[1];
                
                items.push({{
                    content: content,
                    timestamp: timestamp,
                    url: postUrl,
                    likes: likes,
                    comments: comments
                }});
            }}
            
            return {{ posts: items }};
        }}
        """
        
        extracted = await browser.evaluate(js_extract)
        if extracted:
            result["posts"] = extracted.get("posts", [])
            logger.info(f"[desktop_activity] Extracted {len(result['posts'])} posts from profile page")
        
    except Exception as e:
        logger.error(f"Failed to extract desktop activity from profile: {e}")
        import traceback
        logger.error(traceback.format_exc())
    
    return result


async def _extract_desktop_comments(browser, max_posts: int = 5) -> Dict[str, Any]:
    """Extract recent comments from the profile page Activity section (desktop).
    
    Need to click the Comments radio button to load comments.
    """
    result = {"comments": []}
    
    try:
        import asyncio
        
        # First, click the Comments radio button to load comments
        clicked = await browser.evaluate("""
        () => {
            // Find the Comments radio button by looking for label with text "Comments"
            const labels = document.querySelectorAll('label');
            for (const label of labels) {
                if (label.innerText.trim() === 'Comments') {
                    label.click();
                    return true;
                }
            }
            
            // Try clicking the radio div directly
            const radios = document.querySelectorAll('[role="radio"]');
            for (const radio of radios) {
                const labelInside = radio.querySelector('label');
                if (labelInside && labelInside.innerText.trim() === 'Comments') {
                    radio.click();
                    return true;
                }
            }
            
            return false;
        }
        """)
        
        if clicked:
            logger.info("[desktop_comments] Clicked Comments tab, waiting for content to load")
            await asyncio.sleep(1.5)  # Wait for comments to load
        else:
            logger.warning("[desktop_comments] Could not find Comments tab to click")
        
        # Now extract comments
        js_extract = f"""
        () => {{
            const items = [];
            const maxItems = {max_posts};
            const processedUrls = new Set();
            
            // Find the comments section - componentkey contains "comments_pill" (case insensitive search)
            let commentsSection = null;
            const allElements = document.querySelectorAll('[componentkey]');
            for (const el of allElements) {{
                const key = el.getAttribute('componentkey') || '';
                if (key.toLowerCase().includes('comments_pill')) {{
                    commentsSection = el;
                    break;
                }}
            }}
            
            if (!commentsSection) {{
                // Fallback: find links with dashCommentUrn anywhere on page
                const allCommentLinks = document.querySelectorAll('a[href*="dashCommentUrn"]');
                if (allCommentLinks.length === 0) {{
                    return {{ comments: [], debug: 'No comments section or comment links found' }};
                }}
                // Use the parent of the first comment link as the section
                commentsSection = allCommentLinks[0].closest('div');
            }}
            
            // Find all comment links with dashCommentUrn
            const commentLinks = commentsSection.querySelectorAll('a[href*="dashCommentUrn"]');
            
            // If no links in section, try finding them in the whole page
            const linksToProcess = commentLinks.length > 0 ? commentLinks : document.querySelectorAll('a[href*="dashCommentUrn"]');
            
            for (const link of linksToProcess) {{
                if (items.length >= maxItems) break;
                
                let commentUrl = link.getAttribute('href');
                if (!commentUrl) continue;
                
                // Normalize URL
                if (!commentUrl.startsWith('http')) {{
                    commentUrl = 'https://www.linkedin.com' + commentUrl;
                }}
                
                // Skip duplicates based on comment URN
                const urnMatch = commentUrl.match(/dashCommentUrn=([^&]+)/);
                const urlKey = urnMatch ? urnMatch[1] : commentUrl;
                if (processedUrls.has(urlKey)) continue;
                processedUrls.add(urlKey);
                
                // The link itself contains the comment info
                const linkText = link.innerText || '';
                
                // Extract timestamp (e.g., "3h", "4h", "11h") - appears after bullet
                let timestamp = '';
                const timeMatch = linkText.match(/•\\s*(\\d+[hdwmy])/);
                if (timeMatch) {{
                    timestamp = timeMatch[1];
                }} else {{
                    // Try standalone time format
                    const standaloneTime = linkText.match(/(\\d+[hdwmy])\\s*$/m);
                    if (standaloneTime) timestamp = standaloneTime[1];
                }}
                
                // Extract comment content - it's the text after "commented on a post" line
                // Structure: "Name commented on a post • 3h" then the actual comment text
                let content = '';
                const lines = linkText.split('\\n').map(l => l.trim()).filter(l => l);
                
                for (let i = 0; i < lines.length; i++) {{
                    const line = lines[i];
                    // Skip metadata lines
                    if (line.includes('commented on a post') || 
                        line.match(/^\\d+[hdwmy]$/) ||
                        line === '•') {{
                        continue;
                    }}
                    // The comment content is usually the last substantial line
                    if (line.length > 5) {{
                        content = line;
                    }}
                }}
                
                items.push({{
                    content: content,
                    timestamp: timestamp,
                    url: commentUrl
                }});
            }}
            
            return {{ comments: items, debug: 'Found ' + linksToProcess.length + ' comment links' }};
        }}
        """
        
        extracted = await browser.evaluate(js_extract)
        if extracted:
            result["comments"] = extracted.get("comments", [])
            logger.info(f"[desktop_comments] Extracted {len(result['comments'])} comments")
            if extracted.get("debug"):
                logger.debug(f"[desktop_comments] Debug: {extracted['debug']}")
        
    except Exception as e:
        logger.error(f"Failed to extract desktop comments: {e}")
        import traceback
        logger.error(traceback.format_exc())
    
    return result


async def _extract_profile_activity(browser, max_posts: int = 5, activity_type: str = "posts") -> Dict[str, Any]:
    """Extract recent posts or comments from profile activity page (legacy/fallback)."""
    result = {"posts": [], "comments": []}
    human = HumanBehavior()
    
    try:
        # Wait for page to load - try multiple selectors
        import asyncio
        await asyncio.sleep(2)  # Give page time to load
        
        # Try to wait for any content indicator
        selectors_to_try = [
            '[role="main"]',
            'main',
            '.scaffold-layout__main',
            'section',
            'div[data-finite-scroll-hotkey-context]'
        ]
        
        feed_loaded = False
        for selector in selectors_to_try:
            if await browser.wait_for_selector(selector, timeout=3000):
                feed_loaded = True
                logger.info(f"[profile_activity] Found content with selector: {selector}")
                break
        
        if not feed_loaded:
            # Still try to extract - page might have loaded differently
            logger.warning("[profile_activity] No standard selector found, attempting extraction anyway")
        
        # Scroll to load content
        await jittered_safe_scroll_sequence(
            browser,
            human,
            steps=3,
            base_pixels=500,
            delay_min_ms=700,
            delay_max_ms=900,
            on_navigation_delay_min_ms=900,
            on_navigation_delay_max_ms=1400,
        )
        
        # Scroll back up
        await browser.safe_scroll_to(0, 0)
        await asyncio.sleep(0.5)
        
        # Use JavaScript to extract activity items from new React UI
        js_extract = f"""
        () => {{
            const items = [];
            const maxItems = {max_posts};
            const activityType = '{activity_type}';
            
            const mainContent = document.querySelector('[role="main"]') || document.body;
            const processedUrls = new Set();
            
            // Find all links to posts/updates
            const allLinks = mainContent.querySelectorAll('a[href*="/feed/update/"], a[href*="/posts/"]');
            
            for (const link of allLinks) {{
                if (items.length >= maxItems) break;
                
                let postUrl = link.getAttribute('href');
                if (!postUrl) continue;
                
                // Normalize URL
                if (!postUrl.startsWith('http')) {{
                    postUrl = 'https://www.linkedin.com' + postUrl;
                }}
                postUrl = postUrl.split('?')[0];
                
                // Skip if already processed
                if (processedUrls.has(postUrl)) continue;
                processedUrls.add(postUrl);
                
                // Find the parent container - walk up to find substantial content
                let container = link;
                for (let i = 0; i < 10 && container; i++) {{
                    container = container.parentElement;
                    if (!container) break;
                    const text = container.innerText || '';
                    // Look for a container with substantial content
                    if (text.length > 200 && (
                        container.tagName === 'SECTION' || 
                        container.tagName === 'ARTICLE' ||
                        container.classList.length > 3
                    )) {{
                        break;
                    }}
                }}
                
                if (!container) continue;
                
                const fullText = container.innerText || '';
                
                // Extract content - find the main text block
                let content = '';
                const textElements = container.querySelectorAll('p, span, div');
                for (const el of textElements) {{
                    const text = el.innerText.trim();
                    // Look for substantial text that's actual content
                    if (text.length > 80 && text.length < 3000) {{
                        // Skip metadata-like text
                        if (text.includes('followers') || text.includes('reactions') ||
                            text.includes(' comments') || text.includes('reposts') ||
                            text.includes('Like') || text.includes('Comment') ||
                            text.includes('Repost') || text.includes('Send')) {{
                            continue;
                        }}
                        content = text;
                        break;
                    }}
                }}
                
                // Extract timestamp
                let timestamp = '';
                const timeMatch = fullText.match(/(\\d+[hdwmy]|\\d+ (hour|day|week|month|year)s? ago|yesterday|today|just now)/i);
                if (timeMatch) {{
                    timestamp = timeMatch[0];
                }}
                
                // Extract engagement counts
                let likes = '';
                let commentsCount = '';
                let reposts = '';
                
                const likesMatch = fullText.match(/(\\d[\\d,]*) (reaction|like)/i);
                if (likesMatch) likes = likesMatch[1];
                
                const commentsMatch = fullText.match(/(\\d[\\d,]*) comment/i);
                if (commentsMatch) commentsCount = commentsMatch[1];
                
                const repostsMatch = fullText.match(/(\\d[\\d,]*) repost/i);
                if (repostsMatch) reposts = repostsMatch[1];
                
                if (content || postUrl) {{
                    items.push({{
                        content: content,
                        timestamp: timestamp,
                        likes: likes,
                        comments: commentsCount,
                        reposts: reposts,
                        url: postUrl
                    }});
                }}
            }}
            
            if (activityType === 'posts') {{
                return {{ posts: items, comments: [] }};
            }} else {{
                return {{ posts: [], comments: items }};
            }}
        }}
        """
        
        # Log current URL for debugging
        current_url = await browser.get_current_url()
        logger.info(f"[profile_activity] Current URL: {current_url}")
        
        # Debug: check what's on the page
        debug_info = await browser.evaluate("""
        () => {
            const main = document.querySelector('[role="main"]');
            const body = document.body;
            const links = document.querySelectorAll('a[href*="/feed/update/"], a[href*="/posts/"]');
            return {
                hasMain: !!main,
                bodyLength: body ? body.innerText.length : 0,
                linkCount: links.length,
                pageTitle: document.title,
                sampleLinks: Array.from(links).slice(0, 3).map(l => l.href)
            };
        }
        """)
        logger.info(f"[profile_activity] Debug info: {debug_info}")
        
        extracted = await browser.evaluate(js_extract)
        if extracted:
            result["posts"] = extracted.get("posts", [])
            result["comments"] = extracted.get("comments", [])
            logger.info(f"[profile_activity] Extracted {len(result['posts'])} posts, {len(result['comments'])} comments")
        
    except Exception as e:
        logger.error(f"Failed to extract profile activity: {e}")
        import traceback
        logger.error(traceback.format_exc())
    
    return result


# Country URN mapping for LinkedIn search
COUNTRY_URN_MAP = {
    "US": "103644278",
    "USA": "103644278",
    "AE": "104305776",
    "UAE": "104305776",
    "SA": "100459316",
    "SAU": "100459316",
    "GB": "101165590",
    "GBR": "101165590",
    "UK": "101165590",
    "DE": "101282230",
    "FR": "105015875",
    "IN": "102713980",
    "CA": "101174742",
    "AU": "101452733",
}


async def search_people(
    profile_id: str,
    keywords: str,
    country: Optional[str] = None,
    connection_degree: Optional[List[str]] = None,
    page: int = 1,
    max_results: int = 10,
) -> dict:
    """Search for people on LinkedIn.
    
    Args:
        profile_id: Profile UUID (your account)
        keywords: Search keywords
        country: Country code to filter by (e.g., "US", "AE")
        connection_degree: List of connection degrees ["2", "3"]
        page: Page number for pagination
        max_results: Maximum results to return
    
    Returns:
        Dict with search results
    """
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
        
        # Build search URL
        search_url = _build_search_url(keywords, country, connection_degree, page)
        
        # Navigate to search
        await browser.navigate(search_url)
        await human.page_load_delay()
        
        # Check if logged in
        current_url = await browser.get_current_url()
        if "login" in current_url or "authwall" in current_url:
            return {
                "status": "error",
                "message": "Not logged in - please login first",
            }
        
        # Wait for results
        if not await browser.wait_for_selector(".search-results-container", timeout=10000):
            return {
                "status": "error",
                "message": "Search results did not load",
            }
        
        # Extract results
        results = await _extract_search_results(browser, max_results)
        
        # Save cookies after activity
        browser_cookies = await browser.get_cookies(["https://www.linkedin.com"])
        with get_db() as db:
            cookie_repo = CookieRepository(db)
            cookie_repo.set_from_playwright(session.profile_db_id, browser_cookies)
        
        return {
            "status": "ok",
            "profile_id": profile_id,
            "keywords": keywords,
            "page": page,
            "result_count": len(results),
            "results": results,
        }
        
    except Exception as e:
        logger.error(f"Failed to search people: {e}")
        return {
            "status": "error",
            "message": str(e),
        }


def _build_search_url(
    keywords: str,
    country: Optional[str],
    connection_degree: Optional[List[str]],
    page: int,
) -> str:
    """Build LinkedIn people search URL."""
    base_url = "https://www.linkedin.com/search/results/people/"
    
    params = [f"keywords={quote(keywords)}"]
    
    # Country filter
    if country and country.upper() in COUNTRY_URN_MAP:
        geo_urn = COUNTRY_URN_MAP[country.upper()]
        params.append(f"geoUrn=%5B{geo_urn}%5D")
    
    # Connection degree filter
    if connection_degree:
        connection_map = {"2": "S", "3": "O"}
        network = [connection_map.get(d, d) for d in connection_degree if d in connection_map]
        if network:
            network_str = "%2C".join(f'"{n}"' for n in network)
            params.append(f"network=%5B{network_str}%5D")
    
    params.append("origin=FACETED_SEARCH")
    
    if page > 1:
        params.append(f"page={page}")
    
    return f"{base_url}?{'&'.join(params)}"


async def _extract_search_results(browser, max_results: int) -> List[Dict[str, Any]]:
    """Extract search results from current page."""
    results = []
    
    try:
        # Get all result items
        result_elements = await browser.query_selector_all(".reusable-search__result-container")
        
        for element in result_elements[:max_results]:
            try:
                result = {}
                
                # Name and URL
                name_link = await element.query_selector(".entity-result__title-text a")
                if name_link:
                    result["name"] = await name_link.inner_text()
                    result["url"] = await name_link.get_attribute("href")
                
                # Headline
                headline = await element.query_selector(".entity-result__primary-subtitle")
                if headline:
                    result["headline"] = await headline.inner_text()
                
                # Location
                location = await element.query_selector(".entity-result__secondary-subtitle")
                if location:
                    result["location"] = await location.inner_text()
                
                # Connection info
                connection_info = await element.query_selector(".entity-result__badge-text")
                if connection_info:
                    result["connection_degree"] = await connection_info.inner_text()
                
                if result.get("name"):
                    results.append(result)
                    
            except Exception as e:
                logger.debug(f"Failed to parse search result: {e}")
                continue
        
    except Exception as e:
        logger.error(f"Failed to extract search results: {e}")
    
    return results


async def get_company(
    profile_id: str,
    company_url: str,
) -> dict:
    """Get LinkedIn company details.
    
    Args:
        profile_id: Profile UUID (your account)
        company_url: URL of the LinkedIn company page
    
    Returns:
        Dict with company information
    """
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
        
        # Normalize company URL to about page for more details
        if "/company/" in company_url and "/about" not in company_url:
            company_url = company_url.rstrip("/") + "/about"
        
        # Navigate to company page with retry/fallback to handle transient timeouts.
        logger.info(f"[get_company] Navigating to: {company_url}")
        navigation_targets = [company_url]
        company_root_url = company_url.replace("/about", "")
        if company_root_url not in navigation_targets:
            navigation_targets.append(company_root_url)

        last_nav_error = None
        navigated = False
        for target in navigation_targets:
            for wait_until, timeout in (("domcontentloaded", 45000), ("commit", 45000)):
                try:
                    await browser.navigate(target, wait_until=wait_until, timeout=timeout)
                    navigated = True
                    break
                except Exception as nav_exc:
                    last_nav_error = nav_exc
                    logger.warning(
                        f"[get_company] Navigation failed target={target} wait_until={wait_until} "
                        f"timeout={timeout}: {nav_exc}"
                    )
            if navigated:
                break

        if not navigated:
            return {
                "status": "error",
                "message": f"Failed to navigate to company page: {last_nav_error}",
            }

        # Check if logged in
        current_url = await browser.get_current_url()
        logger.info(f"[get_company] Current URL: {current_url}")

        if "login" in current_url or "authwall" in current_url:
            return {
                "status": "error",
                "message": "Not logged in - please login first",
            }

        auth_reason = await _detect_auth_wall(browser)
        if auth_reason:
            return {
                "status": "error",
                "message": f"Auth required: {auth_reason}",
            }

        # Wait for company page structure before extraction.
        for selector in [
            '[role="main"]',
            'main',
            'h1.org-top-card-summary__title',
            'h1.top-card-layout__title',
            '[data-test-id="about-us"]',
        ]:
            if await browser.wait_for_selector(selector, timeout=2500):
                break

        # Extract company data
        data = await _extract_company_data(browser)

        core_keys = [
            "name",
            "tagline",
            "website",
            "industry",
            "company_size",
            "headquarters",
            "founded",
            "specialties",
            "followers",
        ]
        has_core_data = any(bool((data or {}).get(k)) for k in core_keys)
        if not has_core_data:
            logger.warning("[get_company] First extraction returned no core company fields, retrying extraction pass")
            await human.delay(1200, 2000)
            try:
                await browser.navigate(current_url, wait_until="load", timeout=30000)
            except Exception as retry_nav_exc:
                logger.warning(f"[get_company] Retry navigation before second extraction failed: {retry_nav_exc}")
            data = await _extract_company_data(browser)
        
        return {
            "status": "ok",
            "data": data,
        }
        
    except Exception as e:
        logger.error(f"get_company failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "status": "error",
            "message": str(e),
        }


async def _extract_company_data(browser) -> Dict[str, Any]:
    """Extract company data from LinkedIn company page."""
    data = {}
    
    try:
        # Use JavaScript to extract company data from logged-in and guest layouts.
        js_extract = """
        () => {
            const result = {};
            const cleanText = (value) => (value || '').replace(/\s+/g, ' ').trim();
            const normalizeHref = (href) => {
                if (!href) return null;
                if (href.startsWith('http://') || href.startsWith('https://')) return href;
                if (href.startsWith('/')) return `https://www.linkedin.com${href}`;
                return href;
            };
            const root = document.querySelector('[role="main"]') || document.querySelector('main') || document.body;
            if (!root) return result;
            
            // Company name
            const nameEl = root.querySelector(
                'h1.org-top-card-summary__title, h1.top-card-layout__title, h1[data-test-id*="hero-title"], h1'
            );
            if (nameEl) result.name = nameEl.innerText.trim();
            
            // Tagline
            const taglineEl = root.querySelector(
                '.org-top-card-summary__tagline, h2.top-card-layout__headline, p.org-top-card-summary__tagline'
            );
            if (taglineEl) result.tagline = taglineEl.innerText.trim();
            
            // Subline (location/followers in guest layout)
            const sublineEl = root.querySelector('h3.top-card-layout__first-subline');
            if (sublineEl) {
                const text = sublineEl.innerText.trim();
                const parts = text.split('·').map(p => p.trim());
                if (parts.length >= 1) result.location = parts[0];
                if (parts.length >= 2) result.followers = parts[1];
            }

            if (!result.followers) {
                const followerCandidate = root.querySelector(
                    'a[href*="/followers/"], .org-top-card-summary-info-list__info-item, .top-card-layout__second-subline'
                );
                if (followerCandidate) {
                    const value = cleanText(followerCandidate.textContent);
                    if (/followers/i.test(value)) {
                        result.followers = value;
                    }
                }
            }

            if (!result.followers) {
                const bodyText = cleanText(root.innerText || '');
                const match = bodyText.match(/([\d,.\s]+[KMBkmb]?\s*followers)/i);
                if (match) result.followers = cleanText(match[1]);
            }
            
            // Logo URL
            const logoEl = root.querySelector(
                '.top-card-layout__entity-image-container img, .org-top-card-primary-content__logo-container img, img.org-top-card-primary-content__logo'
            );
            if (logoEl) result.logo_url = logoEl.getAttribute('data-delayed-url') || logoEl.src;
            
            // About section description
            const aboutDesc = root.querySelector('[data-test-id="about-us__description"], .org-about-us-organization-description__text');
            if (aboutDesc) result.about = aboutDesc.innerText.trim();
            
            // About us details - using data-test-id attributes
            const websiteEl = root.querySelector('[data-test-id="about-us__website"] dd a, [data-test-id="about-us__website"] a');
            if (websiteEl) {
                result.website = cleanText(websiteEl.innerText) || cleanText(websiteEl.getAttribute('href'));
            }
            
            const industryEl = root.querySelector('[data-test-id="about-us__industry"] dd, [data-test-id="about-us__industry"]');
            if (industryEl) result.industry = industryEl.innerText.trim();
            
            const sizeEl = root.querySelector('[data-test-id="about-us__size"] dd, [data-test-id="about-us__size"]');
            if (sizeEl) result.company_size = sizeEl.innerText.trim();
            
            const hqEl = root.querySelector('[data-test-id="about-us__headquarters"] dd, [data-test-id="about-us__headquarters"]');
            if (hqEl) result.headquarters = hqEl.innerText.trim();
            
            const typeEl = root.querySelector('[data-test-id="about-us__organizationType"] dd, [data-test-id="about-us__organizationType"]');
            if (typeEl) result.type = typeEl.innerText.trim();
            
            const foundedEl = root.querySelector('[data-test-id="about-us__foundedOn"] dd, [data-test-id="about-us__foundedOn"]');
            if (foundedEl) result.founded = foundedEl.innerText.trim();

            const specialtiesEl = root.querySelector('[data-test-id="about-us__specialties"] dd, [data-test-id="about-us__specialties"]');
            if (specialtiesEl) result.specialties = specialtiesEl.innerText.trim();
            
            // Fallback: parse dt/dd pairs from any about/details section
            const aboutSections = Array.from(root.querySelectorAll('[data-test-id="about-us"], section, dl')).slice(0, 40);
            const labelMap = {
                website: 'website',
                industry: 'industry',
                size: 'company_size',
                company_size: 'company_size',
                company_size_: 'company_size',
                headquarters: 'headquarters',
                founded: 'founded',
                founded_on: 'founded',
                specialties: 'specialties',
                speciality: 'specialties',
                overview: 'about',
                about: 'about',
                phone: 'phone',
                phone_number: 'phone',
                associated_members: 'associated_members',
                associated_member: 'associated_members',
                linkedin_members: 'associated_members',
                type: 'type',
            };

            for (const section of aboutSections) {
                const dtElements = section.querySelectorAll('dt');
                if (!dtElements || !dtElements.length) continue;
                dtElements.forEach((dt) => {
                    const dd = dt.nextElementSibling;
                    if (!dd || dd.tagName !== 'DD') return;
                    const label = cleanText(dt.innerText).toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
                    const mappedKey = labelMap[label] || null;
                    if (!mappedKey || result[mappedKey]) return;

                    const link = dd.querySelector('a[href]');
                    const rawValue = link ? (cleanText(link.innerText) || cleanText(link.getAttribute('href'))) : cleanText(dd.innerText);
                    if (!rawValue) return;
                    result[mappedKey] = rawValue;
                });
            }

            // Fallback: parse label/value pairs from flexible text blocks.
            const findValueByLabel = (labels) => {
                const labelSet = new Set(labels.map((label) => cleanText(label).toLowerCase()));
                const candidates = Array.from(root.querySelectorAll('dt, strong, h2, h3, h4, p, span, div')).slice(0, 800);
                for (const node of candidates) {
                    const labelText = cleanText(node.textContent).toLowerCase();
                    if (!labelSet.has(labelText)) continue;

                    const siblingValue = cleanText(node.nextElementSibling ? node.nextElementSibling.textContent : '');
                    if (siblingValue && siblingValue.toLowerCase() !== labelText) {
                        return siblingValue;
                    }

                    const parent = node.parentElement;
                    if (parent) {
                        const children = Array.from(parent.children);
                        const idx = children.indexOf(node);
                        for (let i = idx + 1; i < Math.min(children.length, idx + 4); i += 1) {
                            const value = cleanText(children[i].textContent);
                            if (value && value.toLowerCase() !== labelText) {
                                return value;
                            }
                        }
                    }
                }
                return null;
            };

            if (!result.about) {
                const overviewValue = findValueByLabel(['overview', 'about']);
                if (overviewValue && overviewValue.length > 20) {
                    result.about = overviewValue;
                }
            }

            if (!result.phone) {
                const phoneFromLabel = findValueByLabel(['phone', 'phone number']);
                if (phoneFromLabel) {
                    result.phone = phoneFromLabel;
                }
            }

            if (!result.associated_members) {
                const membersFromLabel = findValueByLabel(['associated members', 'linkedin members']);
                if (membersFromLabel) {
                    result.associated_members = membersFromLabel;
                }
            }

            const bodyText = cleanText(root.innerText || '');
            if (!result.phone) {
                const phoneMatch = bodyText.match(/(\+\d[\d\s()\-]{7,}\d)/);
                if (phoneMatch) {
                    result.phone = cleanText(phoneMatch[1]);
                }
            }

            if (!result.associated_members) {
                const membersMatch = bodyText.match(/(\d[\d,]*\s+associated\s+members?)/i)
                    || bodyText.match(/(\d[\d,]*\s+linkedin\s+members?)/i);
                if (membersMatch) {
                    result.associated_members = cleanText(membersMatch[1]);
                }
            }

            if (!result.website) {
                const websiteLink = root.querySelector('a[href^="http"]');
                if (websiteLink) {
                    const href = normalizeHref(websiteLink.getAttribute('href'));
                    if (href && !href.includes('linkedin.com')) {
                        result.website = cleanText(websiteLink.innerText) || href;
                    }
                }
            }

            if (!result.headquarters && result.location) {
                result.headquarters = result.location;
            }

            if (!result.about && result.tagline && result.tagline.length > 30) {
                result.about = result.tagline;
            }

            // Fallback: parse from metadata when visible UI selectors are sparse.
            if (!result.name) {
                const ogTitle = cleanText(document.querySelector('meta[property="og:title"]')?.getAttribute('content'));
                const titleText = cleanText(document.title || '');
                const titleCandidate = ogTitle || titleText;
                if (titleCandidate) {
                    const cleaned = titleCandidate.replace(/\s*\|\s*linkedin.*$/i, '').trim();
                    if (cleaned && cleaned.length > 1) {
                        result.name = cleaned;
                    }
                }
            }

            if (!result.tagline) {
                const ogDesc = cleanText(document.querySelector('meta[property="og:description"]')?.getAttribute('content'));
                const metaDesc = cleanText(document.querySelector('meta[name="description"]')?.getAttribute('content'));
                const desc = ogDesc || metaDesc;
                if (desc && desc.length > 10 && !/sign in|join linkedin/i.test(desc)) {
                    result.tagline = desc;
                }
            }

            // Fallback: parse JSON-LD Organization data
            const ldJsonNodes = Array.from(document.querySelectorAll('script[type="application/ld+json"]')).slice(0, 20);
            for (const node of ldJsonNodes) {
                if (result.name && result.website && result.tagline) break;
                try {
                    const parsed = JSON.parse(node.textContent || '{}');
                    const items = Array.isArray(parsed) ? parsed : [parsed];
                    for (const item of items) {
                        if (!item || typeof item !== 'object') continue;
                        const typ = String(item['@type'] || '').toLowerCase();
                        if (typ && !typ.includes('organization')) continue;

                        if (!result.name && item.name) {
                            result.name = cleanText(String(item.name));
                        }
                        if (!result.website && item.url) {
                            const url = cleanText(String(item.url));
                            if (url) result.website = url;
                        }
                        if (!result.tagline && item.description) {
                            const description = cleanText(String(item.description));
                            if (description) result.tagline = description;
                        }
                    }
                } catch (_) {
                    // ignore malformed ld+json
                }
            }
            
            // Extract latest posts from company feed
            result.posts = [];
            const postCards = root.querySelectorAll('article.main-feed-activity-card');
            postCards.forEach((card, index) => {
                if (index >= 5) return; // Limit to 5 posts
                
                const post = {};
                
                // Post author name
                const authorEl = card.querySelector('[data-tracking-control-name*="feed-actor-name"]');
                if (authorEl) post.author = authorEl.innerText.trim();
                
                // Post timestamp
                const timeEl = card.querySelector('time');
                if (timeEl) post.timestamp = timeEl.innerText.trim();
                
                // Post text content
                const textEl = card.querySelector('.attributed-text-segment-list__content, .break-words');
                if (textEl) {
                    post.text = textEl.innerText.trim();
                }
                
                // Reactions count
                const reactionsEl = card.querySelector('[data-test-id="social-actions__reactions"]');
                if (reactionsEl) {
                    const count = reactionsEl.getAttribute('data-num-reactions');
                    if (count) post.reactions = parseInt(count);
                }
                
                // Comments count
                const commentsEl = card.querySelector('[data-test-id="social-actions__comments"]');
                if (commentsEl) {
                    const count = commentsEl.getAttribute('data-num-comments');
                    if (count) post.comments = parseInt(count);
                }
                
                // Reposts count
                const repostsEl = card.querySelector('[data-test-id="social-actions__reposts"]');
                if (repostsEl) {
                    const count = repostsEl.getAttribute('data-num-reposts');
                    if (count) post.reposts = parseInt(count);
                }
                
                // Post URL
                const linkEl = card.querySelector('a[href*="/feed/update/"]');
                if (linkEl) post.url = linkEl.href;
                
                if (post.text || post.author) {
                    result.posts.push(post);
                }
            });
            
            return result;
        }
        """
        
        extracted = await browser.evaluate(js_extract)
        if extracted:
            data.update(extracted)
            logger.info(f"[get_company] Extracted: {list(data.keys())}")
        
    except Exception as e:
        logger.error(f"Failed to extract company data: {e}")
        import traceback
        logger.error(traceback.format_exc())
    
    return data
