"""Oxylabs proxy provider for LinkedIn MCP Server.

Uses Oxylabs Sticky Proxy Entry Nodes for consistent IP sessions.
Each profile has a dedicated port stored in the database, ensuring the same IP for up to 10 minutes.
After 10 minutes, Oxylabs automatically rotates to a new IP on the same port.

Architecture:
- Profile stores proxy_port in database
- Same port = same IP for 10 minutes (sticky session)
- Country-specific entry points by mode (mobile / residentials)

Reference: https://developers.oxylabs.io/proxies/mobile-proxies/session-control/sticky-proxy-entry-nodes
"""

import logging
import random
from dataclasses import dataclass
from typing import Optional, Tuple, Dict

from linkedin_mcp.config import get_settings

logger = logging.getLogger(__name__)


DEFAULT_RESIDENTIAL_ENTRY_PORT = 7777


# Oxylabs Residential random entry ports by country (fallback is RANDOM default).
# Format: country -> (host, port)
RESIDENTIAL_ENTRY_NODES: Dict[str, Tuple[str, int]] = {
    "US": ("us-pr.oxylabs.io", 10000),
    "CA": ("ca-pr.oxylabs.io", 30000),
    "GB": ("gb-pr.oxylabs.io", 20000),
    "DE": ("de-pr.oxylabs.io", 30000),
    "FR": ("fr-pr.oxylabs.io", 40000),
    "ES": ("es-pr.oxylabs.io", 10000),
    "IT": ("it-pr.oxylabs.io", 20000),
    "NL": ("nl-pr.oxylabs.io", 20000),
    "SE": ("se-pr.oxylabs.io", 30000),
    "TR": ("tr-pr.oxylabs.io", 30000),
    "AU": ("au-pr.oxylabs.io", 40000),
    "JP": ("jp-pr.oxylabs.io", 40000),
    "KR": ("kr-pr.oxylabs.io", 30000),
    "SG": ("sg-pr.oxylabs.io", 20000),
    "HK": ("hk-pr.oxylabs.io", 40000),
    "IN": ("in-pr.oxylabs.io", 20000),
    "AE": ("ae-pr.oxylabs.io", 40000),
    "MX": ("mx-pr.oxylabs.io", 10000),
    "BR": ("br-pr.oxylabs.io", 20000),
    "AR": ("ar-pr.oxylabs.io", 30000),
    "CL": ("cl-pr.oxylabs.io", 40000),
    "PE": ("pe-pr.oxylabs.io", 10000),
    "CO": ("co-pr.oxylabs.io", 30000),
    "ZA": ("za-pr.oxylabs.io", 40000),
    "EG": ("eg-pr.oxylabs.io", 10000),
    "EU": ("eu-pr.oxylabs.io", 10000),
    "RANDOM": ("pr.oxylabs.io", 7777),
}


class ProxyNotAvailableError(Exception):
    """Raised when proxy is required but not available."""
    pass


@dataclass
class ProxyConfig:
    """Proxy configuration for browser."""
    server: str  # e.g., "http://us-pr.oxylabs.io:10001"
    username: str
    password: str
    country: str
    port: int  # Sticky port for this session
    mode: str


# Oxylabs Sticky Proxy Entry Nodes - Country to (host, port_start, port_end)
# Reference: https://developers.oxylabs.io/proxies/mobile-proxies/session-control/sticky-proxy-entry-nodes
STICKY_ENTRY_NODES = {
    # Major countries
    "US": ("us-pr.oxylabs.io", 10001, 19999),
    "GB": ("gb-pr.oxylabs.io", 20001, 29999),
    "CA": ("ca-pr.oxylabs.io", 30001, 39999),
    "DE": ("de-pr.oxylabs.io", 30001, 39999),
    "FR": ("fr-pr.oxylabs.io", 40001, 49999),
    "ES": ("es-pr.oxylabs.io", 10001, 19999),
    "IT": ("it-pr.oxylabs.io", 20001, 29999),
    "NL": ("nl-pr.oxylabs.io", 20001, 29999),
    "AU": ("au-pr.oxylabs.io", 40001, 49999),
    "JP": ("jp-pr.oxylabs.io", 40001, 49999),
    "KR": ("kr-pr.oxylabs.io", 30001, 39999),
    "IN": ("in-pr.oxylabs.io", 20001, 29999),
    "BR": ("br-pr.oxylabs.io", 20001, 29999),
    "MX": ("mx-pr.oxylabs.io", 10001, 19999),
    
    # Middle East
    "AE": ("ae-pr.oxylabs.io", 40001, 49999),
    "SA": ("sa-pr.oxylabs.io", 44001, 44999),
    "IL": ("il-pr.oxylabs.io", 20001, 29999),
    "TR": ("tr-pr.oxylabs.io", 30001, 39999),
    "QA": ("qa-pr.oxylabs.io", 43001, 43999),
    "BH": ("bh-pr.oxylabs.io", 29001, 29999),
    "OM": ("om-pr.oxylabs.io", 42001, 42999),
    "JO": ("jo-pr.oxylabs.io", 38001, 38999),
    "LB": ("lb-pr.oxylabs.io", 39001, 39999),
    "IQ": ("iq-pr.oxylabs.io", 37001, 37999),
    "IR": ("ir-pr.oxylabs.io", 40001, 49999),
    "EG": ("eg-pr.oxylabs.io", 10001, 19999),
    
    # Asia Pacific
    "SG": ("sg-pr.oxylabs.io", 20001, 29999),
    "HK": ("hk-pr.oxylabs.io", 40001, 49999),
    "TW": ("tw-pr.oxylabs.io", 10001, 19999),
    "CN": ("cn-pr.oxylabs.io", 30001, 39999),
    "MY": ("my-pr.oxylabs.io", 10001, 19999),
    "TH": ("th-pr.oxylabs.io", 20001, 29999),
    "PH": ("ph-pr.oxylabs.io", 10001, 19999),
    "ID": ("id-pr.oxylabs.io", 10001, 19999),
    "PK": ("pk-pr.oxylabs.io", 30001, 39999),
    "BD": ("bd-pr.oxylabs.io", 30001, 30999),
    "NZ": ("nz-pr.oxylabs.io", 15001, 15999),
    
    # Europe
    "SE": ("se-pr.oxylabs.io", 30001, 39999),
    "NO": ("no-pr.oxylabs.io", 34001, 34999),
    "DK": ("dk-pr.oxylabs.io", 19001, 19999),
    "FI": ("fi-pr.oxylabs.io", 21001, 21999),
    "PL": ("pl-pr.oxylabs.io", 20001, 29999),
    "AT": ("at-pr.oxylabs.io", 11001, 11999),
    "CH": ("ch-pr.oxylabs.io", 39001, 39999),
    "BE": ("be-pr.oxylabs.io", 30001, 39999),
    "PT": ("pt-pr.oxylabs.io", 10001, 19999),
    "GR": ("gr-pr.oxylabs.io", 40001, 49999),
    "IE": ("ie-pr.oxylabs.io", 25001, 25999),
    "CZ": ("cz-pr.oxylabs.io", 18001, 18999),
    "HU": ("hu-pr.oxylabs.io", 23001, 23999),
    "RO": ("ro-pr.oxylabs.io", 35001, 35999),
    "RU": ("ru-pr.oxylabs.io", 40001, 49999),
    "UA": ("ua-pr.oxylabs.io", 10001, 19999),
    
    # Americas
    "AR": ("ar-pr.oxylabs.io", 30001, 39999),
    "CL": ("cl-pr.oxylabs.io", 40001, 49999),
    "CO": ("co-pr.oxylabs.io", 30001, 39999),
    "PE": ("pe-pr.oxylabs.io", 10001, 19999),
    
    # Africa
    "ZA": ("za-pr.oxylabs.io", 40001, 49999),
    "NG": ("ng-pr.oxylabs.io", 18001, 18999),
    "KE": ("ke-pr.oxylabs.io", 10001, 10999),
    
    # European Union (general)
    "EU": ("eu-pr.oxylabs.io", 10001, 29999),
    
    # Random/Global fallback
    "RANDOM": ("pr.oxylabs.io", 10000, 49999),
}


class OxylabsProxy:
    """Oxylabs proxy provider with sticky session support.
    
    Uses Sticky Proxy Entry Nodes for consistent IP sessions per profile.
    Each profile has a dedicated port stored in the database:
    - Same port = same IP (for up to 10 minutes)
    - After 10 min, Oxylabs rotates IP but same port = new sticky session
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.proxy_mode = self.settings.oxylabs_proxy_type
        self._validate_config()
    
    def _validate_config(self) -> None:
        """Validate Oxylabs configuration."""
        if not self.settings.oxylabs_username:
            raise ProxyNotAvailableError("OXYLABS_USERNAME is required")
        if not self.settings.oxylabs_password:
            raise ProxyNotAvailableError("OXYLABS_PASSWORD is required")
    
    def _get_entry_node(self, country: str) -> Tuple[str, int, int]:
        """Get sticky entry node for country.
        
        Args:
            country: ISO country code (e.g., "US", "AE")
        
        Returns:
            Tuple of (host, port_start, port_end)
        """
        country_upper = country.upper()
        
        if country_upper in STICKY_ENTRY_NODES:
            return STICKY_ENTRY_NODES[country_upper]
        
        # Fallback to random global entry point
        logger.warning(f"No sticky entry node for {country}, using global random")
        return STICKY_ENTRY_NODES["RANDOM"]

    def _get_residential_entry_node(self, country: str) -> Tuple[str, int]:
        """Get residential random entry node for country."""
        country_upper = (country or "").upper()
        if country_upper in RESIDENTIAL_ENTRY_NODES:
            return RESIDENTIAL_ENTRY_NODES[country_upper]

        fallback_host = self.settings.oxylabs_residential_host
        fallback_port = DEFAULT_RESIDENTIAL_ENTRY_PORT
        if country_upper:
            # Default Oxylabs country endpoint pattern for residential random entry.
            return (f"{country_upper.lower()}-pr.oxylabs.io", fallback_port)
        return (fallback_host, fallback_port)
    
    def generate_port_for_country(self, country: str) -> int:
        """Generate a random port within the country's range.
        
        Call this once when creating a profile to assign a sticky port.
        
        Args:
            country: ISO country code
        
        Returns:
            Random port within the country's sticky port range
        """
        if self.proxy_mode == "mobile":
            _, port_start, port_end = self._get_entry_node(country)
            return random.randint(port_start, port_end)

        _, default_port = self._get_residential_entry_node(country)
        return default_port

    @staticmethod
    def _normalize_state(state: Optional[str]) -> Optional[str]:
        """Normalize state to Oxylabs token format (e.g., 'New York' -> 'new_york')."""
        if not state:
            return None
        normalized = state.strip().lower().replace(" ", "_")
        return normalized or None

    @staticmethod
    def _normalize_city(city: Optional[str]) -> Optional[str]:
        """Normalize city to Oxylabs token format (e.g., 'Los Angeles' -> 'los_angeles')."""
        if not city:
            return None
        normalized = city.strip().lower().replace(" ", "_")
        return normalized or None

    def _build_username(
        self,
        country: str,
        state: Optional[str] = None,
        city: Optional[str] = None,
    ) -> str:
        """Build Oxylabs auth username based on selected proxy mode and geo-target params."""
        username = f"customer-{self.settings.oxylabs_username}"
        country_upper = country.upper()
        normalized_state = self._normalize_state(state)
        normalized_city = self._normalize_city(city)

        if self.proxy_mode == "mobile":
            if normalized_state:
                username = f"{username}-st-{country_upper.lower()}_{normalized_state}"
            return username

        # Residential mode supports cc/city and US state targeting.
        if normalized_state and country_upper == "US":
            username = f"{username}-st-us_{normalized_state}"
        else:
            username = f"{username}-cc-{country_upper}"
        if normalized_city:
            username = f"{username}-city-{normalized_city}"
        return username

    def _resolve_endpoint(self, country: str, port: int) -> Tuple[str, int]:
        """Resolve Oxylabs endpoint host/port based on proxy mode."""
        if self.proxy_mode == "mobile":
            host, _, _ = self._get_entry_node(country)
            return host, port

        host, default_port = self._get_residential_entry_node(country)
        # Residential supports random-entry ports. Respect stored profile port if set.
        return host, port or default_port
    
    def get_proxy(
        self,
        country: str,
        port: int,
        state: Optional[str] = None,
        city: Optional[str] = None,
    ) -> ProxyConfig:
        """Get proxy configuration for a specific country and port.
        
        Args:
            country: ISO country code (e.g., "US", "AE", "GB")
            port: Sticky port from profile.proxy_port
            state: Optional sub-country target (e.g., "california")
            city: Optional city target (e.g., "los_angeles")
        
        Returns:
            ProxyConfig with server, username, password, and port
        
        Raises:
            ProxyNotAvailableError: If proxy is not configured
        """
        if self.settings.proxy_required:
            self._validate_config()
        
        host, resolved_port = self._resolve_endpoint(country, port)
        server = f"http://{host}:{resolved_port}"

        username = self._build_username(country, state=state, city=city)
        normalized_state = self._normalize_state(state)
        normalized_city = self._normalize_city(city)
        if normalized_state and normalized_city:
            logger.info(
                f"[proxy] {self.proxy_mode} session: {country.upper()}-{normalized_state}-{normalized_city} via {host}:{resolved_port}"
            )
        elif normalized_state:
            logger.info(
                f"[proxy] {self.proxy_mode} session: {country.upper()}-{normalized_state} via {host}:{resolved_port}"
            )
        elif normalized_city:
            logger.info(
                f"[proxy] {self.proxy_mode} session: {country.upper()}-{normalized_city} via {host}:{resolved_port}"
            )
        else:
            logger.info(f"[proxy] {self.proxy_mode} session: {country.upper()} via {host}:{resolved_port}")
        
        return ProxyConfig(
            server=server,
            username=username,
            password=self.settings.oxylabs_password,
            country=country.upper(),
            port=resolved_port,
            mode=self.proxy_mode,
        )
    
    def get_proxy_dict(
        self,
        country: str,
        port: int,
        state: Optional[str] = None,
        city: Optional[str] = None,
    ) -> dict:
        """Get proxy as dictionary for Playwright/Patchright.
        
        Args:
            country: ISO country code
            port: Sticky port from profile.proxy_port
            state: Optional sub-country target (e.g., "california")
            city: Optional city target (e.g., "los_angeles")
        
        Returns:
            Dictionary with server, username, password keys
        """
        config = self.get_proxy(country, port, state=state, city=city)
        return {
            "server": config.server,
            "username": config.username,
            "password": config.password,
        }


# Singleton instance
_proxy_provider: Optional[OxylabsProxy] = None


def get_proxy_provider() -> OxylabsProxy:
    """Get proxy provider singleton."""
    global _proxy_provider
    if _proxy_provider is None:
        _proxy_provider = OxylabsProxy()
    return _proxy_provider
