"""Shared test fixtures and configuration for LinkedIn MCP unit tests.

All tests use mocks — no real database, browser, or network calls.
"""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add src to path so tests can import linkedin_mcp without installation
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


# ── Environment fixtures ────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_settings_singleton():
    """Reset the Settings singleton between tests so env changes take effect."""
    import linkedin_mcp.config as cfg_module
    cfg_module._settings = None
    cfg_module._logging_configured = False
    yield
    cfg_module._settings = None
    cfg_module._logging_configured = False


@pytest.fixture
def fernet_key():
    """Provide a valid Fernet key for encryption tests."""
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode("utf-8")


@pytest.fixture
def env_test(fernet_key, monkeypatch):
    """Set up minimal environment variables for testing."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
    monkeypatch.setenv("LINKEDIN_CREDENTIAL_ENCRYPTION_KEY", fernet_key)
    monkeypatch.setenv("PROXY_PROVIDER", "oxylabs")
    monkeypatch.setenv("OXYLABS_USERNAME", "testuser")
    monkeypatch.setenv("OXYLABS_PASSWORD", "testpass")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    return fernet_key


@pytest.fixture
def env_apify(fernet_key, monkeypatch):
    """Set up environment for Apify proxy tests."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
    monkeypatch.setenv("LINKEDIN_CREDENTIAL_ENCRYPTION_KEY", fernet_key)
    monkeypatch.setenv("PROXY_PROVIDER", "apify")
    monkeypatch.setenv("APIFY_PROXY_PASSWORD", "apify_secret_pass")
    monkeypatch.setenv("APIFY_PROXY_GROUPS", "RESIDENTIAL")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    return fernet_key


@pytest.fixture
def env_ipfoxy(fernet_key, monkeypatch):
    """Set up environment for IPFoxy proxy tests."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
    monkeypatch.setenv("LINKEDIN_CREDENTIAL_ENCRYPTION_KEY", fernet_key)
    monkeypatch.setenv("PROXY_PROVIDER", "ipfoxy")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    return fernet_key


# ── Mock DB fixtures ────────────────────────────────────────────

@pytest.fixture
def mock_db_session():
    """Create a mock SQLAlchemy Session for repository tests."""
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = None
    session.query.return_value.filter.return_value.all.return_value = []
    session.query.return_value.filter.return_value.delete.return_value = 0
    return session


@pytest.fixture
def mock_profile_row():
    """Create a mock Profile DB row with typical fields."""
    profile = MagicMock()
    profile.id = 1
    profile.uuid = "test-uuid-1234"
    profile.linkedin_email = "test@example.com"
    profile.linkedin_password_encrypted = "encrypted_value"
    profile.country = "US"
    profile.state = "california"
    profile.city = None
    profile.proxy_port = 15000
    profile.timezone = "America/Los_Angeles"
    profile.totp_secret = None
    profile.is_active = True

    # Mock fingerprint relationship
    fp = MagicMock()
    fp.fingerprint_data = {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/149.0.0.0 Safari/537.36",
        "platform": "MacIntel",
        "screen_width": 1920,
        "screen_height": 1080,
        "color_depth": 24,
        "hardware_concurrency": 8,
        "device_memory": 8,
        "languages": ["en-US", "en"],
        "webgl_vendor": "Google Inc. (Apple)",
        "webgl_renderer": "ANGLE (Apple, ANGLE Metal Renderer: Apple M3)",
    }
    fp.user_agent = fp.fingerprint_data["user_agent"]
    fp.platform = fp.fingerprint_data["platform"]
    profile.fingerprint = fp

    # Mock proxy_configs
    profile.proxy_configs = []

    return profile


@pytest.fixture
def mock_page():
    """Create a mock Patchright Page for browser interaction tests."""
    page = MagicMock()
    page.viewport_size = {"width": 1280, "height": 720}
    page.goto = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.mouse = MagicMock()
    page.mouse.move = AsyncMock()
    page.mouse.wheel = AsyncMock()
    page.locator = MagicMock()
    locator = MagicMock()
    locator.click = AsyncMock()
    locator.fill = AsyncMock()
    locator.press_sequentially = AsyncMock()
    page.locator.return_value = locator
    page.locator.return_value.first = locator
    return page
