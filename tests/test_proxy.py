"""Unit tests for proxy providers (apify, oxylabs, ipfoxy, __init__)."""

import hashlib
from unittest.mock import patch, MagicMock

import pytest

from linkedin_mcp.proxy.apify import (
    ApifyProxy,
    ApifyProxyConfig,
    ProxyNotAvailableError as ApifyProxyNotAvailableError,
    _profile_session_id,
    _normalize_state,
)
from linkedin_mcp.proxy.oxylabs import (
    OxylabsProxy,
    ProxyConfig,
    ProxyNotAvailableError as OxylabsProxyNotAvailableError,
    STICKY_ENTRY_NODES,
    RESIDENTIAL_ENTRY_NODES,
)
from linkedin_mcp.proxy.ipfoxy import (
    IPFoxyProxy,
    IPFoxyProxyConfig,
    ProxyNotAvailableError as IPFoxyProxyNotAvailableError,
)


# ── Apify proxy tests ───────────────────────────────────────────

class TestApifySessionId:
    """Test deterministic session ID generation."""

    def test_deterministic(self):
        """Same UUID should produce the same session ID."""
        uuid = "abc-123-def"
        sid1 = _profile_session_id(uuid)
        sid2 = _profile_session_id(uuid)
        assert sid1 == sid2

    def test_different_uuids_different_sessions(self):
        """Different UUIDs should produce different session IDs."""
        sid1 = _profile_session_id("uuid-aaa")
        sid2 = _profile_session_id("uuid-bbb")
        assert sid1 != sid2

    def test_length(self):
        """Session ID should be 16 hex characters."""
        sid = _profile_session_id("test-uuid")
        assert len(sid) == 16
        int(sid, 16)  # Should be valid hex

    def test_matches_sha256(self):
        """Session ID should be first 16 chars of SHA-256 of UUID."""
        uuid = "my-profile-uuid"
        expected = hashlib.sha256(uuid.encode("utf-8")).hexdigest()[:16]
        assert _profile_session_id(uuid) == expected


class TestApifyNormalizeState:
    """Test state normalization for Apify."""

    def test_none(self):
        assert _normalize_state(None) is None

    def test_empty(self):
        assert _normalize_state("") is None

    def test_simple(self):
        assert _normalize_state("california") == "california"

    def test_spaces(self):
        assert _normalize_state("New York") == "new_york"

    def test_uppercase(self):
        assert _normalize_state("California") == "california"


class TestApifyProxy:
    """Test ApifyProxy provider."""

    def test_missing_password(self, monkeypatch):
        """Should raise when APIFY_PROXY_PASSWORD is not set."""
        monkeypatch.setenv("APIFY_PROXY_PASSWORD", "")
        monkeypatch.setenv("PROXY_PROVIDER", "apify")
        import linkedin_mcp.config as cfg
        cfg._settings = None
        with pytest.raises(ApifyProxyNotAvailableError, match="APIFY_PROXY_PASSWORD is required"):
            ApifyProxy()

    def test_get_proxy_basic(self, env_apify):
        """Should build proxy config with correct fields."""
        provider = ApifyProxy()
        config = provider.get_proxy(country="us", profile_uuid="test-uuid-123")
        assert isinstance(config, ApifyProxyConfig)
        assert config.country == "US"
        assert config.server == "http://proxy.apify.com:8000"
        assert "session-" in config.username
        assert "country-US" in config.username
        assert "groups-RESIDENTIAL" in config.username
        assert config.password == "apify_secret_pass"

    def test_get_proxy_with_state(self, env_apify):
        """Should include state token for US profiles."""
        provider = ApifyProxy()
        config = provider.get_proxy(country="US", profile_uuid="uuid-1", state="California")
        assert config.state == "california"
        assert "state-california" in config.username

    def test_get_proxy_non_us_ignores_state(self, env_apify):
        """Non-US countries should not include state token."""
        provider = ApifyProxy()
        config = provider.get_proxy(country="AE", profile_uuid="uuid-2", state="dubai")
        assert config.state is None
        assert "state-" not in config.username

    def test_get_proxy_dict(self, env_apify):
        """get_proxy_dict should return dict with server/username/password."""
        provider = ApifyProxy()
        d = provider.get_proxy_dict(country="GB", profile_uuid="uuid-3")
        assert "server" in d
        assert "username" in d
        assert "password" in d
        assert "country-GB" in d["username"]

    def test_session_id_in_username(self, env_apify):
        """Username should contain the deterministic session ID."""
        provider = ApifyProxy()
        uuid = "d52e8d51-0abe-4a43-8d96-5da195803235"
        expected_session = _profile_session_id(uuid)
        config = provider.get_proxy(country="US", profile_uuid=uuid)
        assert f"session-{expected_session}" in config.username


# ── Oxylabs proxy tests ─────────────────────────────────────────

class TestOxylabsProxy:
    """Test OxylabsProxy provider."""

    def test_missing_credentials(self, monkeypatch):
        """Should raise when Oxylabs credentials are missing."""
        monkeypatch.setenv("OXYLABS_USERNAME", "")
        monkeypatch.setenv("OXYLABS_PASSWORD", "")
        monkeypatch.setenv("PROXY_PROVIDER", "oxylabs")
        import linkedin_mcp.config as cfg
        cfg._settings = None
        with pytest.raises(OxylabsProxyNotAvailableError, match="OXYLABS_USERNAME is required"):
            OxylabsProxy()

    def test_get_proxy_mobile(self, env_test):
        """Should build mobile proxy config with correct host and port."""
        provider = OxylabsProxy()
        config = provider.get_proxy(country="US", port=15000)
        assert isinstance(config, ProxyConfig)
        assert config.country == "US"
        assert config.mode == "mobile"
        assert "us-pr.oxylabs.io" in config.server
        assert ":15000" in config.server
        assert "customer-testuser" in config.username

    def test_get_proxy_with_state(self, env_test):
        """Mobile mode should include state in username."""
        provider = OxylabsProxy()
        config = provider.get_proxy(country="US", port=15000, state="California")
        assert "st-us_california" in config.username

    def test_get_proxy_residential(self, monkeypatch, fernet_key):
        """Residential mode should use residential entry nodes."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
        monkeypatch.setenv("LINKEDIN_CREDENTIAL_ENCRYPTION_KEY", fernet_key)
        monkeypatch.setenv("PROXY_PROVIDER", "oxylabs")
        monkeypatch.setenv("OXYLABS_USERNAME", "testuser")
        monkeypatch.setenv("OXYLABS_PASSWORD", "testpass")
        monkeypatch.setenv("OXYLABS_PROXY_TYPE", "residentials")
        monkeypatch.setenv("LOG_LEVEL", "WARNING")
        import linkedin_mcp.config as cfg
        cfg._settings = None
        provider = OxylabsProxy()
        config = provider.get_proxy(country="US", port=7777)
        assert config.mode == "residentials"
        assert "cc-US" in config.username

    def test_generate_port_for_country(self, env_test):
        """Generated port should be within country's sticky range."""
        provider = OxylabsProxy()
        port = provider.generate_port_for_country("US")
        host, port_start, port_end = STICKY_ENTRY_NODES["US"]
        assert port_start <= port <= port_end

    def test_generate_port_unknown_country(self, env_test):
        """Unknown country should fall back to RANDOM entry node."""
        provider = OxylabsProxy()
        port = provider.generate_port_for_country("XX")
        _, port_start, port_end = STICKY_ENTRY_NODES["RANDOM"]
        assert port_start <= port <= port_end

    def test_get_proxy_dict(self, env_test):
        """get_proxy_dict should return dict with server/username/password."""
        provider = OxylabsProxy()
        d = provider.get_proxy_dict(country="AE", port=45000)
        assert "server" in d
        assert "username" in d
        assert "password" in d

    def test_normalize_state(self):
        """Test state normalization."""
        assert OxylabsProxy._normalize_state(None) is None
        assert OxylabsProxy._normalize_state("California") == "california"
        assert OxylabsProxy._normalize_state("New York") == "new_york"

    def test_normalize_city(self):
        """Test city normalization."""
        assert OxylabsProxy._normalize_city(None) is None
        assert OxylabsProxy._normalize_city("Los Angeles") == "los_angeles"


# ── IPFoxy proxy tests ──────────────────────────────────────────

class TestIPFoxyProxy:
    """Test IPFoxyProxy provider."""

    def test_missing_host(self):
        """Should raise when host is missing."""
        with pytest.raises(IPFoxyProxyNotAvailableError, match="ipfoxy_host"):
            IPFoxyProxy.get_proxy(host=None, port=12345, username="u", password="p")

    def test_missing_port(self):
        """Should raise when port is missing."""
        with pytest.raises(IPFoxyProxyNotAvailableError, match="ipfoxy_port"):
            IPFoxyProxy.get_proxy(host="1.2.3.4", port=None, username="u", password="p")

    def test_missing_username(self):
        """Should raise when username is missing."""
        with pytest.raises(IPFoxyProxyNotAvailableError, match="ipfoxy_username"):
            IPFoxyProxy.get_proxy(host="1.2.3.4", port=12345, username=None, password="p")

    def test_missing_password(self):
        """Should raise when password is missing."""
        with pytest.raises(IPFoxyProxyNotAvailableError, match="ipfoxy_password"):
            IPFoxyProxy.get_proxy(host="1.2.3.4", port=12345, username="u", password=None)

    def test_basic_http_proxy(self):
        """Should build HTTP proxy config from separate fields."""
        config = IPFoxyProxy.get_proxy(
            host="179.61.157.188", port=45001, username="user", password="pass"
        )
        assert config.server == "http://179.61.157.188:45001"
        assert config.username == "user"
        assert config.password == "pass"
        assert config.host == "179.61.157.188"
        assert config.port == 45001

    def test_host_with_port(self):
        """Should parse host:port format when port is None."""
        config = IPFoxyProxy.get_proxy(
            host="179.61.157.188:45001", port=None, username="user", password="pass"
        )
        assert config.host == "179.61.157.188"
        assert config.port == 45001

    def test_host_with_all_in_one(self):
        """Should parse host:port:user:pass format."""
        config = IPFoxyProxy.get_proxy(
            host="179.61.157.188:45001:myuser:mypass", port=None, username=None, password=None
        )
        assert config.host == "179.61.157.188"
        assert config.port == 45001
        assert config.username == "myuser"
        assert config.password == "mypass"

    def test_socks5_rejected(self):
        """SOCKS5 with auth should be rejected (browser limitation)."""
        with pytest.raises(IPFoxyProxyNotAvailableError, match="SOCKS5"):
            IPFoxyProxy.get_proxy(
                host="socks5://179.61.157.188", port=45001, username="u", password="p"
            )

    def test_get_proxy_dict(self):
        """get_proxy_dict should return dict with server/username/password."""
        provider = IPFoxyProxy()
        d = provider.get_proxy_dict(host="1.2.3.4", port=8080, username="u", password="p")
        assert d == {"server": "http://1.2.3.4:8080", "username": "u", "password": "p"}


# ── Proxy __init__ tests ────────────────────────────────────────

class TestProxyDispatch:
    """Test proxy provider dispatch in proxy/__init__.py."""

    def test_get_active_provider_name_oxylabs(self, env_test):
        """Should return 'oxylabs' when configured."""
        from linkedin_mcp.proxy import get_active_proxy_provider_name
        assert get_active_proxy_provider_name() == "oxylabs"

    def test_get_active_provider_name_apify(self, env_apify):
        """Should return 'apify' when configured."""
        from linkedin_mcp.proxy import get_active_proxy_provider_name
        assert get_active_proxy_provider_name() == "apify"

    def test_get_proxy_dict_for_profile_oxylabs(self, env_test, mock_profile_row):
        """Should dispatch to Oxylabs provider."""
        from linkedin_mcp.proxy import get_proxy_dict_for_profile
        d = get_proxy_dict_for_profile(mock_profile_row)
        assert "server" in d
        assert "username" in d
        assert "password" in d
        assert "us-pr.oxylabs.io" in d["server"]

    def test_oxylabs_profile_without_sticky_port_fails_closed(self, env_test, mock_profile_row):
        """Resolution must not invent a different route on each session lookup."""
        from linkedin_mcp.proxy import get_proxy_dict_for_profile

        mock_profile_row.proxy_port = None
        with pytest.raises(OxylabsProxyNotAvailableError, match="sticky port"):
            get_proxy_dict_for_profile(mock_profile_row)

    def test_get_proxy_dict_for_profile_apify(self, env_apify, mock_profile_row):
        """Should dispatch to Apify provider."""
        from linkedin_mcp.proxy import get_proxy_dict_for_profile
        d = get_proxy_dict_for_profile(mock_profile_row)
        assert "server" in d
        assert "proxy.apify.com" in d["server"]
        assert "country-US" in d["username"]

    def test_get_proxy_dict_for_profile_missing_country(self, env_apify):
        """Should raise when profile has no country."""
        from linkedin_mcp.proxy import get_proxy_dict_for_profile
        profile = MagicMock()
        profile.country = None
        profile.uuid = "test-uuid"
        with pytest.raises(ApifyProxyNotAvailableError, match="missing country"):
            get_proxy_dict_for_profile(profile)
