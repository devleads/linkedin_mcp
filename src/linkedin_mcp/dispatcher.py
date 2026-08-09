"""Tool dispatcher for LinkedIn MCP.

Shared dispatcher used by both MCP server (stdio) and HTTP server.
This eliminates code duplication between server.py and http_server.py.
"""

from contextlib import asynccontextmanager
from typing import Any, List

from linkedin_mcp.browser.session import get_session_manager
from linkedin_mcp.challenge_lock import (
    build_challenge_lock_response,
    extract_challenge_event_from_result,
)
from linkedin_mcp.config import get_settings
from linkedin_mcp.db import get_db
from linkedin_mcp.db.repository import ProfileRepository, ChallengeEventRepository
from linkedin_mcp.tools import auth, feed, profile, messages


# Tool registry - maps tool names to their handlers and argument specs
TOOLS = {
    "set_cookies": {
        "handler": auth.set_cookies,
        "required": ["profile_id", "li_at"],
        "optional": {"jsessionid": None, "cookies": None},
        "auth_recovery": False,
    },
    "login": {
        "handler": auth.login,
        "required": ["profile_id"],
        "optional": {"email": None, "password": None, "totp_code": None},
        "auth_recovery": False,
    },
    "get_session_status": {
        "handler": auth.get_session_status,
        "required": ["profile_id"],
        "optional": {},
        "auth_recovery": False,
    },
    "open_manual_browser": {
        "handler": auth.open_manual_browser,
        "required": ["profile_id"],
        "optional": {"url": None},
        "auth_recovery": False,
    },
    "save_session_cookies": {
        "handler": auth.save_session_cookies,
        "required": ["profile_id"],
        "optional": {},
        "auth_recovery": False,
    },
    "close_session": {
        "handler": auth.close_session,
        "required": ["profile_id"],
        "optional": {},
        "auth_recovery": False,
    },
    "read_feed": {
        "handler": feed.read_feed,
        "required": ["profile_id"],
        "optional": {"max_posts": 10, "scroll_count": 3},
        "auth_recovery": True,
    },
    "get_profile": {
        "handler": profile.get_profile,
        "required": ["profile_id", "linkedin_url"],
        "optional": {"include_activity": False, "max_posts": 5},
        "auth_recovery": True,
    },
    "get_company": {
        "handler": profile.get_company,
        "required": ["profile_id", "company_url"],
        "optional": {},
        "auth_recovery": True,
    },
    "search_people": {
        "handler": profile.search_people,
        "required": ["profile_id", "keywords"],
        "optional": {"country": None, "connection_degree": None, "page": 1, "max_results": 10},
        "auth_recovery": True,
    },
    "search_posts": {
        "handler": feed.search_posts,
        "required": ["profile_id", "keywords"],
        "optional": {"max_posts": 10, "scroll_count": 3},
        "auth_recovery": True,
    },
    "get_post": {
        "handler": feed.get_post,
        "required": ["profile_id", "post_url"],
        "optional": {},
        "auth_recovery": True,
    },
    "like_post": {
        "handler": feed.like_post,
        "required": ["profile_id", "post_url"],
        "optional": {},
        "auth_recovery": True,
    },
    "comment_post": {
        "handler": feed.comment_post,
        "required": ["profile_id", "post_url", "comment_text"],
        "optional": {},
        "auth_recovery": True,
    },
    "like_and_comment_post": {
        "handler": feed.like_and_comment_post,
        "required": ["profile_id", "post_url", "comment_text"],
        "optional": {},
        "auth_recovery": True,
    },
    "read_messages": {
        "handler": messages.read_messages,
        "required": ["profile_id"],
        "optional": {"max_conversations": 0, "max_messages_per_conversation": 20},
        "auth_recovery": True,
    },
    "send_message": {
        "handler": messages.send_message,
        "required": ["profile_id", "recipient_url", "message"],
        "optional": {},
        "auth_recovery": True,
    },
    "send_inbox_message": {
        "handler": messages.send_inbox_message,
        "required": ["profile_id", "message"],
        "optional": {
            "conversation_id": None,
            "participant_profile_url": None,
            "existing_thread_only": True,
        },
        "auth_recovery": True,
    },
    "send_connection_request": {
        "handler": messages.send_connection_request,
        "required": ["profile_id", "recipient_url"],
        "optional": {"note": None},
        "auth_recovery": True,
    },
    "create_post": {
        "handler": feed.create_post,
        "required": ["profile_id", "content"],
        "optional": {"image_path": None},
        "auth_recovery": True,
    },
    "create_company_post": {
        "handler": feed.create_company_post,
        "required": ["profile_id", "company_url", "content"],
        "optional": {"image_path": None},
        "auth_recovery": True,
    },
}


def get_tool_names() -> List[str]:
    """Get list of available tool names."""
    return list(TOOLS.keys())


@asynccontextmanager
async def _noop_operation_guard():
    """No-op guard for tools that do not need session operation protection."""
    yield


def _is_auth_related_error(result: Any) -> bool:
    """Return True when tool result indicates auth/login wall problem."""
    if not isinstance(result, dict):
        return False
    if result.get("status") != "error":
        return False

    code = str(result.get("code") or "").lower()
    if code in {"auth_required", "login_required", "authwall"}:
        return True

    details = result.get("details") if isinstance(result.get("details"), dict) else {}
    current_url = str(details.get("current_url") or "").lower()
    if any(token in current_url for token in ["/login", "authwall", "login-submit"]):
        return True

    message = str(result.get("message") or "").lower()
    indicators = [
        "not logged in",
        "not authenticated",
        "please login",
        "auth required",
        "auth wall",
        "authwall",
        "sign in",
        "login first",
        "login page",
        "redirected to login",
        "err_too_many_redirects",
        "too many redirects",
        "cookies may be invalid",
        "cookies may be invalid or expired",
        "session may be invalid",
    ]
    return any(token in message for token in indicators)


def _needs_auth_recovery(tool: dict[str, Any], profile_id: Any) -> bool:
    """Determine whether this tool should use centralized auth recovery."""
    if not profile_id:
        return False
    return bool(tool.get("auth_recovery", True))


def _is_fatal_session_error(result: Any) -> bool:
    """Return True when error indicates browser session should be force-closed."""
    if not isinstance(result, dict):
        return False
    if result.get("status") != "error":
        return False

    message = str(result.get("message") or "").lower()
    indicators = [
        "err_tunnel_connection_failed",
        "tunnel connection failed",
        "err_proxy_connection_failed",
        "err_connection_reset",
        "err_network_changed",
        "target page, context or browser has been closed",
        "page.goto",
    ]
    return any(token in message for token in indicators)


def _get_active_lock_for_profile(profile_db_id: int, db=None):
    """Fetch active challenge cooldown lock for profile DB id."""
    settings = get_settings()
    if db is not None:
        challenge_repo = ChallengeEventRepository(db)
        return challenge_repo.get_active_lock(
            profile_id=profile_db_id,
            cooldown_minutes=settings.challenge_cooldown_minutes,
        )

    with get_db() as local_db:
        challenge_repo = ChallengeEventRepository(local_db)
        return challenge_repo.get_active_lock(
            profile_id=profile_db_id,
            cooldown_minutes=settings.challenge_cooldown_minutes,
        )


async def dispatch_tool(name: str, arguments: dict[str, Any]) -> dict:
    """Dispatch tool call to appropriate handler.
    
    Args:
        name: Tool name
        arguments: Tool arguments
    
    Returns:
        Tool result as dict
    """
    if name not in TOOLS:
        return {
            "status": "error",
            "message": f"Unknown tool: {name}",
        }
    
    tool = TOOLS[name]
    handler = tool["handler"]
    
    # Build kwargs from required and optional arguments
    kwargs = {}
    
    # Add required arguments
    for arg in tool["required"]:
        if arg not in arguments:
            return {
                "status": "error",
                "message": f"Missing required argument: {arg}",
            }
        kwargs[arg] = arguments[arg]
    
    # Add optional arguments with defaults
    for arg, default in tool["optional"].items():
        kwargs[arg] = arguments.get(arg, default)
    
    profile_id = kwargs.get("profile_id")
    profile_db_id = None

    if profile_id:
        with get_db() as db:
            profile_repo = ProfileRepository(db)
            profile_row = profile_repo.get_by_uuid(profile_id)
            if profile_row:
                profile_db_id = profile_row.id
                active_lock = _get_active_lock_for_profile(profile_db_id, db)
                if active_lock:
                    return build_challenge_lock_response(profile_id=profile_id, lock_data=active_lock)

    operation_guard = (
        get_session_manager().operation_guard(profile_id)
        if profile_id and name != "close_session"
        else _noop_operation_guard()
    )

    result: Any = None

    async with operation_guard:
        try:
            result = await handler(**kwargs)
        except Exception as exc:
            result = {
                "status": "error",
                "message": str(exc),
            }

        if _needs_auth_recovery(tool, profile_id) and _is_auth_related_error(result):
            if profile_db_id is not None:
                active_lock = _get_active_lock_for_profile(profile_db_id)
                if active_lock:
                    return build_challenge_lock_response(profile_id=profile_id, lock_data=active_lock)

            login_result = await auth.ensure_logged_in(profile_id=profile_id)
            if isinstance(login_result, dict) and login_result.get("status") == "ok":
                try:
                    result = await handler(**kwargs)
                except Exception as exc:
                    result = {
                        "status": "error",
                        "message": str(exc),
                    }
            else:
                login_message = (
                    login_result.get("message") if isinstance(login_result, dict) else str(login_result)
                ) or "Login failed"
                return {
                    "status": "error",
                    "message": f"Auth recovery failed: {login_message}",
                }

    if profile_id and name != "close_session" and _is_fatal_session_error(result):
        try:
            await get_session_manager().close_session(profile_id, force=True)
        except Exception:
            pass

    if profile_db_id is not None:
        challenge_event = extract_challenge_event_from_result(result)
        if challenge_event:
            with get_db() as db:
                challenge_repo = ChallengeEventRepository(db)
                challenge_repo.record_event(
                    profile_id=profile_db_id,
                    source_tool=name,
                    signal=challenge_event["signal"],
                    reason=challenge_event["reason"],
                    page_url=challenge_event.get("page_url"),
                    details=challenge_event.get("details"),
                )

    return result
