"""Challenge lock helpers for tool dispatch and cooldown enforcement."""

from typing import Any, Optional


_CHALLENGE_TERMS = {
    "checkpoint": "checkpoint",
    "captcha": "captcha",
    "challenge": "challenge",
    "auth wall": "authwall",
    "authwall": "authwall",
    "contextual-sign-in": "authwall",
    "sign in to view more content": "authwall",
    "not logged in": "authwall",
    "login": "authwall",
    "two-step": "verification",
    "2fa": "verification",
    "verification": "verification",
}


def classify_challenge_signal(message: str) -> Optional[str]:
    """Classify challenge signal from an error/status message."""
    text = (message or "").strip().lower()
    if not text:
        return None

    for term, signal in _CHALLENGE_TERMS.items():
        if term in text:
            return signal
    return None


def extract_challenge_event_from_result(result: Any) -> Optional[dict]:
    """Extract normalized challenge event payload from a handler result dict."""
    if not isinstance(result, dict):
        return None

    if result.get("status") == "skipped" and result.get("challenge_lock"):
        return None

    message = str(result.get("message", ""))
    signal = classify_challenge_signal(message)
    if not signal:
        return None

    details = result.get("details")
    page_url = None
    if isinstance(details, dict):
        page_url = details.get("current_url") or details.get("url")
    if not page_url:
        page_url = result.get("current_url")

    return {
        "signal": signal,
        "reason": message or f"Detected {signal} signal",
        "page_url": page_url,
        "details": details if isinstance(details, dict) else None,
    }


def build_challenge_lock_response(profile_id: str, lock_data: dict) -> dict:
    """Return standardized response when a profile is inside challenge cooldown."""
    remaining_minutes = lock_data.get("remaining_minutes")
    return {
        "status": "skipped",
        "profile_id": profile_id,
        "message": (
            "Skipped due to recent LinkedIn challenge/auth-wall signal. "
            f"Retry after cooldown ({remaining_minutes} min remaining)."
        ),
        "challenge_lock": lock_data,
    }
