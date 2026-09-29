"""Stable error codes and sanitized error response construction."""

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    AUTH_REQUIRED = "AUTH_REQUIRED"
    CHALLENGE_DETECTED = "CHALLENGE_DETECTED"
    PAGE_NOT_READY = "PAGE_NOT_READY"
    PAGE_STATE_UNKNOWN = "PAGE_STATE_UNKNOWN"
    SELECTOR_DRIFT = "SELECTOR_DRIFT"
    AMBIGUOUS_TARGET = "AMBIGUOUS_TARGET"
    POSTCONDITION_FAILED = "POSTCONDITION_FAILED"
    NETWORK_ROUTE_FAILED = "NETWORK_ROUTE_FAILED"
    SESSION_CLOSED = "SESSION_CLOSED"
    BROWSER_START_FAILED = "BROWSER_START_FAILED"
    INVALID_REQUEST = "INVALID_REQUEST"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    ACTIVITY_LIMITED = "ACTIVITY_LIMITED"
    UNKNOWN_WRITE_OUTCOME = "UNKNOWN_WRITE_OUTCOME"
    DUPLICATE_ACTION = "DUPLICATE_ACTION"


def error_result(code: ErrorCode, message: str, **details: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"status": "error", "code": code.value, "message": message}
    if details:
        result["details"] = details
    return result
