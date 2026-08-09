"""Apify residential proxy provider.

Uses Apify's proxy URL format for residential proxy sessions with
sticky session support and country/state targeting.

Apify proxy URL format:
    http://<username>:<password>@proxy.apify.com:8000

Username tokens (comma-separated):
    groups-RESIDENTIAL             — residential proxy group
    session-<id>                   — sticky session (same IP for ~30 min)
    country-<CC>                   — ISO-2 country code
    state-<state>                  — US state targeting (e.g., california)

Session persistence: the session ID is deterministic per profile (derived
from the profile UUID). This means:
- Same profile always gets the same session ID → same exit IP for ~30 min
- Different profiles get different session IDs → different exit IPs
- No DB migration or state persistence needed
- If a session expires on Apify's side (~30 min idle), the same session ID
  will be assigned a new IP, maintaining the per-profile isolation

Each profile uses a fixed country (and state for US) so the exit IP
always matches the profile's fingerprint timezone and locale.
"""

import hashlib
import logging
from dataclasses import dataclass
from typing import Optional

from linkedin_mcp.config import get_settings

logger = logging.getLogger(__name__)


# Apify residential proxy server endpoint.
APIFY_PROXY_SERVER = "http://proxy.apify.com:8000"


class ProxyNotAvailableError(Exception):
    """Raised when required Apify proxy configuration is missing."""


@dataclass
class ApifyProxyConfig:
    """Apify residential proxy configuration for a single profile."""

    server: str
    username: str
    password: str
    country: Optional[str] = None
    state: Optional[str] = None
    session_id: Optional[str] = None


def _profile_session_id(profile_uuid: str) -> str:
    """Generate a deterministic session ID from a profile UUID.

    The session ID is derived from a SHA-256 hash of the profile UUID,
    truncated to 16 hex characters. This ensures:
    - Same profile → same session ID → same exit IP for ~30 min
    - Different profiles → different session IDs → different exit IPs
    - No state persistence needed (deterministic from profile UUID)

    Args:
        profile_uuid: The profile's UUID string.

    Returns:
        A 16-character hex session ID string.
    """
    digest = hashlib.sha256(profile_uuid.encode("utf-8")).hexdigest()
    return digest[:16]


def _normalize_state(state: Optional[str]) -> Optional[str]:
    """Normalize US state to Apify token format (e.g., 'New York' -> 'new_york')."""
    if not state:
        return None
    normalized = state.strip().lower().replace(" ", "_")
    return normalized or None


class ApifyProxy:
    """Apify residential proxy provider with sticky sessions and geo-targeting.

    Each profile gets a deterministic session ID (derived from its UUID)
    so the same exit IP is reused across browser sessions within Apify's
    ~30-min session lifetime. Country (and optionally US state) are fixed
    per profile to match the profile's fingerprint timezone and locale.
    """

    provider_name = "apify"

    def __init__(self) -> None:
        self.settings = get_settings()
        self._validate_config()

    def _validate_config(self) -> None:
        """Validate that Apify proxy password is configured."""
        if not self.settings.apify_proxy_password:
            raise ProxyNotAvailableError(
                "APIFY_PROXY_PASSWORD is required when PROXY_PROVIDER=apify"
            )

    def get_proxy(
        self,
        country: str,
        profile_uuid: str,
        state: Optional[str] = None,
    ) -> ApifyProxyConfig:
        """Build Apify proxy config for a profile.

        Args:
            country: ISO-2 country code (e.g., "US", "GB", "AE").
            profile_uuid: The profile's UUID — used to derive a deterministic
                          session ID so the same profile always gets the same
                          exit IP for ~30 min.
            state: Optional US state name (e.g., "California", "New York").
                   Only applied for US profiles.

        Returns:
            ApifyProxyConfig with server, username, password, and geo info.

        Raises:
            ProxyNotAvailableError: If configuration is missing.
        """
        self._validate_config()

        country_upper = country.upper()
        normalized_state = _normalize_state(state) if country_upper == "US" else None

        # Derive a deterministic session ID from the profile UUID.
        # Same profile → same session → same IP for ~30 min.
        # Different profiles → different sessions → different IPs.
        session = _profile_session_id(profile_uuid)

        # Build Apify username token string.
        # Format: groups-RESIDENTIAL,session-<id>,country-<CC>[,state-<state>]
        group = self.settings.apify_proxy_groups or "RESIDENTIAL"
        tokens = [f"groups-{group}", f"session-{session}", f"country-{country_upper}"]
        if normalized_state:
            tokens.append(f"state-{normalized_state}")

        username = ",".join(tokens)

        logger.info(
            f"[proxy] apify residential session: {country_upper}"
            f"{f'-{normalized_state}' if normalized_state else ''}"
            f" via {APIFY_PROXY_SERVER} (session={session})"
        )

        return ApifyProxyConfig(
            server=APIFY_PROXY_SERVER,
            username=username,
            password=self.settings.apify_proxy_password,
            country=country_upper,
            state=normalized_state,
            session_id=session,
        )

    def get_proxy_dict(
        self,
        country: str,
        profile_uuid: str,
        state: Optional[str] = None,
    ) -> dict:
        """Get proxy as dictionary for Playwright/Patchright.

        Args:
            country: ISO-2 country code.
            profile_uuid: Profile UUID for deterministic session ID.
            state: Optional US state name.

        Returns:
            Dictionary with server, username, password keys.
        """
        config = self.get_proxy(country, profile_uuid=profile_uuid, state=state)
        return {
            "server": config.server,
            "username": config.username,
            "password": config.password,
        }


# Singleton instance
_apify_provider: Optional[ApifyProxy] = None


def get_apify_provider() -> ApifyProxy:
    """Get singleton Apify proxy provider."""
    global _apify_provider
    if _apify_provider is None:
        _apify_provider = ApifyProxy()
    return _apify_provider
