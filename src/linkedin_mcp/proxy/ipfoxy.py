"""IPFoxy dedicated residential proxy provider."""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


class ProxyNotAvailableError(Exception):
    """Raised when required proxy configuration is missing."""


@dataclass
class IPFoxyProxyConfig:
    """Per-profile IPFoxy dedicated residential proxy configuration."""

    server: str
    username: Optional[str]
    password: Optional[str]
    host: str
    port: int


class IPFoxyProxy:
    """Builds Playwright proxy config from profile-level dedicated IPFoxy credentials."""

    provider_name = "ipfoxy"

    @staticmethod
    def get_proxy(
        host: Optional[str],
        port: Optional[int],
        username: Optional[str],
        password: Optional[str],
    ) -> IPFoxyProxyConfig:
        if not host:
            raise ProxyNotAvailableError("Profile is missing ipfoxy_host")
        raw_host = host.strip()
        scheme = "http"

        # Accept host values like:
        # - "179.61.157.188"
        # - "socks5://179.61.157.188"
        # - "socks5://179.61.157.188:45001:aFh...:Nzi..."
        if "://" in raw_host:
            parsed_scheme, raw_host = raw_host.split("://", 1)
            if parsed_scheme:
                scheme = parsed_scheme.lower()

        parts = raw_host.split(":")
        if len(parts) >= 4:
            host = parts[0]
            port = int(parts[1])
            username = username or parts[2]
            password = password or ":".join(parts[3:])
        elif len(parts) == 2 and port is None:
            host = parts[0]
            port = int(parts[1])
        else:
            host = raw_host

        if not port:
            raise ProxyNotAvailableError("Profile is missing ipfoxy_port")
        if not username:
            raise ProxyNotAvailableError("Profile is missing ipfoxy_username")
        if not password:
            raise ProxyNotAvailableError("Profile is missing ipfoxy_password")

        if scheme.startswith("socks"):
            # Chromium/Patchright does not reliably support SOCKS5 auth for browser contexts.
            # Keep an explicit error so users can switch IPFoxy protocol to HTTP in dashboard
            # (or use an allowlisted/no-auth SOCKS endpoint if available).
            raise ProxyNotAvailableError(
                "IPFoxy SOCKS5 with username/password is not supported by current browser stack. "
                "Switch this dedicated proxy to HTTP protocol in IPFoxy and keep host/port/user/pass."
            )

        server = f"{scheme}://{host}:{int(port)}"
        out_username = str(username)
        out_password = str(password)

        logger.info(f"[proxy] ipfoxy dedicated proxy via {scheme}://{host}:{int(port)}")
        return IPFoxyProxyConfig(
            server=server,
            username=out_username,
            password=out_password,
            host=host,
            port=int(port),
        )

    def get_proxy_dict(
        self,
        host: Optional[str],
        port: Optional[int],
        username: Optional[str],
        password: Optional[str],
    ) -> dict:
        config = self.get_proxy(host, port, username, password)
        return {
            "server": config.server,
            "username": config.username,
            "password": config.password,
        }


_ipfoxy_provider: Optional[IPFoxyProxy] = None


def get_ipfoxy_provider() -> IPFoxyProxy:
    """Get singleton IPFoxy provider."""
    global _ipfoxy_provider
    if _ipfoxy_provider is None:
        _ipfoxy_provider = IPFoxyProxy()
    return _ipfoxy_provider
