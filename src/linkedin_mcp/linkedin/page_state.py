"""Central deterministic classification for LinkedIn page states."""

from enum import StrEnum
from urllib.parse import urlparse

from linkedin_mcp.linkedin.observation import PageObservation


class PageState(StrEnum):
    READY_FEED = "READY_FEED"
    READY_PROFILE = "READY_PROFILE"
    READY_COMPANY = "READY_COMPANY"
    READY_SEARCH = "READY_SEARCH"
    READY_MESSAGING = "READY_MESSAGING"
    READY_POST = "READY_POST"
    LOGIN = "LOGIN"
    AUTH_WALL = "AUTH_WALL"
    CHECKPOINT = "CHECKPOINT"
    CAPTCHA = "CAPTCHA"
    RATE_LIMIT = "RATE_LIMIT"
    TRANSIENT_ERROR = "TRANSIENT_ERROR"
    UNKNOWN = "UNKNOWN"


def classify_page_state(observation: PageObservation) -> PageState:
    """Classify stop states before ordinary application layouts."""
    parsed = urlparse(observation.url)
    path = parsed.path.lower()
    text = " ".join(
        [observation.title, observation.visible_text, *observation.headings]
    ).lower()

    if "captcha" in path or "captcha" in text:
        return PageState.CAPTCHA
    if "/checkpoint" in path or "security verification" in text:
        return PageState.CHECKPOINT
    if "authwall" in path or "join linkedin" in text:
        return PageState.AUTH_WALL
    if "/login" in path or "/uas/login" in path:
        return PageState.LOGIN
    if "too many requests" in text or "rate limit" in text:
        return PageState.RATE_LIMIT
    if "temporarily unavailable" in text or "something went wrong" in text:
        return PageState.TRANSIENT_ERROR
    if "/messaging" in path:
        return PageState.READY_MESSAGING
    if "/company/" in path:
        return PageState.READY_COMPANY
    if "/in/" in path:
        return PageState.READY_PROFILE
    if "/search/" in path:
        return PageState.READY_SEARCH
    if "/posts/" in path or "/feed/update/" in path:
        return PageState.READY_POST
    if path in {"/", "/feed", "/feed/"} or path.startswith("/feed/"):
        return PageState.READY_FEED
    return PageState.UNKNOWN
