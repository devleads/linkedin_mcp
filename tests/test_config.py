"""Unit tests for configuration management."""

import logging

from linkedin_mcp.config import Settings, get_settings, setup_logging, JsonFormatter


class TestSettings:
    """Test Settings model loading from environment."""

    def test_defaults(self, monkeypatch, tmp_path):
        """Settings should have correct defaults when no env vars set."""
        # Move to a temp dir so no .env file is picked up
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("PROXY_PROVIDER", raising=False)
        monkeypatch.delenv("LINKEDIN_CREDENTIAL_ENCRYPTION_KEY", raising=False)
        monkeypatch.delenv("OXYLABS_USERNAME", raising=False)
        monkeypatch.delenv("OXYLABS_PASSWORD", raising=False)
        import linkedin_mcp.config as cfg
        cfg._settings = None
        settings = Settings()
        assert settings.database_url == "postgresql://linkedin:linkedin@localhost:5432/linkedin"
        assert settings.proxy_provider == "oxylabs"
        assert settings.headless is False
        assert settings.mcp_host == "127.0.0.1"
        assert settings.browser_runtime == "legacy_injected"
        assert settings.mcp_port == 8765

    def test_explicit_direct_route(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("PROXY_PROVIDER", "none")
        settings = Settings()
        assert settings.proxy_provider == "none"

    def test_env_override(self, env_test):
        """Settings should load from environment variables."""
        settings = get_settings()
        assert settings.database_url == "postgresql://test:test@localhost:5432/test"
        assert settings.proxy_provider == "oxylabs"
        assert settings.oxylabs_username == "testuser"
        assert settings.oxylabs_password == "testpass"

    def test_singleton(self, env_test):
        """get_settings should return the same instance."""
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_apify_provider(self, env_apify):
        """Should load apify provider settings."""
        settings = get_settings()
        assert settings.proxy_provider == "apify"
        assert settings.apify_proxy_password == "apify_secret_pass"
        assert settings.apify_proxy_groups == "RESIDENTIAL"

    def test_ipfoxy_provider(self, env_ipfoxy):
        """Should load ipfoxy provider settings."""
        settings = get_settings()
        assert settings.proxy_provider == "ipfoxy"

    def test_invalid_proxy_provider(self, monkeypatch):
        """Invalid proxy provider should raise validation error."""
        monkeypatch.setenv("PROXY_PROVIDER", "invalid_provider")
        import linkedin_mcp.config as cfg
        cfg._settings = None
        import pytest as _pytest
        with _pytest.raises(Exception):
            Settings()


class TestLogging:
    """Test logging configuration."""

    def test_setup_logging_text(self, env_test):
        """setup_logging should configure text format handler."""
        setup_logging()
        root = logging.getLogger()
        assert len(root.handlers) > 0
        assert root.level == logging.WARNING  # env_test sets LOG_LEVEL=WARNING

    def test_setup_logging_idempotent(self, env_test):
        """setup_logging should not add duplicate handlers on repeated calls."""
        setup_logging()
        handler_count = len(logging.getLogger().handlers)
        setup_logging()
        assert len(logging.getLogger().handlers) == handler_count

    def test_json_formatter(self):
        """JsonFormatter should produce valid JSON output."""
        import json
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py", lineno=1,
            msg="test message", args=(), exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert data["level"] == "INFO"
        assert data["message"] == "test message"
        assert data["logger"] == "test"
        assert "timestamp" in data
