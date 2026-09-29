"""Resolve an explicit direct or fail-closed proxy route."""

import hashlib
import hmac
import os
from typing import Any

from linkedin_mcp.config import Settings, get_settings
from linkedin_mcp.network.models import NetworkRoute
from linkedin_mcp.proxy import get_proxy_dict_for_profile


class NetworkRouteError(RuntimeError):
    """The configured network route could not be resolved safely."""


_PROCESS_HMAC_KEY = os.urandom(32)


class NetworkRouteResolver:
    """Build a complete immutable route; named providers never fail open."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def resolve(self, profile: Any) -> NetworkRoute:
        provider = self.settings.proxy_provider
        if provider == "none":
            return NetworkRoute(
                kind="direct",
                provider="none",
                route_identity=self._identity("direct"),
                country=getattr(profile, "country", None),
                state=getattr(profile, "state", None),
                city=getattr(profile, "city", None),
            )

        try:
            proxy = get_proxy_dict_for_profile(profile)
        except Exception as exc:
            raise NetworkRouteError(f"Unable to resolve configured {provider} route") from exc

        server = proxy.get("server")
        if not server:
            raise NetworkRouteError(f"Configured {provider} route returned no server")

        # Credentials affect route identity but are never retained in the digest input
        # after this method returns or exposed in logs/repr.
        material = "\x1f".join(
            str(value or "")
            for value in (
                provider,
                server,
                proxy.get("username"),
                proxy.get("password"),
                getattr(profile, "country", None),
                getattr(profile, "state", None),
                getattr(profile, "city", None),
            )
        )
        return NetworkRoute(
            kind="proxy",
            provider=provider,
            route_identity=self._identity(material),
            server=server,
            username=proxy.get("username"),
            password=proxy.get("password"),
            country=getattr(profile, "country", None),
            state=getattr(profile, "state", None),
            city=getattr(profile, "city", None),
        )

    def _identity(self, material: str) -> str:
        configured = self.settings.linkedin_credential_encryption_key.encode("utf-8")
        key = configured or _PROCESS_HMAC_KEY
        return hmac.new(key, material.encode("utf-8"), hashlib.sha256).hexdigest()
