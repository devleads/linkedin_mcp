"""Messaging tools for LinkedIn MCP Server."""

import asyncio
import hashlib
import logging
import random
import re
import sys
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse

from linkedin_mcp.browser.session import get_session_manager
from linkedin_mcp.browser.human import HumanBehavior
from linkedin_mcp.db import get_db
from linkedin_mcp.db.repository import ProfileRepository, CookieRepository

logger = logging.getLogger(__name__)


AUTO_MIN_CONVERSATIONS = 6
AUTO_MAX_CONVERSATIONS = 14
MAX_CONVERSATIONS_HARD_LIMIT = 30
MAX_MESSAGES_PER_CONVERSATION_HARD_LIMIT = 100
DEFAULT_MESSAGES_PER_CONVERSATION = 20
READ_MESSAGES_VERSION = "2026-05-09-sync-window-v4"


def _resolve_conversation_limit(max_conversations: int) -> int:
    """Resolve requested conversation count.

    If max_conversations is 0 or negative, picks a random latest-count in [6, 14].
    """
    if max_conversations <= 0:
        return random.randint(AUTO_MIN_CONVERSATIONS, AUTO_MAX_CONVERSATIONS)
    return max(1, min(max_conversations, MAX_CONVERSATIONS_HARD_LIMIT))


def _resolve_message_limit(max_messages_per_conversation: int) -> int:
    """Resolve per-conversation message window for sync use cases."""
    if max_messages_per_conversation <= 0:
        return DEFAULT_MESSAGES_PER_CONVERSATION
    return max(1, min(max_messages_per_conversation, MAX_MESSAGES_PER_CONVERSATION_HARD_LIMIT))


def _is_retryable_navigation_error(error: Exception) -> bool:
    """Return True for transient network/proxy/navigation failures."""
    message = str(error).lower()
    return any(
        marker in message
        for marker in [
            "timeout",
            "err_tunnel_connection_failed",
            "err_connection_reset",
            "err_network_changed",
            "net::",
            "page.goto",
        ]
    )


def _extract_conversation_id(raw_value: Optional[str]) -> str:
    """Extract LinkedIn conversation id from id or thread URL-like input."""
    if not raw_value:
        return ""
    value = raw_value.strip()
    if not value:
        return ""
    match = re.search(r"/messaging/thread/([^/?#]+)", value)
    if match:
        return match.group(1).strip()
    return value


def _extract_profile_id_from_url(raw_url: Optional[str]) -> str:
    """Extract LinkedIn profile id/slug from profile URL."""
    if not raw_url:
        return ""
    value = raw_url.strip()
    if not value:
        return ""
    match = re.search(r"/in/([^/?#]+)", value)
    if match:
        return match.group(1).strip().lower()
    return ""


def _normalize_profile_url(raw_url: Optional[str]) -> str:
    """Normalize LinkedIn profile URL into canonical lowercase host/path shape."""
    if not raw_url:
        return ""
    value = raw_url.strip()
    if not value:
        return ""

    if value.startswith("www.linkedin.com"):
        value = f"https://{value}"
    elif value.startswith("linkedin.com"):
        value = f"https://www.{value}"

    profile_id = _extract_profile_id_from_url(value)
    if profile_id:
        return f"https://www.linkedin.com/in/{profile_id}"

    try:
        parsed = urlparse(value)
    except Exception:
        return value.rstrip("/")

    if not parsed.scheme and not parsed.netloc:
        return value.rstrip("/")

    host = (parsed.netloc or "").lower()
    if host in {"linkedin.com", "www.linkedin.com"}:
        host = "www.linkedin.com"
    normalized = f"{parsed.scheme or 'https'}://{host}{parsed.path or ''}"
    return normalized.rstrip("/")


async def _extract_current_profile_identity(browser, fallback_url: Optional[str] = None) -> Dict[str, str]:
    try:
        current_url = await browser.get_current_url()
    except Exception:
        current_url = ""

    try:
        payload = await browser.evaluate(
            """
            () => {
                const out = {};
                const pickProfileHref = () => {
                    const selectors = [
                        'main a[href*="/in/"]',
                        '[role="main"] a[href*="/in/"]',
                        'a[href*="/in/"]'
                    ];
                    for (const selector of selectors) {
                        const nodes = Array.from(document.querySelectorAll(selector));
                        for (const node of nodes) {
                            const href = (node.href || node.getAttribute('href') || '').trim();
                            if (href && /\\/in\\/[^/?#]+/i.test(href)) return href;
                        }
                    }
                    return '';
                };

                const profileHref = pickProfileHref();
                if (profileHref) out.profile_url = profileHref;

                const composeHref = Array.from(document.querySelectorAll('a[href*="/messaging/compose/"]'))
                    .map((node) => node.href || node.getAttribute('href') || '')
                    .find((href) => href.includes('profileUrn=')) || '';
                if (composeHref) {
                    try {
                        const url = new URL(composeHref, window.location.origin);
                        const profileUrn = url.searchParams.get('profileUrn') || '';
                        if (profileUrn) out.member_urn = decodeURIComponent(profileUrn);
                    } catch (_) {}
                }

                const scripts = Array.from(document.querySelectorAll('code, script'))
                    .map((node) => node.textContent || '')
                    .join('\\n')
                    .slice(0, 500000);
                const publicIdentifier = scripts.match(/"publicIdentifier"\\s*:\\s*"([^"]+)"/);
                if (publicIdentifier) out.public_identifier = publicIdentifier[1];
                const entityUrn = scripts.match(/"entityUrn"\\s*:\\s*"(urn:li:[^"]+)"/);
                if (entityUrn && !out.member_urn) out.member_urn = entityUrn[1];
                return out;
            }
            """
        )
    except Exception:
        payload = {}

    if not isinstance(payload, dict):
        payload = {}

    current_profile_url = _normalize_profile_url(current_url) if _extract_profile_id_from_url(current_url) else ""
    profile_url = current_profile_url or _clean_message_text(payload.get("profile_url")) or _normalize_profile_url(fallback_url)
    profile_id = _extract_profile_id_from_url(profile_url) or _extract_profile_id_from_url(fallback_url)
    public_identifier = _clean_message_text(payload.get("public_identifier")) or profile_id
    member_urn = _clean_message_text(payload.get("member_urn"))
    normalized_url = _normalize_profile_url(profile_url or fallback_url)

    out: Dict[str, str] = {}
    if profile_id:
        out["recipient_profile_id"] = profile_id
    if normalized_url:
        out["recipient_profile_url"] = normalized_url
    if public_identifier:
        out["recipient_public_identifier"] = public_identifier
    if member_urn:
        out["recipient_member_urn"] = member_urn
    return out


def _profile_urls_match(lhs: Optional[str], rhs: Optional[str]) -> bool:
    """Compare LinkedIn profile URLs robustly using id fallback."""
    left = _normalize_profile_url(lhs)
    right = _normalize_profile_url(rhs)
    if left and right and left == right:
        return True

    left_id = _extract_profile_id_from_url(left)
    right_id = _extract_profile_id_from_url(right)
    return bool(left_id and right_id and left_id == right_id)


def _to_absolute_linkedin_url(raw_href: Optional[str]) -> str:
    """Build absolute LinkedIn URL from relative or absolute href."""
    if not raw_href:
        return ""
    href = raw_href.strip()
    if not href:
        return ""
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("//"):
        return f"https:{href}"
    if href.startswith("/"):
        return f"https://www.linkedin.com{href}"
    return f"https://www.linkedin.com/{href.lstrip('/')}"


async def _find_profile_compose_url(browser) -> str:
    """Find profile-page message compose link URL if present."""
    selectors = [
        'a[href*="/messaging/compose/?recipient="]',
        'a[href*="/messaging/compose/?profileUrn="]',
        'a[href*="/messaging/compose/"]',
    ]

    for selector in selectors:
        candidates = await browser.query_selector_all(selector)
        for candidate in candidates:
            try:
                if not await candidate.is_visible():
                    continue
                href = (await candidate.get_attribute("href")) or ""
                absolute = _to_absolute_linkedin_url(href)
                if "/messaging/compose/" in absolute:
                    return absolute
            except Exception:
                continue
    return ""


def _clean_message_text(raw_text: Optional[str]) -> str:
    """Normalize message preview text and guard against accidental HTML payloads."""
    if not raw_text:
        return ""

    text = raw_text.strip()
    lowered = text.lower()

    if (
        "<!doctype" in lowered
        or "<html" in lowered
        or "<head" in lowered
        or "<body" in lowered
        or "<script" in lowered
    ):
        return ""

    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _build_message_fallback_id(
    sender: str,
    timestamp: str,
    text: str,
    conversation_id: str = "",
) -> str:
    """Build deterministic fallback message id when LinkedIn URN is unavailable."""
    payload = f"{conversation_id}|{sender}|{timestamp}|{text}".encode("utf-8", errors="ignore")
    return f"msg_fallback:{hashlib.sha1(payload).hexdigest()}"


async def _extract_visible_thread_messages(browser, max_messages: int = 20) -> Dict[str, Any]:
    """Extract visible message bubbles from the currently opened conversation thread."""
    max_messages = max(1, min(max_messages, 100))
    js_script = """
        () => {{
            const isVisible = (el) => {{
                if (!el) return false;
                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden') return false;
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            }};

            const threadRoot =
                document.querySelector('.scaffold-layout__detail .msg-thread') ||
                document.querySelector('.msg-sponsored-conversation-thread') ||
                document;

            const bodyNodes = Array.from(
                threadRoot.querySelectorAll(
                    '.msg-s-event-listitem__body, .msg-spinmail-thread-presenter__message-body'
                )
            );
            const out = [];
            for (const bodyNode of bodyNodes) {{
                if (!isVisible(bodyNode)) continue;

                const eventNode =
                    bodyNode.closest('.msg-s-event-listitem') ||
                    bodyNode.closest('.msg-s-message-list__event') ||
                    bodyNode.closest('li');

                let text = (bodyNode.innerText || bodyNode.textContent || '').trim();
                text = text.replace(/\\s+/g, ' ').trim();
                if (!text) continue;
                if (text.length > 5000) continue;

                text = text
                    .replace(/\bGet the guide!\b/gi, '')
                    .replace(/\bNot interested\b/gi, '')
                    .replace(/\\s+/g, ' ')
                    .trim();
                if (!text) continue;

                const lowered = text.toLowerCase();
                if (lowered.includes('type a message') || lowered === 'read') continue;

                const senderEl = eventNode?.querySelector('.msg-s-message-group__name, .msg-s-event-listitem__name, .msg-sender__name');
                const timestampEl = eventNode?.querySelector('time, .msg-s-message-group__timestamp, .msg-s-event-listitem__timestamp');
                const eventUrn = (eventNode?.getAttribute('data-event-urn') || '').trim();

                out.push({
                    text: text,
                    sender: (senderEl?.innerText || '').trim(),
                    timestamp: (timestampEl?.innerText || timestampEl?.getAttribute?.('datetime') || '').trim(),
                    event_urn: eventUrn,
                });
            }}

            const deduped = [];
            const seen = new Set();
            for (const item of out) {{
                const key = `${{item.sender}}|${{item.timestamp}}|${{item.text}}`;
                if (seen.has(key)) continue;
                seen.add(key);
                deduped.push(item);
            }}

            return {{
                raw_items: deduped.slice(-__MAX_MESSAGES__),
                diagnostics: {{
                    body_node_count: bodyNodes.length,
                    raw_item_count: out.length,
                    deduped_item_count: deduped.length,
                }},
            }};
        }}
        """
    js_script = js_script.replace("{{", "{").replace("}}", "}")
    js_script = js_script.replace("__MAX_MESSAGES__", str(max_messages))
    extraction = await browser.evaluate(js_script)

    messages: List[Dict[str, str]] = []
    for raw_item in (extraction or {}).get("raw_items") or []:
        if not isinstance(raw_item, dict):
            continue
        try:
            msg_text = _clean_message_text(raw_item.get("text"))
            if not msg_text:
                continue
            sender = _clean_message_text(raw_item.get("sender"))
            timestamp = _clean_message_text(raw_item.get("timestamp"))
            event_urn = _clean_message_text(raw_item.get("event_urn"))
            message_id = event_urn or _build_message_fallback_id(
                sender=sender,
                timestamp=timestamp,
                text=msg_text,
            )
            messages.append(
                {
                    "message_id": message_id,
                    "text": msg_text,
                    "sender": sender,
                    "timestamp": timestamp,
                }
            )
        except Exception:
            continue
    diagnostics = (extraction or {}).get("diagnostics") or {}
    diagnostics["cleaned_item_count"] = len(messages)
    return {
        "messages": messages,
        "diagnostics": diagnostics,
    }


def _merge_thread_messages(
    existing: List[Dict[str, str]],
    incoming: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    """Append unseen thread messages while preserving encounter order."""
    merged = list(existing)
    seen = {
        f"{item.get('sender', '')}|{item.get('timestamp', '')}|{item.get('text', '')}"
        for item in existing
    }

    for item in incoming:
        key = f"{item.get('sender', '')}|{item.get('timestamp', '')}|{item.get('text', '')}"
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)

    return merged


async def _extract_desktop_thread_messages_with_scroll(browser, max_messages: int = 60) -> Dict[str, Any]:
    """Extract fuller desktop thread history by paging upward through the thread container."""
    max_messages = max(1, min(max_messages, 100))
    aggregated_messages: List[Dict[str, str]] = []
    diagnostics: Dict[str, Any] = {
        "scroll_passes": 0,
        "scroll_steps": 0,
    }

    for _ in range(10):
        batch_payload = await _extract_visible_thread_messages(browser, max_messages=100)
        batch_messages = batch_payload.get("messages", [])
        batch_diag = batch_payload.get("diagnostics", {})
        if batch_diag:
            diagnostics["last_visible_batch"] = batch_diag

        before_count = len(aggregated_messages)
        aggregated_messages = _merge_thread_messages(aggregated_messages, batch_messages)
        diagnostics["scroll_passes"] += 1

        scroll_result = await browser.evaluate(
            """
            () => {
                const scroller =
                    document.querySelector('.msg-s-message-list-container') ||
                    document.querySelector('.msg-s-message-list-content') ||
                    document.querySelector('.msg-thread__content') ||
                    document.querySelector('.msg-thread');
                if (!scroller) {
                    return { status: 'no_scroller', at_top: true, moved: 0 };
                }

                const before = scroller.scrollTop || 0;
                const step = Math.max(300, Math.floor((scroller.clientHeight || 0) * 0.9));
                scroller.scrollTop = Math.max(0, before - step);
                const after = scroller.scrollTop || 0;

                return {
                    status: 'ok',
                    at_top: after <= 2,
                    moved: Math.max(0, before - after),
                };
            }
            """
        )

        diagnostics["last_scroll"] = scroll_result
        if isinstance(scroll_result, dict) and scroll_result.get("moved", 0) > 0:
            diagnostics["scroll_steps"] += 1

        no_new_messages = len(aggregated_messages) == before_count
        reached_top = isinstance(scroll_result, dict) and bool(scroll_result.get("at_top"))
        did_not_move = not isinstance(scroll_result, dict) or scroll_result.get("moved", 0) <= 0

        if reached_top:
            break
        if no_new_messages and did_not_move:
            break

        await asyncio.sleep(0.6)

    diagnostics["aggregated_message_count"] = len(aggregated_messages)
    return {
        "messages": aggregated_messages[-max_messages:],
        "diagnostics": diagnostics,
    }


async def _extract_active_thread_participant_meta(browser) -> Dict[str, str]:
    """Extract participant profile metadata from currently opened desktop thread."""
    try:
        payload = await browser.evaluate(
            """
            () => {
                const pickText = (el) => ((el?.innerText || el?.textContent || '').trim());

                const profileLink =
                    document.querySelector('.msg-thread__link-to-profile[href*="/in/"]') ||
                    document.querySelector('.msg-title-bar__title a[href*="/in/"]') ||
                    document.querySelector('.msg-entity-lockup__entity-title-wrapper a[href*="/in/"]') ||
                    document.querySelector('.msg-s-profile-card-one-to-one a[href*="/in/"]');

                const href = (profileLink?.getAttribute('href') || '').trim();
                const absoluteHref = (profileLink?.href || href || '').trim();

                let profileId = '';
                const source = absoluteHref || href;
                if (source) {
                    const match = source.match(/\\/in\\/([^/?#]+)/i);
                    if (match) {
                        profileId = (match[1] || '').trim();
                    }
                }

                const titleName = pickText(document.querySelector('.msg-entity-lockup__entity-title'));
                const headingName = pickText(document.querySelector('.msg-thread__link-to-profile h2'));
                const name = titleName || headingName || pickText(profileLink);

                return {
                    participant_name: name,
                    participant_profile_url: absoluteHref || href,
                    participant_profile_id: profileId,
                };
            }
            """
        )
    except Exception:
        return {}

    if not isinstance(payload, dict):
        return {}

    out: Dict[str, str] = {}
    name = _clean_message_text(payload.get("participant_name"))
    profile_url = _clean_message_text(payload.get("participant_profile_url"))
    profile_id = _clean_message_text(payload.get("participant_profile_id"))

    if name:
        out["participant_name"] = name
    if profile_url:
        out["participant_profile_url"] = profile_url
    if profile_id:
        out["participant_profile_id"] = profile_id
    return out


async def _extract_desktop_conversation_messages(
    browser,
    human: HumanBehavior,
    conversation_element,
    max_messages_per_conversation: int,
    conversation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Open a desktop conversation item and return visible thread messages."""
    try:
        opened = await _open_desktop_conversation_thread(browser, human, conversation_element)
        if not opened.get("opened"):
            return {
                "messages": [],
                "diagnostics": {"click_error": opened.get("error", "conversation_click_failed")},
            }
    except Exception as exc:
        logger.debug(f"[read_messages] Failed waiting for conversation thread after click: {exc}")
        return {
            "messages": [],
            "diagnostics": {"open_error": str(exc)},
        }

    try:
        participant_meta = await _extract_active_thread_participant_meta(browser)
        resolved_conversation_id = conversation_id
        if not resolved_conversation_id:
            try:
                current_url = await browser.get_current_url()
            except Exception:
                current_url = ""
            if current_url:
                match = re.search(r"/messaging/thread/([^/?#]+)", current_url)
                if match:
                    resolved_conversation_id = match.group(1)

        payload = await _extract_desktop_thread_messages_with_scroll(
            browser,
            max_messages=max_messages_per_conversation,
        )
        messages = payload.get("messages") or []
        for item in messages:
            if resolved_conversation_id:
                item["conversation_id"] = resolved_conversation_id
            if not item.get("message_id"):
                item["message_id"] = _build_message_fallback_id(
                    sender=item.get("sender", ""),
                    timestamp=item.get("timestamp", ""),
                    text=item.get("text", ""),
                    conversation_id=resolved_conversation_id or "",
                )
        if resolved_conversation_id:
            payload["conversation_id"] = resolved_conversation_id
        if participant_meta:
            payload["participant_meta"] = participant_meta
        return payload
    except Exception as exc:
        logger.debug(f"[read_messages] Failed extracting thread messages: {exc}")
        payload: Dict[str, Any] = {
            "messages": [],
            "diagnostics": {"extract_error": str(exc)},
        }
        if resolved_conversation_id:
            payload["conversation_id"] = resolved_conversation_id
        if participant_meta:
            payload["participant_meta"] = participant_meta
        return payload


async def _open_desktop_conversation_thread(
    browser,
    human: HumanBehavior,
    conversation_element,
) -> Dict[str, Any]:
    """Click conversation list item and wait for the thread pane to load."""
    try:
        link = await conversation_element.query_selector(
            ".msg-conversation-listitem__link, .msg-conversations-container__convo-item-link"
        )
    except Exception:
        link = None

    await human.action_delay()
    clicked = False
    if link:
        try:
            clicked = bool(await browser.click_element_human(link))
        except Exception:
            clicked = False
    if not clicked:
        try:
            clicked = bool(await browser.click_element_human(conversation_element))
        except Exception:
            clicked = False

    if not clicked:
        return {
            "opened": False,
            "error": "conversation_click_failed",
        }

    await human.delay(700, 1500)
    loaded = await browser.wait_for_selector(
        ".msg-s-message-list-content, .msg-sponsored-conversation-thread, .msg-thread__content, .msg-thread",
        timeout=7000,
    )
    if not loaded:
        return {
            "opened": False,
            "error": "thread_did_not_load",
        }

    await human.delay(350, 900)
    return {"opened": True}


async def _find_message_input_element(browser):
    """Find visible message composer input for messaging thread/modal."""
    message_selectors = [
        ".msg-form__contenteditable",
        "div.msg-form__contenteditable[contenteditable='true']",
        "[contenteditable='true'][role='textbox']",
        "div[contenteditable='true'][aria-label*='Write a message']",
    ]

    for selector in message_selectors:
        candidates = await browser.query_selector_all(selector)
        for candidate in candidates:
            try:
                if await candidate.is_visible():
                    return candidate
            except Exception:
                continue
    return None


async def _wait_for_message_input_element(
    browser,
    human: HumanBehavior,
    attempts: int = 4,
) -> Optional[Any]:
    """Wait for a visible message composer input with short retries."""
    for _ in range(max(1, attempts)):
        message_input = await _find_message_input_element(browser)
        if message_input:
            return message_input

        await browser.wait_for_selector(
            ".msg-form__contenteditable, [contenteditable='true'][role='textbox'], .msg-form__send-button",
            timeout=5000,
        )
        await human.delay(300, 700)

    return None


async def _send_from_open_message_composer(
    browser,
    human: HumanBehavior,
    message_text: str,
    conversation_id: Optional[str] = None,
) -> Dict[str, str]:
    """Type and send message in currently opened composer/thread and return send metadata."""
    typed_ok = False
    for _ in range(3):
        message_input = await _wait_for_message_input_element(browser, human)
        if not message_input:
            await human.delay(300, 700)
            continue
        if await _type_text_human_like(message_input, message_text, human, browser=browser):
            typed_ok = True
            break
        await human.delay(350, 800)

    if not typed_ok:
        return {"error": "Failed to type message"}

    await human.delay(500, 1000)
    send_clicked = await _click_button_human_like(
        browser,
        human,
        selectors=[
            ".msg-form__send-button",
            "button.msg-form__send-button",
        ],
        text_candidates=["send"],
    )
    if not send_clicked:
        return {"error": "Send button not found or disabled"}

    await human.delay(900, 1800)

    sent_message_id = ""
    sent_timestamp = ""
    sent_sender = ""
    for _ in range(3):
        recent_payload = await _extract_visible_thread_messages(browser, max_messages=15)
        recent_messages = recent_payload.get("messages") or []
        for item in reversed(recent_messages):
            if _clean_message_text(item.get("text")) != message_text:
                continue
            sent_message_id = item.get("message_id") or ""
            sent_timestamp = item.get("timestamp") or ""
            sent_sender = item.get("sender") or ""
            break
        if sent_message_id:
            break
        await human.delay(350, 800)

    if not sent_message_id:
        sent_message_id = _build_message_fallback_id(
            sender=sent_sender or "You",
            timestamp=sent_timestamp,
            text=message_text,
            conversation_id=conversation_id or "",
        )

    return {
        "message_id": sent_message_id,
        "timestamp": sent_timestamp,
        "sender": sent_sender,
    }


async def _resolve_opened_thread_identity(
    browser,
    fallback_conversation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Resolve currently opened thread conversation id and participant metadata."""
    participant_meta = await _extract_active_thread_participant_meta(browser)
    resolved_conversation_id = _extract_conversation_id(fallback_conversation_id)
    if not resolved_conversation_id:
        try:
            current_url = await browser.get_current_url()
        except Exception:
            current_url = ""
        resolved_conversation_id = _extract_conversation_id(current_url)
    return {
        "conversation_id": resolved_conversation_id,
        "participant_meta": participant_meta or {},
    }


async def _open_inbox_thread_by_participant_url(
    browser,
    human: HumanBehavior,
    participant_profile_url: str,
    max_conversations_to_scan: int = 30,
) -> Dict[str, Any]:
    """Open a desktop inbox thread by scanning conversations and matching participant profile URL."""
    normalized_target = _normalize_profile_url(participant_profile_url)
    if not normalized_target:
        return {
            "opened": False,
            "error": "participant_profile_url is required",
        }

    scanned = 0
    index = 0
    while scanned < max_conversations_to_scan:
        conv_elements = await browser.query_selector_all(".msg-conversation-listitem")
        if index >= len(conv_elements):
            scroll_result = await browser.evaluate(
                """
                () => {
                    const scroller =
                        document.querySelector('.msg-conversations-container__conversations-list') ||
                        document.querySelector('.conversation-list') ||
                        document.querySelector('.msg-conversations-container');
                    if (!scroller) {
                        return { moved: 0 };
                    }
                    const before = scroller.scrollTop || 0;
                    const step = Math.max(280, Math.floor((scroller.clientHeight || 0) * 0.9));
                    scroller.scrollTop = before + step;
                    const after = scroller.scrollTop || 0;
                    return { moved: Math.max(0, after - before) };
                }
                """
            )
            moved = 0
            if isinstance(scroll_result, dict):
                moved = int(scroll_result.get("moved") or 0)
            if moved <= 0:
                break
            await human.delay(500, 1000)
            continue

        conversation_element = conv_elements[index]
        index += 1
        scanned += 1

        opened = await _open_desktop_conversation_thread(browser, human, conversation_element)
        if not opened.get("opened"):
            continue

        identity = await _resolve_opened_thread_identity(browser)
        participant_meta = identity.get("participant_meta") or {}
        opened_profile_url = participant_meta.get("participant_profile_url")
        if _profile_urls_match(opened_profile_url, normalized_target):
            return {
                "opened": True,
                "conversation_id": identity.get("conversation_id"),
                "participant_meta": participant_meta,
                "scanned": scanned,
            }

        await human.delay(250, 700)

    return {
        "opened": False,
        "error": "thread_not_found",
        "scanned": scanned,
    }


async def _type_text_human_like(
    element,
    text: str,
    human: HumanBehavior,
    browser,
    clear_first: bool = True,
) -> bool:
    """Type text with human-like behavior.

    Reusable across message/comment-like composers to reduce bot-like instant fills.
    """
    try:
        clicked = await browser.click_element_human(element)
        if not clicked:
            try:
                await element.click()
                clicked = True
            except Exception:
                clicked = False

        if not clicked:
            try:
                await element.focus()
                clicked = True
            except Exception:
                clicked = False

        if not clicked:
            return False

        await human.delay(200, 400)

        input_meta = await element.evaluate(
            """
            (el) => {
                const tag = (el.tagName || '').toLowerCase();
                return {
                    tag,
                    isContentEditable: !!el.isContentEditable,
                };
            }
            """
        )
        tag = (input_meta or {}).get("tag") or ""
        is_contenteditable = bool((input_meta or {}).get("isContentEditable"))

        if clear_first:
            existing_value = ""
            try:
                if tag in {"input", "textarea"}:
                    existing_value = (await element.input_value()) or ""
                elif is_contenteditable:
                    existing_value = await element.evaluate(
                        "(el) => (el.innerText || el.textContent || '')"
                    ) or ""
            except Exception:
                existing_value = ""

            if existing_value.strip():
                # Keyboard-based clear preserves focus on Ember/React components
                # (JS value mutation triggers re-renders that drop focus mid-typing).
                try:
                    select_all = "Meta+A" if sys.platform == "darwin" else "Control+A"
                    await browser.page.keyboard.press(select_all)
                    await human.delay(60, 140)
                    await browser.page.keyboard.press("Backspace")
                    await human.delay(80, 160)
                except Exception:
                    pass

        typing_delay = human.get_typing_speed()
        typed = False
        try:
            await element.type(text, delay=typing_delay)
            typed = True
        except Exception:
            typed = False

        if not typed and is_contenteditable:
            try:
                await element.evaluate(
                    """
                    (el) => {
                        el.focus();
                        const selection = window.getSelection();
                        if (selection) {
                            selection.removeAllRanges();
                            const range = document.createRange();
                            range.selectNodeContents(el);
                            range.collapse(false);
                            selection.addRange(range);
                        }
                    }
                    """
                )
                await browser.page.keyboard.type(text, delay=typing_delay)
                typed = True
            except Exception:
                typed = False

        if not typed and tag in {"input", "textarea"}:
            try:
                await element.focus()
                await browser.page.keyboard.type(text, delay=typing_delay)
                typed = True
            except Exception:
                typed = False

        if not typed:
            return False

        typed_text = await element.evaluate(
            """
            (el) => {
                const tag = (el.tagName || '').toLowerCase();
                if (tag === 'textarea' || tag === 'input') {
                    return (el.value || '').trim();
                }
                return (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
            }
            """
        )

        normalized_target = re.sub(r"\s+", " ", (text or "").strip())
        normalized_typed = re.sub(r"\s+", " ", (typed_text or "").strip())
        if not normalized_typed:
            return False

        if tag in {"input", "textarea"}:
            return normalized_typed == normalized_target

        return normalized_target in normalized_typed
    except Exception:
        return False


async def _click_button_human_like(
    browser,
    human: HumanBehavior,
    selectors: Optional[List[str]] = None,
    text_candidates: Optional[List[str]] = None,
    scope_selector: Optional[str] = None,
) -> bool:
    """Click a visible/enabled button via reusable selector + text fallback logic."""
    selectors = selectors or []
    text_candidates = [t.lower() for t in (text_candidates or [])]

    async def _matches_text_candidate(candidate) -> bool:
        if not text_candidates:
            return True
        try:
            aria = ((await candidate.get_attribute("aria-label")) or "").strip().lower()
        except Exception:
            aria = ""
        try:
            title = ((await candidate.get_attribute("title")) or "").strip().lower()
        except Exception:
            title = ""
        try:
            text = ((await candidate.inner_text()) or "").strip().lower()
        except Exception:
            text = ""

        combined = f"{aria} {title} {text}".strip()
        if not combined:
            return False
        return any(term in combined for term in text_candidates)

    for selector in selectors:
        try:
            candidates = await browser.query_selector_all(selector)
            for candidate in candidates:
                try:
                    if not await candidate.is_visible():
                        continue
                    if not await candidate.is_enabled():
                        continue
                    if not await _matches_text_candidate(candidate):
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


async def read_messages(
    profile_id: str,
    max_conversations: int = 0,
    max_messages_per_conversation: int = DEFAULT_MESSAGES_PER_CONVERSATION,
) -> dict:
    """Read LinkedIn messages/conversations.
    
    Args:
        profile_id: Profile UUID
        max_conversations: Maximum number of conversations to return
        max_messages_per_conversation: Latest messages to return per conversation
    
    Returns:
        Dict with conversations
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
        
        # Navigate to messaging (retry with longer timeout on transient failures).
        messaging_url = "https://www.linkedin.com/messaging/"
        last_nav_error: Optional[Exception] = None
        for nav_attempt in range(1, 4):
            try:
                await browser.navigate(messaging_url, timeout=90000)
                await human.page_load_delay()
                last_nav_error = None
                break
            except Exception as nav_exc:
                last_nav_error = nav_exc
                if nav_attempt >= 3 or not _is_retryable_navigation_error(nav_exc):
                    raise
                logger.warning(
                    f"[read_messages] Navigation attempt {nav_attempt}/3 failed: {nav_exc}. Retrying..."
                )
                await human.delay(1800, 3600)

        if last_nav_error is not None:
            raise last_nav_error
        
        # Check if logged in
        current_url = await browser.get_current_url()
        if "login" in current_url or "authwall" in current_url:
            return {
                "status": "error",
                "message": "Not logged in - please login first",
            }
        
        # Wait for messaging to load - try multiple selectors (desktop and mobile-lite)
        messaging_selectors = [
            ".msg-conversations-container__conversations-list",  # Desktop
            ".conversation-list",                                 # Mobile-lite
            "ul.conversation-list",                               # Mobile-lite variant
        ]
        
        messaging_found = False
        layout_type = "desktop"
        for selector in messaging_selectors:
            if await browser.wait_for_selector(selector, timeout=5000):
                logger.info(f"[read_messages] Found messaging with selector: {selector}")
                messaging_found = True
                if "conversation-list" in selector:
                    layout_type = "mobile"
                break
        
        if not messaging_found:
            return {
                "status": "error",
                "message": "Messaging did not load",
            }
        
        conversation_limit = _resolve_conversation_limit(max_conversations)
        message_limit = _resolve_message_limit(max_messages_per_conversation)

        # Extract conversations based on layout
        if layout_type == "mobile":
            conversations = await _extract_mobile_conversations(browser, conversation_limit)
        else:
            conversations = await _extract_conversations(
                browser,
                human,
                conversation_limit,
                message_limit,
            )
        
        # Save cookies after activity
        browser_cookies = await browser.get_cookies(["https://www.linkedin.com"])
        with get_db() as db:
            cookie_repo = CookieRepository(db)
            cookie_repo.set_from_playwright(session.profile_db_id, browser_cookies)
        
        return {
            "status": "ok",
            "profile_id": profile_id,
            "read_messages_version": READ_MESSAGES_VERSION,
            "requested_max_conversations": max_conversations,
            "applied_max_conversations": conversation_limit,
            "requested_max_messages_per_conversation": max_messages_per_conversation,
            "applied_max_messages_per_conversation": message_limit,
            "conversation_count": len(conversations),
            "conversations": conversations,
        }
        
    except Exception as e:
        logger.error(f"Failed to read messages: {e}")
        return {
            "status": "error",
            "message": str(e),
        }


async def _extract_conversations(
    browser,
    human: HumanBehavior,
    max_conversations: int,
    max_messages_per_conversation: int,
) -> List[Dict[str, Any]]:
    """Extract conversations from desktop messaging page."""
    conversations = []
    
    try:
        for index in range(max_conversations):
            conv_elements = await browser.query_selector_all(".msg-conversation-listitem")
            if index >= len(conv_elements):
                break

            element = conv_elements[index]
            try:
                conv = {}
                
                # Participant name
                name_elem = await element.query_selector(".msg-conversation-listitem__participant-names")
                if name_elem:
                    conv["participant"] = (await name_elem.inner_text()).strip()
                
                # Last message preview
                preview_elem = await element.query_selector(".msg-conversation-card__message-snippet")
                if preview_elem:
                    conv["last_message"] = _clean_message_text(await preview_elem.inner_text())

                # Conversation identifiers for sync tracking.
                conv_link = await element.query_selector(
                    "a.msg-conversation-listitem__link, a.msg-conversations-container__convo-item-link"
                )
                conversation_id = None
                if conv_link:
                    raw_href = (await conv_link.get_attribute("href")) or ""
                    if raw_href:
                        conv["thread_url"] = raw_href
                        match = re.search(r"/messaging/thread/([^/?#]+)", raw_href)
                        if match:
                            conversation_id = match.group(1)
                if not conversation_id:
                    conversation_id = (
                        (await element.get_attribute("data-conversation-id"))
                        or (await element.get_attribute("data-id"))
                        or ""
                    ).strip() or None
                if conversation_id:
                    conv["conversation_id"] = conversation_id

                thread_payload = await _extract_desktop_conversation_messages(
                    browser,
                    human,
                    element,
                    max_messages_per_conversation,
                    conversation_id=conversation_id,
                )
                resolved_conversation_id = thread_payload.get("conversation_id")
                if not conversation_id and resolved_conversation_id:
                    conversation_id = resolved_conversation_id
                    conv["conversation_id"] = conversation_id
                thread_messages = thread_payload.get("messages", [])
                thread_diagnostics = thread_payload.get("diagnostics", {})
                participant_meta = thread_payload.get("participant_meta") or {}
                if participant_meta.get("participant_profile_id"):
                    conv["participant_profile_id"] = participant_meta["participant_profile_id"]
                if participant_meta.get("participant_profile_url"):
                    conv["participant_profile_url"] = participant_meta["participant_profile_url"]
                if not conv.get("participant") and participant_meta.get("participant_name"):
                    conv["participant"] = participant_meta["participant_name"]
                if thread_diagnostics:
                    conv["thread_extraction"] = thread_diagnostics
                if thread_messages:
                    conv["messages"] = thread_messages
                    conv["message_count"] = len(thread_messages)
                    conv["last_message"] = thread_messages[-1].get("text", conv.get("last_message", ""))

                    # Simulate glance/read dwell on opened thread content.
                    total_chars = sum(len((m.get("text") or "")) for m in thread_messages[-3:])
                    await human.reading_delay(max(40, total_chars))
                
                # Timestamp
                time_elem = await element.query_selector(".msg-conversation-listitem__time-stamp")
                if time_elem:
                    conv["timestamp"] = (await time_elem.inner_text()).strip()
                
                # Unread indicator
                unread_elem = await element.query_selector(".msg-conversation-card__unread-count")
                conv["unread"] = unread_elem is not None
                
                if conv.get("participant"):
                    conversations.append(conv)
                    await human.delay(500, 1200)
                    if random.random() < 0.22:
                        await human.delay(1200, 2600)
                    
            except Exception as e:
                logger.debug(f"Failed to parse conversation: {e}")
                continue
        
    except Exception as e:
        logger.error(f"Failed to extract conversations: {e}")
    
    return conversations


async def _extract_mobile_conversations(browser, max_conversations: int) -> List[Dict[str, Any]]:
    """Extract conversations from mobile-lite messaging page."""
    conversations = []
    
    try:
        # Get conversation items - mobile-lite uses .conversation-item
        conv_elements = await browser.query_selector_all(".conversation-item")
        logger.info(f"[read_messages] Found {len(conv_elements)} mobile conversations")
        
        for element in conv_elements[:max_conversations]:
            try:
                conv = {}
                
                # Participant name - in p with body-medium-open or body-medium-bold-open
                name_elem = await element.query_selector("p.body-medium-open, p.body-medium-bold-open")
                if name_elem:
                    conv["participant"] = (await name_elem.inner_text()).strip()
                
                # Last message preview - in p.body-small-open inside second section
                preview_elem = await element.query_selector("p.body-small-open")
                if preview_elem:
                    conv["last_message"] = _clean_message_text(await preview_elem.inner_text())
                
                # Timestamp - in p.body-xsmall
                time_elem = await element.query_selector("p.body-xsmall")
                if time_elem:
                    conv["timestamp"] = (await time_elem.inner_text()).strip()
                
                # Unread indicator - span with unread count
                unread_elem = await element.query_selector("span.rounded-full.bg-color-link")
                conv["unread"] = unread_elem is not None
                if unread_elem:
                    unread_text = await unread_elem.inner_text()
                    try:
                        conv["unread_count"] = int(unread_text.strip())
                    except ValueError:
                        conv["unread_count"] = 1
                
                # Check if sponsored
                sponsored_elem = await element.query_selector("[data-is-sponsored]")
                conv["is_sponsored"] = sponsored_elem is not None
                
                # Get thread URL
                link_elem = await element.query_selector("a[href*='/messaging/thread/']")
                if link_elem:
                    thread_url = (await link_elem.get_attribute("href")) or ""
                    conv["thread_url"] = thread_url
                    match = re.search(r"/messaging/thread/([^/?#]+)", thread_url)
                    if match:
                        conv["conversation_id"] = match.group(1)
                
                if conv.get("participant"):
                    conversations.append(conv)
                    
            except Exception as e:
                logger.debug(f"Failed to parse mobile conversation: {e}")
                continue
        
    except Exception as e:
        logger.error(f"Failed to extract mobile conversations: {e}")
    
    return conversations


async def send_message(
    profile_id: str,
    recipient_url: str,
    message: str,
) -> dict:
    """Send a direct message to a LinkedIn connection.
    
    Args:
        profile_id: Profile UUID
        recipient_url: LinkedIn profile URL of the recipient
        message: Message text to send
    
    Returns:
        Status dict
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
        
        # Navigate to recipient's profile
        await browser.navigate(recipient_url)
        await human.page_load_delay()
        
        # Check if logged in
        current_url = await browser.get_current_url()
        if "login" in current_url or "authwall" in current_url:
            return {
                "status": "error",
                "message": "Not logged in - please login first",
            }
        
        # Wait for profile to load
        if not await browser.wait_for_selector(".pv-top-card", timeout=10000):
            return {
                "status": "error",
                "message": "Profile did not load",
            }
        
        compose_url = await _find_profile_compose_url(browser)
        if compose_url:
            await browser.navigate(compose_url, timeout=90000)
            await human.page_load_delay()
            await human.delay(700, 1400)
        else:
            message_clicked = await _click_button_human_like(
                browser,
                human,
                selectors=[
                    "a[href*='/messaging/compose/']",
                    "button[aria-label*='Message']",
                    "[role='button'][aria-label*='Message']",
                ],
                text_candidates=["message"],
            )
            if not message_clicked:
                return {
                    "status": "error",
                    "message": "Message action not found - may not be connected",
                }
            await human.delay(1000, 2000)
        
        # Wait for message modal
        if not await browser.wait_for_selector(".msg-form__contenteditable", timeout=5000):
            return {
                "status": "error",
                "message": "Message composer did not open",
            }
        
        # Type message
        await human.delay(500, 1000)
        message_input = None
        message_selectors = [
            ".msg-form__contenteditable",
            "div.msg-form__contenteditable[contenteditable='true']",
            "[contenteditable='true'][role='textbox']",
        ]

        for selector in message_selectors:
            candidates = await browser.query_selector_all(selector)
            for candidate in candidates:
                try:
                    if await candidate.is_visible():
                        message_input = candidate
                        break
                except Exception:
                    continue
            if message_input:
                break

        if not message_input:
            return {
                "status": "error",
                "message": "Message composer input not found",
            }

        if not await _type_text_human_like(message_input, message, human, browser=browser):
            return {
                "status": "error",
                "message": "Failed to type message",
            }
        await human.delay(500, 1000)
        
        # Click send
        send_clicked = await _click_button_human_like(
            browser,
            human,
            selectors=[
                ".msg-form__send-button",
                "button.msg-form__send-button",
            ],
            text_candidates=["send"],
        )
        if not send_clicked:
            return {
                "status": "error",
                "message": "Send button not found",
            }

        await human.delay(1000, 2000)
        
        # Save cookies after activity
        browser_cookies = await browser.get_cookies(["https://www.linkedin.com"])
        with get_db() as db:
            cookie_repo = CookieRepository(db)
            cookie_repo.set_from_playwright(session.profile_db_id, browser_cookies)
        
        return {
            "status": "ok",
            "profile_id": profile_id,
            "recipient": recipient_url,
            "message_length": len(message),
        }
        
    except Exception as e:
        logger.error(f"Failed to send message: {e}")
        return {
            "status": "error",
            "message": str(e),
        }


async def send_inbox_message(
    profile_id: str,
    message: str,
    conversation_id: Optional[str] = None,
    participant_profile_url: Optional[str] = None,
    existing_thread_only: bool = True,
) -> dict:
    """Send a message via LinkedIn thread/profile compose routing.

    Routing:
    - If conversation_id is provided, use inbox thread flow.
    - Else if participant_profile_url is provided, open profile and use compose flow.
    """
    try:
        message_text = _clean_message_text(message)
        if not message_text:
            return {
                "status": "error",
                "message": "Message text is required",
            }

        resolved_conversation_id = _extract_conversation_id(conversation_id)
        normalized_profile_url = _normalize_profile_url(participant_profile_url)
        if not resolved_conversation_id and not normalized_profile_url:
            return {
                "status": "error",
                "message": "Either conversation_id or participant_profile_url is required",
            }

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

        participant_meta: Dict[str, str] = {}
        flow_used = ""
        if resolved_conversation_id:
            flow_used = "conversation_id_inbox"
            messaging_url = "https://www.linkedin.com/messaging/"
            for nav_attempt in range(1, 4):
                try:
                    await browser.navigate(messaging_url, timeout=90000)
                    await human.page_load_delay()
                    break
                except Exception as nav_exc:
                    if nav_attempt >= 3 or not _is_retryable_navigation_error(nav_exc):
                        raise
                    logger.warning(
                        f"[send_inbox_message] Inbox navigation attempt {nav_attempt}/3 failed: {nav_exc}. Retrying..."
                    )
                    await human.delay(1800, 3600)

            current_url = await browser.get_current_url()
            if "login" in current_url or "authwall" in current_url:
                return {
                    "status": "error",
                    "message": "Not logged in - please login first",
                }
            await browser.wait_for_selector(
                ".msg-conversations-container__conversations-list, .conversation-list, ul.conversation-list",
                timeout=8000,
            )
            thread_url = f"https://www.linkedin.com/messaging/thread/{resolved_conversation_id}/"
            await browser.navigate(thread_url, timeout=90000)
            await human.page_load_delay()
            await browser.wait_for_selector(
                ".msg-s-message-list-content, .msg-thread, .msg-thread__content",
                timeout=8000,
            )
            identity = await _resolve_opened_thread_identity(
                browser,
                fallback_conversation_id=resolved_conversation_id,
            )
            participant_meta = identity.get("participant_meta") or {}
            resolved_conversation_id = identity.get("conversation_id") or resolved_conversation_id
        else:
            flow_used = "participant_profile_compose"
            await browser.navigate(normalized_profile_url, timeout=90000)
            await human.page_load_delay()
            await human.delay(700, 1400)

            current_url = await browser.get_current_url()
            if "login" in current_url or "authwall" in current_url:
                return {
                    "status": "error",
                    "message": "Not logged in - please login first",
                }

            profile_loaded = await browser.wait_for_selector(
                ".pv-top-card, main, a[href*='/messaging/compose/']",
                timeout=8000,
            )
            if not profile_loaded:
                return {
                    "status": "error",
                    "message": "Profile did not load",
                }

            compose_url = await _find_profile_compose_url(browser)
            if not compose_url:
                return {
                    "status": "error",
                    "message": "Profile message compose link not found - may not be connected",
                }

            await browser.navigate(compose_url, timeout=90000)
            await human.page_load_delay()
            await human.delay(700, 1400)
            await browser.wait_for_selector(
                ".msg-form__contenteditable, [contenteditable='true'][role='textbox'], .msg-form__send-button",
                timeout=15000,
            )

            identity = await _resolve_opened_thread_identity(browser)
            participant_meta = identity.get("participant_meta") or {}
            resolved_conversation_id = identity.get("conversation_id") or resolved_conversation_id

        opened_profile_url = participant_meta.get("participant_profile_url")
        participant_mismatch_warning: Optional[Dict[str, str]] = None
        if normalized_profile_url and opened_profile_url and not _profile_urls_match(normalized_profile_url, opened_profile_url):
            if flow_used == "conversation_id_inbox":
                return {
                    "status": "error",
                    "message": "Opened inbox thread participant does not match participant_profile_url",
                    "code": "participant_mismatch",
                    "expected_participant_profile_url": normalized_profile_url,
                    "actual_participant_profile_url": opened_profile_url,
                    "conversation_id": resolved_conversation_id,
                }
            participant_mismatch_warning = {
                "expected_participant_profile_url": normalized_profile_url,
                "actual_participant_profile_url": opened_profile_url,
            }

        send_payload = await _send_from_open_message_composer(
            browser,
            human,
            message_text,
            conversation_id=resolved_conversation_id,
        )
        if send_payload.get("error"):
            return {
                "status": "error",
                "message": send_payload.get("error"),
            }

        browser_cookies = await browser.get_cookies(["https://www.linkedin.com"])
        with get_db() as db:
            cookie_repo = CookieRepository(db)
            cookie_repo.set_from_playwright(session.profile_db_id, browser_cookies)

        return {
            "status": "ok",
            "profile_id": profile_id,
            "conversation_id": resolved_conversation_id,
            "participant_profile_id": participant_meta.get("participant_profile_id"),
            "participant_profile_url": participant_meta.get("participant_profile_url"),
            "participant_name": participant_meta.get("participant_name"),
            "message_id": send_payload.get("message_id"),
            "sent_text": message_text,
            "message_length": len(message_text),
            "existing_thread_only": existing_thread_only,
            "flow_used": flow_used,
            "participant_mismatch_warning": participant_mismatch_warning,
        }

    except Exception as e:
        logger.error(f"Failed to send inbox message: {e}")
        return {
            "status": "error",
            "message": str(e),
        }


async def send_connection_request(
    profile_id: str,
    recipient_url: str,
    note: str,
) -> dict:
    """Send a connection request to a LinkedIn user.
    
    Supports both mobile-lite and desktop LinkedIn.
    Mobile-lite is tried first as it's more reliable.
    
    Args:
        profile_id: Profile UUID
        recipient_url: LinkedIn profile URL of the recipient
        note: Connection note/cover letter (required, max 300 chars)
    
    Returns:
        Status dict
    """
    logger.info(f"[send_connection_request] Starting for profile {profile_id}")
    logger.info(f"[send_connection_request] Recipient: {recipient_url}")
    
    try:
        # Validate note is provided
        if not note or not note.strip():
            return {
                "status": "error",
                "message": "Connection note is required",
            }
        
        note = note.strip()
        
        # Validate note length
        if len(note) > 300:
            return {
                "status": "error",
                "message": "Connection note must be 300 characters or less",
            }
        
        # Verify profile exists
        with get_db() as db:
            profile_repo = ProfileRepository(db)
            profile = profile_repo.get_by_uuid(profile_id)
            if not profile:
                return {
                    "status": "error",
                    "message": f"Profile {profile_id} not found",
                }
        
        # Get or create session and keep it alive during long-running browser actions
        session_manager = get_session_manager()
        async with session_manager.operation_guard(profile_id):
            session = await session_manager.create_session(profile_id)
            browser = session.browser
            human = HumanBehavior()

            # Ensure we use desktop URL (mobile-lite doesn't support adding notes)
            # Convert any mobile URLs to desktop
            desktop_url = recipient_url.replace("/mwlite/", "/in/").replace("/m/", "/")
            if "/in/" not in desktop_url and "linkedin.com" in desktop_url:
                # Extract username and build proper desktop URL
                match = re.search(r'linkedin\.com/(?:mwlite/in/|m/in/|in/)([^/?]+)', recipient_url)
                if match:
                    username = match.group(1)
                    desktop_url = f"https://www.linkedin.com/in/{username}/"

            logger.info(f"[send_connection_request] Using desktop URL: {desktop_url}")

            # Navigate to recipient's profile (desktop version)
            await browser.navigate(desktop_url)
            await human.page_load_delay()

            # Wait for page to fully load
            await human.delay(2000, 3000)

            # Check if logged in
            current_url = await browser.get_current_url()
            logger.info(f"[send_connection_request] Current URL: {current_url}")

            if "login" in current_url or "authwall" in current_url:
                return {
                    "status": "error",
                    "message": "Not logged in - please login first",
                }

            # Check if we got redirected to mobile-lite anyway
            if "mwlite" in current_url or "/m/" in current_url:
                logger.warning("[send_connection_request] Redirected to mobile-lite, navigating back to desktop")
                await browser.navigate(desktop_url)
                await human.page_load_delay()
                await human.delay(2000, 3000)

            recipient_identity = await _extract_current_profile_identity(browser, fallback_url=desktop_url)

            # Always use desktop flow since note is required
            result = await _send_connection_request_desktop(browser, human, note)
            if recipient_identity:
                result.update(recipient_identity)

            if result.get("status") == "ok":
                # Save cookies after successful activity
                browser_cookies = await browser.get_cookies(["https://www.linkedin.com"])
                with get_db() as db:
                    cookie_repo = CookieRepository(db)
                    cookie_repo.set_from_playwright(session.profile_db_id, browser_cookies)

                result["profile_id"] = profile_id
                result["recipient"] = recipient_url
                result["note_included"] = True
                result["sent_note"] = note
                result["connection_action"] = "sent"
            elif result.get("status") == "already_connected":
                result["profile_id"] = profile_id
                result["recipient"] = recipient_url
                result["connection_action"] = "already_connected"
            elif result.get("status") == "already_pending":
                result["profile_id"] = profile_id
                result["recipient"] = recipient_url
                result["connection_action"] = "already_pending"

            return result
        
    except Exception as e:
        logger.error(f"Failed to send connection request: {e}")
        import traceback
        traceback.print_exc()
        return {
            "status": "error",
            "message": str(e),
        }


async def _send_connection_request_mobile(browser, human, note: str) -> dict:
    """Send connection request on mobile-lite LinkedIn.
    
    Mobile-lite profile pages have Connect option inside ellipsis menu (three dots).
    Flow: Click ellipsis menu -> Click Connect -> Handle note modal -> Click Send
    """
    logger.info("[send_connection_request_mobile] Starting mobile flow")
    
    # Wait for profile to load - on mobile-lite, wait for the ellipsis menu button
    # which appears a few seconds after the profile loads
    profile_selectors = [
        'button.ellipsis-menu__trigger',
        'button[aria-label="Open menu"]',
        '.basic-profile-section',
        '#profile-picture-container',
        '.profile-topcard',
    ]
    
    profile_loaded = False
    # Try multiple times with increasing delays since ellipsis button loads late
    for attempt in range(3):
        for selector in profile_selectors:
            if await browser.wait_for_selector(selector, timeout=5000):
                logger.info(f"[send_connection_request_mobile] Profile element found: {selector}")
                profile_loaded = True
                break
        if profile_loaded:
            break
        logger.info(f"[send_connection_request_mobile] Attempt {attempt + 1}: waiting for profile elements...")
        await human.delay(2000, 3000)
    
    if not profile_loaded:
        # Last resort - wait and check for any profile content
        await human.delay(3000, 4000)
    
    # Check connection status by looking at the ellipsis menu content
    # On mobile-lite, we need to check if Connect option exists in the menu
    connection_status = await browser.evaluate("""
        () => {
            // Check for pending invitation text
            const pageText = document.body.innerText.toLowerCase();
            if (pageText.includes('pending') || pageText.includes('invitation sent')) {
                return 'pending';
            }
            
            // Check if there's a Message button in the actions (indicates connected)
            // On mobile, connected users show Message button, not Connect
            const messageAction = document.querySelector('.actions-container a[href*="/messaging/"]');
            const connectInMenu = document.querySelector('li.connect-profile');
            
            if (messageAction && !connectInMenu) {
                return 'connected';
            }
            
            // Check if Connect option exists in ellipsis menu
            if (connectInMenu) {
                return 'not_connected';
            }
            
            return 'unknown';
        }
    """)
    
    logger.info(f"[send_connection_request_mobile] Connection status: {connection_status}")
    
    if connection_status == 'pending':
        return {
            "status": "already_pending",
            "message": "Connection request already pending",
        }
    
    if connection_status == 'connected':
        return {
            "status": "already_connected",
            "message": "Already connected with this user",
        }
    
    # Step 1: Wait for and click the ellipsis menu (three dots button)
    # The button appears a few seconds after the profile loads
    logger.info("[send_connection_request_mobile] Waiting for ellipsis menu button...")
    
    ellipsis_selectors = [
        'button.ellipsis-menu__trigger',
        'button[aria-label="Open menu"]',
        '.ellipsis-menu button',
    ]
    
    ellipsis_btn = None
    for attempt in range(5):  # Try up to 5 times with delays
        for selector in ellipsis_selectors:
            ellipsis_btn = await browser.query_selector(selector)
            if ellipsis_btn:
                logger.info(f"[send_connection_request_mobile] Found ellipsis button: {selector}")
                break
        if ellipsis_btn:
            break
        logger.info(f"[send_connection_request_mobile] Attempt {attempt + 1}: ellipsis button not found, waiting...")
        await human.delay(1500, 2500)
    
    if not ellipsis_btn:
        logger.error("[send_connection_request_mobile] Could not find ellipsis menu after retries")
        return {
            "status": "error",
            "message": "Could not find ellipsis menu on mobile profile (button loads late)",
        }
    
    # Click the ellipsis button
    await human.action_delay()
    if not await browser.click_element_human(ellipsis_btn):
        return {
            "status": "error",
            "message": "Failed to click ellipsis menu",
        }
    logger.info("[send_connection_request_mobile] Clicked ellipsis menu")
    await human.delay(800, 1200)
    
    # Step 2: Click Connect option in the dropdown menu
    connect_clicked = await _click_button_human_like(
        browser,
        human,
        selectors=[
            'li.connect-profile button[data-action="connect"]',
            'button[data-action="connect"]',
            'li.connect-profile button',
            '.ellipsis-menu__item-button',
            '.collapsible-dropdown__list button',
        ],
        text_candidates=['connect'],
        scope_selector='.collapsible-dropdown__list, .ellipsis-menu, [role="menu"]',
    )
    
    if not connect_clicked:
        logger.error("[send_connection_request_mobile] Connect option not found in menu")
        return {
            "status": "error",
            "message": "Connect option not found in ellipsis menu",
        }
    
    logger.info("[send_connection_request_mobile] Clicked Connect in menu")
    await human.delay(1500, 2500)
    
    # On mobile-lite, clicking Connect in the ellipsis menu may:
    # 1. Send the request immediately (shows toast "Request sent")
    # 2. Open a modal/bottom-sheet for adding a note
    
    # Check if a modal/bottom-sheet appeared for adding note
    modal_appeared = await browser.evaluate("""
        () => {
            const modal = document.querySelector('.bottom-sheet:not(.hidden), .modal:not([aria-hidden="true"]), [role="dialog"]:not([aria-hidden="true"])');
            return modal !== null;
        }
    """)
    
    if modal_appeared and note:
        logger.info("[send_connection_request_mobile] Note modal appeared, adding note")
        
        # Look for "Add a note" button or link
        add_note_clicked = await _click_button_human_like(
            browser,
            human,
            selectors=[
                '.bottom-sheet:not(.hidden) button',
                '.modal:not([aria-hidden="true"]) button',
                '[role="dialog"] button',
                '.bottom-sheet:not(.hidden) a',
                '.modal:not([aria-hidden="true"]) a',
                '[role="dialog"] a',
            ],
            text_candidates=['add a note', 'add note', 'personalize'],
            scope_selector='.bottom-sheet:not(.hidden), .modal:not([aria-hidden="true"]), [role="dialog"]',
        )
        
        if add_note_clicked:
            await human.delay(500, 1000)
        
        # Find and fill note textarea
        note_selectors = [
            'textarea[name="message"]',
            'textarea[id*="note"]',
            'textarea[placeholder*="note"]',
            'textarea[placeholder*="message"]',
            'textarea',
            'div[contenteditable="true"]',
        ]
        
        note_filled = False
        for selector in note_selectors:
            candidates = await browser.query_selector_all(selector)
            for note_input in candidates:
                try:
                    if not await note_input.is_visible():
                        continue
                    logger.info(f"[send_connection_request_mobile] Found note input: {selector}")
                    if await _type_text_human_like(note_input, note, human, browser=browser):
                        note_filled = True
                        await human.delay(500, 1000)
                        break
                except Exception:
                    continue
            if note_filled:
                break
        
        if not note_filled:
            logger.warning("[send_connection_request_mobile] Could not find note input in modal")
        
        # Click Send/Done button in modal
        await human.delay(500, 1000)
        
        send_clicked = await _click_button_human_like(
            browser,
            human,
            selectors=[
                '.bottom-sheet:not(.hidden) button.btn-primary:not([disabled])',
                '.modal:not([aria-hidden="true"]) button.btn-primary:not([disabled])',
                '[role="dialog"] button.btn-primary:not([disabled])',
            ],
            text_candidates=['send', 'send now', 'send invitation', 'done'],
            scope_selector='.bottom-sheet:not(.hidden), .modal:not([aria-hidden="true"]), [role="dialog"]',
        )
        
        if not send_clicked:
            logger.warning("[send_connection_request_mobile] Could not find send button in modal")
        
        await human.delay(2000, 3000)
    elif not modal_appeared:
        # No modal appeared - need to find another way to add note
        # On mobile-lite, the connection might be sent immediately without note option
        # This is a problem since note is required
        logger.error("[send_connection_request_mobile] No note modal appeared - cannot add required note")
        return {
            "status": "error",
            "message": "Mobile-lite does not support adding notes. Try desktop LinkedIn.",
        }
    
    # Check if the "Invited" text appeared (confirmation)
    await human.delay(500, 1000)
    invite_confirmed = await browser.evaluate("""
        () => {
            // Check for "Invited" or "Request sent" confirmation
            const invitedText = document.querySelector('.invite-sent-msg:not(.hidden), .network-action-msg:not(.hidden)');
            if (invitedText) return true;
            
            // Check toast message
            const toast = document.querySelector('.toast, [role="alert"]');
            if (toast && toast.innerText.toLowerCase().includes('sent')) return true;
            
            return false;
        }
    """)
    
    if invite_confirmed:
        logger.info("[send_connection_request_mobile] Connection request confirmed")
    
    return {"status": "ok", "message": "Connection request sent"}


async def _send_connection_request_desktop(browser, human, note: str) -> dict:
    """Send connection request on desktop LinkedIn.
    
    Desktop flow:
    1. Wait for profile to load (check for name heading or profile section)
    2. Check connection status (pending/connected)
    3. Find Connect button - either direct or via "More" dropdown
    4. Click Connect -> Modal appears with "Add a note" / "Send without a note" options
    5. Always click "Add a note" and fill in the note textarea
    6. Click "Send" button
    """
    logger.info("[send_connection_request_desktop] Starting desktop flow")
    
    # Wait for profile to load - new LinkedIn uses different selectors
    profile_loaded = await browser.evaluate("""
        () => {
            // Check for profile name heading (h2 with person's name)
            const nameHeading = document.querySelector('h2[class*="a551f3eb"]');
            // Check for profile section
            const profileSection = document.querySelector('section[class*="c0ff2433"]');
            // Check for any profile content
            const hasContent = document.body.innerText.includes('followers') || 
                              document.body.innerText.includes('connections');
            return !!(nameHeading || profileSection || hasContent);
        }
    """)
    
    if not profile_loaded:
        # Fallback: wait a bit more and check again
        await human.delay(2000, 3000)
        profile_loaded = await browser.evaluate("""
            () => {
                return document.body.innerText.length > 1000;
            }
        """)
    
    if not profile_loaded:
        return {
            "status": "error",
            "message": "Profile did not load",
        }
    
    logger.info("[send_connection_request_desktop] Profile loaded")
    
    # Check connection status using page text and buttons
    connection_status = await browser.evaluate("""
        () => {
            const pageText = document.body.innerText.toLowerCase();
            
            // Check for pending invitation
            if (pageText.includes('pending') && pageText.includes('invitation')) {
                return 'pending';
            }
            
            // Check for "Message" button without "Connect" - indicates already connected
            const buttons = Array.from(document.querySelectorAll('button, a'));
            const hasMessage = buttons.some(b => b.innerText.trim().toLowerCase() === 'message');
            const hasConnect = buttons.some(b => b.innerText.trim().toLowerCase() === 'connect');
            
            // Also check in More dropdown text
            const moreMenuText = document.querySelector('[role="menu"]')?.innerText?.toLowerCase() || '';
            const connectInMenu = moreMenuText.includes('connect');
            
            if (hasMessage && !hasConnect && !connectInMenu) {
                // Need to check More menu for Connect option
                return 'check_more_menu';
            }
            
            if (hasConnect || connectInMenu) {
                return 'not_connected';
            }
            
            return 'unknown';
        }
    """)
    
    logger.info(f"[send_connection_request_desktop] Connection status: {connection_status}")
    
    if connection_status == 'pending':
        return {
            "status": "already_pending",
            "message": "Connection request already pending",
        }

    connect_result = {"type": None, "clicked": False}

    async def _mark_topcard_connect_targets() -> Dict[str, bool]:
        """Mark deterministic top-card action targets for direct Connect and More button."""
        try:
            payload = await browser.evaluate(
                """
                () => {
                    const clearAttr = (attr) => {
                        document.querySelectorAll(`[${attr}="true"]`).forEach((node) => {
                            node.removeAttribute(attr);
                        });
                    };

                    clearAttr('data-mcp-topcard-target');
                    clearAttr('data-mcp-connect-target');
                    clearAttr('data-mcp-more-target');
                    clearAttr('data-mcp-connect-menu-target');

                    const isVisible = (el) => {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        if (style.display === 'none' || style.visibility === 'hidden') return false;
                        const rect = el.getBoundingClientRect();
                        return rect.width > 0 && rect.height > 0;
                    };

                    const isEnabled = (el) => {
                        if (!el) return false;
                        if (el.hasAttribute('disabled')) return false;
                        return el.getAttribute('aria-disabled') !== 'true';
                    };

                    const textOf = (el) => (
                        (el?.getAttribute?.('aria-label') || '') + ' ' +
                        (el?.getAttribute?.('title') || '') + ' ' +
                        (el?.innerText || el?.textContent || '')
                    ).trim().toLowerCase();

                    const hasConnectIntent = (label) => {
                        if (!label) return false;
                        if (/\bconnections?\b/.test(label)) return false;
                        if (label.includes('mutual connections')) return false;
                        return /\bconnect\b/.test(label) || /\binvite\b/.test(label);
                    };

                    const topcardCandidates = Array.from(document.querySelectorAll(
                        'main section[componentkey*="topcard" i], section[componentkey*="topcard" i], section[data-view-name*="top-card" i], section'
                    ));

                    const topcard = topcardCandidates.find((section) => {
                        if (!isVisible(section)) return false;
                        const hasName = !!section.querySelector('h1, h2');
                        if (!hasName) return false;
                        const hasProfileMessageAnchor = !!section.querySelector('a[href*="/messaging/compose/?profileUrn="]');
                        const hasActionRail = !!section.querySelector('button, a[role="button"], a[href*="/preload/custom-invite/"]');
                        return hasProfileMessageAnchor || hasActionRail;
                    }) || null;

                    if (!topcard) {
                        return {
                            topcard_found: false,
                            connect_marked: false,
                            more_marked: false,
                        };
                    }

                    topcard.setAttribute('data-mcp-topcard-target', 'true');

                    const actionNodes = Array.from(topcard.querySelectorAll(
                        'a, button, [role="button"]'
                    )).filter((el) => isVisible(el) && isEnabled(el));

                    let connectMarked = false;
                    for (const node of actionNodes) {
                        const label = textOf(node);
                        const href = (node.getAttribute('href') || '').toLowerCase();
                        const target = (node.getAttribute('target') || '').toLowerCase();
                        if (label.includes('send profile in a message')) continue;
                        if (label.includes('follow') || label.includes('message') || label.includes('book') || label.includes('report') || label.includes('block')) continue;
                        if (href.includes('/search/results/')) continue;
                        if (href.includes('/safety/go?')) continue;
                        if (target === '_blank') continue;
                        const isConnectLike =
                            href.includes('/preload/custom-invite/') ||
                            hasConnectIntent(label);
                        if (!isConnectLike) continue;
                        node.setAttribute('data-mcp-connect-target', 'true');
                        connectMarked = true;
                        break;
                    }

                    let moreMarked = false;
                    for (const node of actionNodes) {
                        const label = textOf(node);
                        if (label === 'more' || label.includes('more actions') || label.includes('more options')) {
                            node.setAttribute('data-mcp-more-target', 'true');
                            moreMarked = true;
                            break;
                        }
                    }

                    return {
                        topcard_found: true,
                        connect_marked: connectMarked,
                        more_marked: moreMarked,
                    };
                }
                """
            )
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            return {
                "topcard_found": False,
                "connect_marked": False,
                "more_marked": False,
            }
        return {
            "topcard_found": bool(payload.get("topcard_found")),
            "connect_marked": bool(payload.get("connect_marked")),
            "more_marked": bool(payload.get("more_marked")),
        }

    async def _mark_connect_item_in_open_menu() -> bool:
        """Mark visible Connect menu item from the currently opened More menu."""
        try:
            marked = await browser.evaluate(
                """
                () => {
                    document.querySelectorAll('[data-mcp-connect-menu-target="true"]').forEach((node) => {
                        node.removeAttribute('data-mcp-connect-menu-target');
                    });

                    const isVisible = (el) => {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        if (style.display === 'none' || style.visibility === 'hidden') return false;
                        const rect = el.getBoundingClientRect();
                        return rect.width > 0 && rect.height > 0;
                    };

                    const isEnabled = (el) => {
                        if (!el) return false;
                        if (el.hasAttribute('disabled')) return false;
                        return el.getAttribute('aria-disabled') !== 'true';
                    };

                    const textOf = (el) => (
                        (el?.getAttribute?.('aria-label') || '') + ' ' +
                        (el?.getAttribute?.('title') || '') + ' ' +
                        (el?.innerText || el?.textContent || '')
                    ).trim().toLowerCase();

                    const hasConnectIntent = (label) => {
                        if (!label) return false;
                        if (/\bconnections?\b/.test(label)) return false;
                        if (label.includes('mutual connections')) return false;
                        return /\bconnect\b/.test(label) || /\binvite\b/.test(label);
                    };

                    const menuRoots = Array.from(document.querySelectorAll(
                        '[popover="manual"], [role="menu"], .artdeco-dropdown__content, .artdeco-popover__content'
                    )).filter((el) => isVisible(el));
                    if (!menuRoots.length) return false;

                    for (const root of menuRoots) {
                        const menuItems = Array.from(root.querySelectorAll('a, button, [role="menuitem"], [role="button"]'));

                        let preferred = null;
                        for (const item of menuItems) {
                            if (!isVisible(item) || !isEnabled(item)) continue;
                            const label = textOf(item);
                            const href = (item.getAttribute('href') || '').toLowerCase();
                            if (!hasConnectIntent(label) && !href.includes('/preload/custom-invite/')) continue;
                            if (label.includes('send profile in a message')) continue;
                            if (href.includes('/search/results/')) continue;
                            if (href.includes('/preload/custom-invite/')) {
                                preferred = item;
                                break;
                            }
                            if (!preferred) {
                                preferred = item;
                            }
                        }

                        if (preferred) {
                            preferred.setAttribute('data-mcp-connect-menu-target', 'true');
                            return true;
                        }
                    }

                    return false;
                }
                """
            )
            return bool(marked)
        except Exception:
            return False

    topcard_targets = await _mark_topcard_connect_targets()
    logger.info(f"[send_connection_request_desktop] Top-card targets: {topcard_targets}")

    connect_clicked = False
    if topcard_targets.get("connect_marked"):
        try:
            topcard_connect = await browser.query_selector('[data-mcp-connect-target="true"]')
            if topcard_connect:
                if await browser.click_element_human(topcard_connect, timeout=1800):
                    connect_clicked = True
                    connect_result = {
                        "type": "topcard_direct_connect",
                        "clicked": True,
                    }
        except Exception:
            connect_clicked = False

    more_clicked = False
    if not connect_clicked and topcard_targets.get("more_marked"):
        logger.info("[send_connection_request_desktop] Direct top-card Connect unavailable, trying top-card More menu")
        try:
            topcard_more = await browser.query_selector('[data-mcp-more-target="true"]')
            if topcard_more:
                more_clicked = bool(await browser.click_element_human(topcard_more, timeout=1800))
        except Exception:
            more_clicked = False

    if more_clicked:
        menu_connect_marked = False
        for _ in range(10):
            menu_connect_marked = await _mark_connect_item_in_open_menu()
            if menu_connect_marked:
                break
            await human.delay(120, 220)
        if menu_connect_marked:
            try:
                menu_connect = await browser.query_selector('[data-mcp-connect-menu-target="true"]')
                if menu_connect:
                    async def _invite_flow_started() -> bool:
                        try:
                            return bool(
                                await browser.evaluate(
                                    """
                                    () => {
                                        const isVisible = (el) => {
                                            if (!el) return false;
                                            const style = window.getComputedStyle(el);
                                            if (style.display === 'none' || style.visibility === 'hidden') return false;
                                            const rect = el.getBoundingClientRect();
                                            return rect.width > 0 && rect.height > 0;
                                        };

                                        const url = (window.location.href || '').toLowerCase();
                                        if (url.includes('/preload/custom-invite/')) return true;

                                        const inviteDialog = Array.from(document.querySelectorAll('div.send-invite[role="dialog"], [data-test-modal][role="dialog"], .artdeco-modal[role="dialog"], [role="dialog"]'))
                                            .find((d) => isVisible(d));
                                        if (inviteDialog) return true;

                                        const noteEditor = document.querySelector('textarea#custom-message, textarea[name="message"], textarea[id*="custom-message"]');
                                        if (isVisible(noteEditor)) return true;

                                        return false;
                                    }
                                    """
                                )
                            )
                        except Exception:
                            return False

                    activation_done = False

                    # Path 1: human-like click on the marked element handle.
                    if not activation_done:
                        try:
                            logger.info("[send_connection_request_desktop] Activating More-menu Connect via human click")
                            if await browser.click_element_human(menu_connect, timeout=1800):
                                activation_done = True
                        except Exception:
                            pass

                    # Path 2: DOM click on the marked anchor (reliable for SPA links).
                    if not activation_done:
                        try:
                            logger.info("[send_connection_request_desktop] Human click failed, retrying DOM click on marked anchor")
                            dom_clicked = await browser.evaluate(
                                """
                                () => {
                                    const target = document.querySelector('[data-mcp-connect-menu-target="true"]');
                                    if (!target) return false;
                                    target.scrollIntoView({ block: 'center', inline: 'center' });
                                    target.click();
                                    return true;
                                }
                                """
                            )
                            if dom_clicked:
                                activation_done = True
                        except Exception:
                            pass

                    # Path 3: keyboard Enter on focused menu item.
                    if not activation_done:
                        try:
                            logger.info("[send_connection_request_desktop] DOM click failed, retrying Enter on menu item")
                            await menu_connect.focus()
                            await human.delay(180, 320)
                            await browser.page.keyboard.press("Enter")
                            activation_done = True
                        except Exception:
                            pass

                    # Path 4: navigate directly to the connect href if available.
                    if not activation_done:
                        try:
                            href = await menu_connect.get_attribute("href")
                        except Exception:
                            href = None
                        if href and "/preload/custom-invite/" in href:
                            try:
                                logger.info(f"[send_connection_request_desktop] Falling back to direct navigation: {href}")
                                await browser.navigate(href)
                                activation_done = True
                            except Exception:
                                pass

                    connect_clicked = bool(activation_done)
                    if connect_clicked:
                        # Allow LinkedIn modal animation to finish before downstream state polling.
                        await human.delay(400, 700)
            except Exception:
                connect_clicked = False
        connect_result = {
            "type": "topcard_more_menu_connect" if connect_clicked else None,
            "clicked": connect_clicked,
        }

    # Final constrained fallback: if top-card wasn't detected reliably, try direct connect only in top-card-like sections.
    if not connect_clicked and not topcard_targets.get("topcard_found"):
        connect_clicked = await _click_button_human_like(
            browser,
            human,
            selectors=[
                'section[componentkey*="topcard" i] a[href*="/preload/custom-invite/"]',
                'section[componentkey*="topcard" i] a[aria-label*="connect" i]',
                'section[componentkey*="topcard" i] button[aria-label*="connect" i]',
            ],
            text_candidates=['connect', 'invite'],
            scope_selector='section[componentkey*="topcard" i], main',
        )
        if connect_clicked:
            connect_result = {
                "type": "constrained_topcard_fallback_connect",
                "clicked": True,
            }

    if not connect_clicked:
        return {
            "status": "error",
            "message": "Could not click Connect action (direct or More menu)",
        }
    
    # Wait for "Add a note" button to appear using Playwright's wait_for_selector
    logger.info(
        f"[send_connection_request_desktop] Connect click result: {connect_result}, more_clicked: {more_clicked}, connect_clicked: {connect_clicked}"
    )
    logger.info("[send_connection_request_desktop] Waiting for invite modal / note option...")

    async def _click_add_note_in_invite_modal() -> bool:
        """Click 'Add a note' in currently visible invite modal deterministically."""
        # Fast path: direct selector clicks with built-in visibility wait.
        for selector in [
            'button[aria-label="Add a note"]',
            '[role="dialog"] button[aria-label="Add a note"]',
            '[data-test-modal-container] button[aria-label="Add a note"]',
            '.send-invite button[aria-label="Add a note"]',
        ]:
            try:
                if await browser.click_human(selector, timeout=1800):
                    await human.delay(700, 1200)
                    return True
            except Exception:
                continue

        try:
            marked = await browser.evaluate(
                """
                () => {
                    document.querySelectorAll('[data-mcp-add-note-target="true"]').forEach((node) => {
                        node.removeAttribute('data-mcp-add-note-target');
                    });

                    const isVisible = (el) => {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        if (style.display === 'none' || style.visibility === 'hidden') return false;
                        const rect = el.getBoundingClientRect();
                        return rect.width > 0 && rect.height > 0;
                    };

                    const modals = Array.from(document.querySelectorAll(
                        'div.send-invite[role="dialog"], [data-test-modal][role="dialog"], .artdeco-modal[role="dialog"], [role="dialog"]'
                    ));
                    const modal = modals.find((m) => isVisible(m));
                    if (!modal) return false;

                    const buttons = Array.from(modal.querySelectorAll('button'));
                    for (const btn of buttons) {
                        if (!isVisible(btn)) continue;
                        if (btn.hasAttribute('disabled') || btn.getAttribute('aria-disabled') === 'true') continue;
                        const label = (
                            btn.getAttribute('aria-label') ||
                            btn.getAttribute('title') ||
                            btn.innerText ||
                            btn.textContent || ''
                        ).trim().toLowerCase();
                        if (!label) continue;
                        if (label.includes('add a note') || label === 'add note' || label.includes('with a note')) {
                            btn.setAttribute('data-mcp-add-note-target', 'true');
                            return true;
                        }
                    }

                    return false;
                }
                """
            )
        except Exception:
            marked = False

        if not marked:
            return False

        try:
            add_note_btn = await browser.query_selector('[data-mcp-add-note-target="true"]')
            if add_note_btn and await browser.click_element_human(add_note_btn):
                await human.delay(700, 1200)
                return True
        except Exception:
            pass

        # Fallback: direct button targeting in visible send-invite dialog.
        try:
            clicked = await _click_button_human_like(
                browser,
                human,
                selectors=[
                    'div.send-invite[role="dialog"] button[aria-label="Add a note"]',
                    '[data-test-modal][role="dialog"] button[aria-label="Add a note"]',
                    '[role="dialog"] button[aria-label="Add a note"]',
                    '.artdeco-modal[role="dialog"] button[aria-label="Add a note"]',
                ],
                text_candidates=['add a note'],
                scope_selector='div.send-invite[role="dialog"], [data-test-modal][role="dialog"], [role="dialog"], .artdeco-modal[role="dialog"]',
            )
            if clicked:
                await human.delay(700, 1200)
                return True
        except Exception:
            pass

        # Final fallback: prompt can be rendered outside detected dialog roots.
        try:
            clicked = await _click_button_human_like(
                browser,
                human,
                selectors=[
                    'button[aria-label="Add a note"]',
                    'button[aria-label*="Add a note" i]',
                    'button:has-text("Add a note")',
                    '[role="button"][aria-label*="Add a note" i]',
                    '[role="button"]:has-text("Add a note")',
                ],
                text_candidates=['add a note'],
                scope_selector='main, [role="main"], [data-test-modal-container], [data-test-modal], body',
            )
            if clicked:
                await human.delay(700, 1200)
                return True
        except Exception:
            pass
        return False

    async def _get_invite_modal_state() -> Dict[str, bool]:
        """Collect invite modal state so transitions can stop once note modal is already open."""
        try:
            payload = await browser.evaluate(
                """
                () => {
                    const isVisible = (el) => {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        if (style.display === 'none' || style.visibility === 'hidden') return false;
                        const rect = el.getBoundingClientRect();
                        return rect.width > 0 && rect.height > 0;
                    };

                    const dialog = Array.from(document.querySelectorAll('div.send-invite[role="dialog"], [data-test-modal][role="dialog"], .artdeco-modal[role="dialog"], [role="dialog"]'))
                        .find((d) => isVisible(d)) || null;
                    if (!dialog) {
                        return {
                            modalVisible: false,
                            addNotePromptVisible: false,
                            noteModalVisible: false,
                            noteEditorVisible: false,
                            noteEditorExists: false,
                        };
                    }

                    const headerText = (
                        dialog.querySelector('h1, h2, [id*="send-invite-modal"]')?.innerText ||
                        dialog.querySelector('h1, h2, header')?.textContent ||
                        ''
                    ).trim().toLowerCase();

                    const promptButtons = Array.from(dialog.querySelectorAll('button, [role="button"]'));
                    const addNotePromptVisible = promptButtons.some((btn) => {
                        if (!isVisible(btn)) return false;
                        if (btn.hasAttribute('disabled') || btn.getAttribute('aria-disabled') === 'true') return false;
                        const label = (
                            btn.getAttribute('aria-label') ||
                            btn.getAttribute('title') ||
                            btn.innerText ||
                            btn.textContent || ''
                        ).trim().toLowerCase();
                        return label.includes('add a note');
                    });

                    const editor = dialog.querySelector(
                        'textarea#custom-message, textarea[name="message"], textarea[id*="custom-message"], textarea[placeholder*="note"], textarea[placeholder*="message"], textarea[aria-label*="note" i], textarea[aria-label*="invitation" i], div[contenteditable="true"][role="textbox"], div[contenteditable="true"]'
                    );
                    const noteEditorExists = !!editor;
                    const noteEditorVisible = isVisible(editor);
                    const noteModalVisible = headerText.includes('add a note') && headerText.includes('invitation');

                    return {
                        modalVisible: true,
                        addNotePromptVisible,
                        noteModalVisible,
                        noteEditorVisible,
                        noteEditorExists,
                    };
                }
                """
            )
            if not isinstance(payload, dict):
                return {
                    "modalVisible": False,
                    "addNotePromptVisible": False,
                    "noteModalVisible": False,
                    "noteEditorVisible": False,
                    "noteEditorExists": False,
                }
            return payload
        except Exception:
            return {
                "modalVisible": False,
                "addNotePromptVisible": False,
                "noteModalVisible": False,
                "noteEditorVisible": False,
                "noteEditorExists": False,
            }

    async def _direct_note_textarea_visible() -> bool:
        """Direct DOM check for the note editor textarea inside the open invite modal.

        This intentionally bypasses the multi-field evaluate payload to avoid silent
        failures (Trusted Types, navigation races, exec-context destruction).
        """
        textarea_selectors = (
            '[role="dialog"] textarea#custom-message',
            '[role="dialog"] textarea[name="message"]',
            '[role="dialog"] textarea[id*="custom-message"]',
            '.artdeco-modal textarea#custom-message',
            '.artdeco-modal textarea[name="message"]',
            'div.send-invite textarea#custom-message',
            'div.send-invite textarea[name="message"]',
        )
        for sel in textarea_selectors:
            try:
                handle = await browser.query_selector(sel)
                if handle is None:
                    continue
                if await handle.is_visible():
                    return True
            except Exception:
                continue
        return False

    async def _note_editor_visible() -> bool:
        # Fast, direct path first.
        if await _direct_note_textarea_visible():
            return True
        state = await _get_invite_modal_state()
        return bool(state.get("noteEditorVisible") or (state.get("noteModalVisible") and state.get("noteEditorExists")))

    invite_modal_appeared = False
    note_editor_ready = False
    add_note_clicked = False

    # Unconditional transition attempts: click "Add a note" until editor appears.
    for transition_attempt in range(1, 9):
        if await _direct_note_textarea_visible():
            note_editor_ready = True
            invite_modal_appeared = True
            logger.info("[send_connection_request_desktop] Note editor textarea visible (direct DOM); skipping Add-a-note transition")
            break

        state = await _get_invite_modal_state()
        if state.get("noteModalVisible") and state.get("noteEditorExists"):
            note_editor_ready = True
            invite_modal_appeared = True
            logger.info("[send_connection_request_desktop] Note modal already open; skipping Add-a-note transition")
            break

        if state.get("noteEditorVisible"):
            note_editor_ready = True
            invite_modal_appeared = True
            break

        clicked_add_note = await _click_add_note_in_invite_modal()
        if clicked_add_note:
            add_note_clicked = True
            invite_modal_appeared = True
        logger.info(
            f"[send_connection_request_desktop] Pre-loop transition {transition_attempt}/8, clicked_add_note={clicked_add_note}, state={state}"
        )
        await human.delay(600, 1000)

        if await _direct_note_textarea_visible():
            note_editor_ready = True
            invite_modal_appeared = True
            break

    # Poll modal state because some LinkedIn variants render it with delayed hydration.
    for modal_attempt in range(1, 9):
        if note_editor_ready:
            break
        modal_state = await _get_invite_modal_state()

        if modal_state.get("modalVisible") or modal_state.get("addNotePromptVisible") or modal_state.get("noteModalVisible"):
            invite_modal_appeared = True
            if not (modal_state.get("noteEditorVisible") or (modal_state.get("noteModalVisible") and modal_state.get("noteEditorExists"))):
                add_note_clicked = await _click_add_note_in_invite_modal()
        if modal_state.get("noteEditorVisible") or (modal_state.get("noteModalVisible") and modal_state.get("noteEditorExists")):
            note_editor_ready = True
            break

        await human.delay(600, 1000)

    if invite_modal_appeared:
        if add_note_clicked:
            logger.info("[send_connection_request_desktop] Clicked 'Add a note' option")
            await human.delay(1000, 1500)
        elif note_editor_ready:
            logger.info("[send_connection_request_desktop] Note editor already visible in invite modal")
        else:
            logger.info("[send_connection_request_desktop] Invite modal visible but note editor not ready yet")
    else:
        logger.warning("[send_connection_request_desktop] Invite modal did not appear within timeout")

        # Do not redirect/navigate away. Some variants show a 2-step UI on the current page.
        # Try to click "Add a note" globally, then wait briefly for the editor.
        try:
            add_note_global_clicked = await _click_add_note_in_invite_modal()
            if add_note_global_clicked:
                logger.info("[send_connection_request_desktop] Clicked Add a note from global fallback")
                await human.delay(800, 1200)
        except Exception:
            pass

        try:
            await browser.wait_for_selector(
                '[role="dialog"] textarea[name="message"], [role="dialog"] textarea#custom-message, [role="dialog"] textarea[id*="custom-message"], [role="dialog"] textarea[placeholder*="note"], [role="dialog"] textarea[placeholder*="message"], [role="dialog"] textarea[aria-label*="note" i], [role="dialog"] div[contenteditable="true"][role="textbox"], [role="dialog"] div[contenteditable="true"]',
                timeout=4000,
            )
        except Exception:
            pass

    # Explicit transition guard: ensure prompt modal advances to note editor modal.
    if not note_editor_ready:
        for transition_attempt in range(1, 6):
            modal_state = await _get_invite_modal_state()
            if modal_state.get("noteModalVisible") and modal_state.get("noteEditorExists"):
                note_editor_ready = True
                logger.info("[send_connection_request_desktop] Note modal detected during transition guard")
                break

            if await _note_editor_visible():
                note_editor_ready = True
                break

            clicked_add_note = await _click_add_note_in_invite_modal()
            logger.info(
                f"[send_connection_request_desktop] Transition attempt {transition_attempt}/5, clicked_add_note={clicked_add_note}"
            )
            await human.delay(700, 1300)

            if await _note_editor_visible():
                note_editor_ready = True
                break
    
    # Find and fill the note textarea/editor
    note_filled = False

    async def _type_invite_note_via_modal_focus() -> bool:
        """Type the invite note using Playwright-native click + keyboard.type.

        Avoids JS-based value mutation that triggers Ember re-renders mid-typing
        (which silently drops keystrokes by stealing focus from the textarea).
        """
        textarea_selectors = [
            '[role="dialog"] textarea#custom-message',
            '[role="dialog"] textarea[name="message"]',
            'div.send-invite textarea#custom-message',
            'div.send-invite textarea[name="message"]',
            '.artdeco-modal textarea#custom-message',
            '.artdeco-modal textarea[name="message"]',
        ]

        handle = None
        used_selector = None
        for sel in textarea_selectors:
            try:
                candidate = await browser.query_selector(sel)
                if candidate is None:
                    continue
                if not await candidate.is_visible():
                    continue
                handle = candidate
                used_selector = sel
                break
            except Exception:
                continue

        if handle is None:
            logger.info("[send_connection_request_desktop] modal-focus typer: textarea not found")
            return False

        try:
            try:
                await handle.scroll_into_view_if_needed(timeout=1500)
            except Exception:
                pass

            try:
                await handle.click(timeout=3000)
            except Exception as click_exc:
                logger.info(f"[send_connection_request_desktop] modal-focus typer: click failed ({click_exc}); falling back to focus()")
                try:
                    await handle.focus()
                except Exception:
                    return False

            await human.delay(180, 320)

            # Clear via keyboard only (Cmd/Ctrl+A then Backspace), preserves focus.
            try:
                existing = (await handle.input_value()).strip()
            except Exception:
                existing = ""
            if existing:
                try:
                    select_all = "Meta+A" if sys.platform == "darwin" else "Control+A"
                    await browser.page.keyboard.press(select_all)
                    await human.delay(60, 140)
                    await browser.page.keyboard.press("Backspace")
                    await human.delay(80, 160)
                except Exception:
                    pass

            await browser.page.keyboard.type(note, delay=human.get_typing_speed())
            await human.delay(200, 400)

            try:
                typed_value = (await handle.input_value()) or ""
            except Exception:
                typed_value = ""

            normalized_target = re.sub(r"\s+", " ", (note or "").strip())
            normalized_typed = re.sub(r"\s+", " ", typed_value.strip())

            if not normalized_typed:
                logger.info(f"[send_connection_request_desktop] modal-focus typer: nothing typed (selector={used_selector})")
                return False

            # Strict match preferred; otherwise accept if at least 80% of target was typed.
            if normalized_typed == normalized_target:
                return True
            if len(normalized_typed) >= max(1, int(len(normalized_target) * 0.8)) and normalized_typed in normalized_target:
                logger.info(
                    f"[send_connection_request_desktop] modal-focus typer: partial match accepted ({len(normalized_typed)}/{len(normalized_target)})"
                )
                return True

            logger.info(
                f"[send_connection_request_desktop] modal-focus typer: typed text mismatch (typed_len={len(normalized_typed)}, target_len={len(normalized_target)})"
            )
            return False
        except Exception as exc:
            logger.warning(f"[send_connection_request_desktop] modal-focus typer error: {exc}")
            return False

    note_selectors = [
        'textarea[name="message"]',
        'textarea#custom-message',
        'textarea[id*="custom-message"]',
        'textarea[placeholder*="note"]',
        'textarea[placeholder*="message"]',
        'textarea[aria-label*="note" i]',
        'textarea[aria-label*="invitation" i]',
        'textarea',
        'div[contenteditable="true"][role="textbox"]',
        'div[contenteditable="true"]',
    ]
    
    # Retry window for slow LinkedIn modal rendering.
    for attempt in range(1, 9):
        if attempt > 1:
            await human.delay(700, 1200)

        if await _type_invite_note_via_modal_focus():
            note_filled = True
            await human.delay(500, 1000)
            break

        # Re-attempt "Add a note" in case options render late.
        try:
            add_note_retry_clicked = await _click_add_note_in_invite_modal()
            if add_note_retry_clicked:
                logger.info(f"[send_connection_request_desktop] Retry {attempt}: clicked Add a note")
                await human.delay(700, 1200)
        except Exception:
            pass

        # 1) Try active dialog/modal scope first
        modal_roots = await browser.query_selector_all('[role="dialog"], .artdeco-modal, .artdeco-modal__content')
        for root in modal_roots:
            try:
                if not await root.is_visible():
                    continue
            except Exception:
                continue

            for selector in note_selectors:
                try:
                    candidates = await root.query_selector_all(selector)
                except Exception:
                    candidates = []
                for note_input in candidates:
                    try:
                        if not await note_input.is_visible():
                            continue
                        logger.info(f"[send_connection_request_desktop] Retry {attempt}: Found modal-scoped note input: {selector}")
                        if await _type_text_human_like(note_input, note, human, browser=browser):
                            note_filled = True
                            await human.delay(500, 1000)
                            break
                    except Exception:
                        continue
                if note_filled:
                    break
            if note_filled:
                break

        if note_filled:
            break

        # 2) Fallback to global search
        for selector in note_selectors:
            candidates = await browser.query_selector_all(selector)
            for note_input in candidates:
                try:
                    if not await note_input.is_visible():
                        continue
                    logger.info(f"[send_connection_request_desktop] Retry {attempt}: Found note input: {selector}")
                    if await _type_text_human_like(note_input, note, human, browser=browser):
                        note_filled = True
                        await human.delay(500, 1000)
                        break
                except Exception:
                    continue
            if note_filled:
                break

        if note_filled:
            break

        logger.info(f"[send_connection_request_desktop] Retry {attempt}: note editor not ready yet")
    
    if not note_filled:
        logger.error("[send_connection_request_desktop] Could not find note textarea")
        return {
            "status": "error",
            "message": "Could not find note textarea in connection modal",
        }
    
    logger.info("[send_connection_request_desktop] Note filled")
    await human.delay(500, 1000)
    
    # Click Send button using reusable helper
    logger.info("[send_connection_request_desktop] Looking for Send button...")

    send_clicked = await _click_button_human_like(
        browser,
        human,
        selectors=[
            'button[aria-label="Send invitation"]',
            'button[aria-label="Send now"]',
            '.artdeco-modal button.artdeco-button--primary:not([disabled])',
        ],
        text_candidates=['send', 'send now', 'send invitation'],
        scope_selector='.artdeco-modal, [role="dialog"]',
    )
    
    if not send_clicked:
        logger.error("[send_connection_request_desktop] Could not find Send button")
        return {
            "status": "error",
            "message": "Could not find Send button in connection modal",
        }
    
    await human.delay(2000, 3000)
    
    logger.info("[send_connection_request_desktop] Connection request sent")
    return {"status": "ok", "message": "Connection request sent"}
