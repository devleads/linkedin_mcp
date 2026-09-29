"""Immutable network route passed to the browser runtime."""

from dataclasses import dataclass
from typing import Literal, Optional


@dataclass(frozen=True)
class NetworkRoute:
    """One direct or proxied route for the lifetime of a browser session."""

    kind: Literal["direct", "proxy"]
    provider: Literal["none", "oxylabs", "ipfoxy", "apify"]
    route_identity: str
    server: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    country: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None

    def as_browser_proxy(self) -> Optional[dict[str, str]]:
        """Return Patchright proxy configuration without exposing it in repr/logs."""
        if self.kind == "direct":
            return None
        if not self.server:
            raise ValueError("Proxy route has no server")
        proxy = {"server": self.server}
        if self.username is not None:
            proxy["username"] = self.username
        if self.password is not None:
            proxy["password"] = self.password
        return proxy

    def __repr__(self) -> str:
        return (
            "NetworkRoute("
            f"kind={self.kind!r}, provider={self.provider!r}, "
            f"route_identity={self.route_identity!r}, country={self.country!r})"
        )
