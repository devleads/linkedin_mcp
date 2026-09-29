"""Configurable per-profile activity budgets with no claimed safe schedule."""

from collections import defaultdict, deque
import time
from typing import Literal

from linkedin_mcp.config import Settings, get_settings


class ActivityPolicy:
    """Bound bursts in one process; profile serialization remains authoritative."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._events: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def allow(self, profile_id: str, effect: Literal["read", "write"]) -> bool:
        limit = (
            self.settings.max_profile_write_actions_per_hour
            if effect == "write"
            else self.settings.max_profile_read_actions_per_hour
        )
        if limit == 0:
            return True
        now = time.monotonic()
        events = self._events[(profile_id, effect)]
        cutoff = now - 3600
        while events and events[0] <= cutoff:
            events.popleft()
        if len(events) >= limit:
            return False
        events.append(now)
        return True


_policy: ActivityPolicy | None = None


def get_activity_policy() -> ActivityPolicy:
    global _policy
    if _policy is None:
        _policy = ActivityPolicy()
    return _policy
