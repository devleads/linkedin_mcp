"""Proxy providers for LinkedIn MCP Server."""

from typing import Any

from linkedin_mcp.config import get_settings
from linkedin_mcp.security import decrypt_envelope
from linkedin_mcp.proxy.oxylabs import (
    OxylabsProxy,
    ProxyConfig,
    ProxyNotAvailableError as OxylabsProxyNotAvailableError,
    get_proxy_provider,
)
from linkedin_mcp.proxy.ipfoxy import IPFoxyProxy, get_ipfoxy_provider
from linkedin_mcp.proxy.apify import ApifyProxy, ProxyNotAvailableError as ApifyProxyNotAvailableError, get_apify_provider


def _get_profile_proxy_config(profile: Any, provider_name: str) -> Any:
    """Return active profile proxy config row for a provider, if present."""
    proxy_configs = getattr(profile, "proxy_configs", None) or []
    for cfg in proxy_configs:
        if getattr(cfg, "provider", None) == provider_name and getattr(cfg, "is_active", True):
            return cfg
    return None


def get_proxy_dict_for_profile(profile: Any) -> dict:
    """Build provider-specific Playwright proxy dict for a DB profile object.

    The provider is selected via PROXY_PROVIDER in .env:
    - oxylabs: Uses Oxylabs mobile/residential proxies with sticky ports
    - ipfoxy: Uses IPFoxy dedicated residential proxies (per-profile credentials)
    - apify:  Uses Apify residential proxies with session-based sticky sessions

    For apify, each profile uses a fixed country (and US state if applicable)
    so the exit IP always matches the profile's fingerprint timezone.
    """
    settings = get_settings()
    provider_name = settings.proxy_provider

    if provider_name == "none":
        raise ValueError("Direct mode does not have a proxy configuration")

    if provider_name == "ipfoxy":
        provider = get_ipfoxy_provider()
        proxy_cfg = _get_profile_proxy_config(profile, "ipfoxy")
        return provider.get_proxy_dict(
            host=getattr(proxy_cfg, "host", None),
            port=getattr(proxy_cfg, "port", None),
            username=getattr(proxy_cfg, "username", None),
            password=decrypt_envelope(getattr(proxy_cfg, "password", None)),
        )

    if provider_name == "apify":
        provider = get_apify_provider()
        country = getattr(profile, "country", None)
        if not country:
            raise ApifyProxyNotAvailableError(
                "Profile is missing country for apify proxy"
            )
        # Apify uses deterministic session IDs derived from the profile UUID.
        # Same profile → same session ID → same exit IP for ~30 min.
        # Different profiles → different session IDs → different exit IPs.
        profile_uuid = getattr(profile, "uuid", None) or str(getattr(profile, "id", ""))
        return provider.get_proxy_dict(
            country=country,
            profile_uuid=profile_uuid,
            state=getattr(profile, "state", None),
        )

    # Default: oxylabs
    provider = get_proxy_provider()
    country = getattr(profile, "country", None)
    if not country:
        raise OxylabsProxyNotAvailableError("Profile is missing country for oxylabs proxy")

    profile_port = getattr(profile, "proxy_port", None)
    if profile_port is None:
        raise OxylabsProxyNotAvailableError(
            "Profile is missing its persisted Oxylabs sticky port"
        )
    return provider.get_proxy_dict(
        country,
        profile_port,
        state=getattr(profile, "state", None),
        city=getattr(profile, "city", None),
    )


def get_active_proxy_provider_name() -> str:
    """Return configured proxy provider name from settings."""
    return get_settings().proxy_provider


__all__ = [
    "OxylabsProxy",
    "ProxyConfig",
    "IPFoxyProxy",
    "ApifyProxy",
    "get_proxy_dict_for_profile",
    "get_active_proxy_provider_name",
]
