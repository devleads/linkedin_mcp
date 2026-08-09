"""Unit tests for data models (Profile, ProfileFingerprint, CookieData, CookieStore)."""

import json
import os
import tempfile
from datetime import datetime

import pytest

from linkedin_mcp.models.profile import Profile, ProfileFingerprint
from linkedin_mcp.models.cookies import CookieData, CookieStore, ESSENTIAL_COOKIES


class TestProfileFingerprint:
    """Test ProfileFingerprint dataclass."""

    def test_defaults(self):
        """Should have correct default values."""
        fp = ProfileFingerprint(user_agent="test_ua", platform="MacIntel")
        assert fp.screen_width == 1920
        assert fp.screen_height == 1080
        assert fp.color_depth == 24
        assert fp.hardware_concurrency == 8
        assert fp.device_memory == 8
        assert fp.languages == ["en-US", "en"]
        assert fp.webgl_vendor == "Google Inc."

    def test_to_dict(self):
        """to_dict should include all fields."""
        fp = ProfileFingerprint(user_agent="ua", platform="Win32")
        d = fp.to_dict()
        assert d["user_agent"] == "ua"
        assert d["platform"] == "Win32"
        assert "screen_width" in d
        assert "webgl_renderer" in d

    def test_from_dict(self):
        """from_dict should reconstruct the dataclass."""
        data = {
            "user_agent": "test_ua",
            "platform": "Linux x86_64",
            "screen_width": 2560,
            "screen_height": 1440,
        }
        fp = ProfileFingerprint.from_dict(data)
        assert fp.user_agent == "test_ua"
        assert fp.platform == "Linux x86_64"
        assert fp.screen_width == 2560
        assert fp.screen_height == 1440

    def test_roundtrip(self):
        """to_dict → from_dict should be identity."""
        fp = ProfileFingerprint(user_agent="ua", platform="MacIntel", webgl_vendor="Apple")
        restored = ProfileFingerprint.from_dict(fp.to_dict())
        assert restored == fp


class TestProfile:
    """Test Profile dataclass."""

    def _make_fp(self):
        return ProfileFingerprint(user_agent="ua", platform="MacIntel")

    def test_to_dict(self):
        """to_dict should include all fields."""
        p = Profile(
            id="test-id",
            linkedin_email="test@example.com",
            country="US",
            timezone="America/Los_Angeles",
            fingerprint=self._make_fp(),
        )
        d = p.to_dict()
        assert d["id"] == "test-id"
        assert d["linkedin_email"] == "test@example.com"
        assert d["country"] == "US"
        assert d["timezone"] == "America/Los_Angeles"
        assert "fingerprint" in d

    def test_from_dict(self):
        """from_dict should reconstruct the Profile."""
        data = {
            "id": "test-id",
            "linkedin_email": "test@example.com",
            "country": "AE",
            "timezone": "Asia/Dubai",
            "fingerprint": {"user_agent": "ua", "platform": "MacIntel"},
        }
        p = Profile.from_dict(data)
        assert p.id == "test-id"
        assert p.country == "AE"
        assert p.fingerprint.user_agent == "ua"

    def test_roundtrip(self):
        """to_dict → from_dict should be identity."""
        p = Profile(
            id="test-id",
            linkedin_email="test@example.com",
            country="US",
            timezone="America/Los_Angeles",
            fingerprint=self._make_fp(),
            state="california",
        )
        restored = Profile.from_dict(p.to_dict())
        assert restored.id == p.id
        assert restored.country == p.country
        assert restored.state == p.state
        assert restored.fingerprint == p.fingerprint

    def test_save_and_load(self):
        """save then load should restore the profile."""
        p = Profile(
            id="test-save",
            linkedin_email="test@example.com",
            country="US",
            timezone="America/Los_Angeles",
            fingerprint=self._make_fp(),
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            p.save(tmpdir)
            loaded = Profile.load("test-save", tmpdir)
            assert loaded is not None
            assert loaded.id == "test-save"
            assert loaded.fingerprint.user_agent == "ua"

    def test_load_nonexistent(self):
        """load should return None for missing profile."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = Profile.load("nonexistent", tmpdir)
            assert result is None

    def test_list_profiles(self):
        """list_profiles should list profile directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            p1 = Profile(
                id="profile-a", linkedin_email="a@test.com", country="US",
                timezone="America/New_York", fingerprint=self._make_fp(),
            )
            p2 = Profile(
                id="profile-b", linkedin_email="b@test.com", country="AE",
                timezone="Asia/Dubai", fingerprint=self._make_fp(),
            )
            p1.save(tmpdir)
            p2.save(tmpdir)
            profiles = Profile.list_profiles(tmpdir)
            assert "profile-a" in profiles
            assert "profile-b" in profiles

    def test_list_profiles_empty(self):
        """list_profiles should return [] for nonexistent directory."""
        assert Profile.list_profiles("/nonexistent/path") == []


class TestCookieData:
    """Test CookieData dataclass."""

    def test_defaults(self):
        """Should have correct defaults."""
        c = CookieData(name="li_at", value="test_value")
        assert c.domain == ".linkedin.com"
        assert c.path == "/"
        assert c.secure is True
        assert c.http_only is True
        assert c.same_site == "None"

    def test_to_dict(self):
        """to_dict should use camelCase for httpOnly/sameSite."""
        c = CookieData(name="li_at", value="test")
        d = c.to_dict()
        assert d["name"] == "li_at"
        assert d["httpOnly"] is True
        assert d["sameSite"] == "None"

    def test_to_playwright_cookie(self):
        """to_playwright_cookie should have correct keys."""
        c = CookieData(name="li_at", value="test", expires=1234567890.0)
        pw = c.to_playwright_cookie()
        assert pw["name"] == "li_at"
        assert pw["httpOnly"] is True
        assert pw["expires"] == 1234567890.0

    def test_to_playwright_cookie_no_expires(self):
        """Should not include expires when None."""
        c = CookieData(name="li_at", value="test", expires=None)
        pw = c.to_playwright_cookie()
        assert "expires" not in pw

    def test_from_dict(self):
        """from_dict should reconstruct CookieData."""
        data = {"name": "JSESSIONID", "value": "abc", "httpOnly": False}
        c = CookieData.from_dict(data)
        assert c.name == "JSESSIONID"
        assert c.http_only is False

    def test_from_playwright_cookie(self):
        """from_playwright_cookie should map fields correctly."""
        pw = {"name": "bcookie", "value": "xyz", "domain": ".linkedin.com"}
        c = CookieData.from_playwright_cookie(pw)
        assert c.name == "bcookie"
        assert c.value == "xyz"
        assert c.domain == ".linkedin.com"

    def test_roundtrip(self):
        """to_dict → from_dict should be identity."""
        c = CookieData(name="li_at", value="test", expires=999.0)
        restored = CookieData.from_dict(c.to_dict())
        assert restored.name == c.name
        assert restored.value == c.value
        assert restored.expires == c.expires


class TestCookieStore:
    """Test CookieStore file-based persistence."""

    def test_set_and_get(self):
        """Should set and retrieve cookies."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CookieStore("profile-1", tmpdir)
            store.set(CookieData(name="li_at", value="token123"))
            cookie = store.get("li_at")
            assert cookie is not None
            assert cookie.value == "token123"

    def test_get_nonexistent(self):
        """get should return None for missing cookie."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CookieStore("profile-1", tmpdir)
            assert store.get("nonexistent") is None

    def test_has_auth_true(self):
        """has_auth should return True when li_at is present."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CookieStore("profile-1", tmpdir)
            store.set(CookieData(name="li_at", value="token"))
            assert store.has_auth() is True

    def test_has_auth_false(self):
        """has_auth should return False when li_at is missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CookieStore("profile-1", tmpdir)
            assert store.has_auth() is False

    def test_get_li_at(self):
        """get_li_at should return the li_at value."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CookieStore("profile-1", tmpdir)
            store.set(CookieData(name="li_at", value="my_token"))
            assert store.get_li_at() == "my_token"

    def test_get_li_at_missing(self):
        """get_li_at should return None when li_at is missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CookieStore("profile-1", tmpdir)
            assert store.get_li_at() is None

    def test_get_essential(self):
        """get_essential should return only essential cookies."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CookieStore("profile-1", tmpdir)
            store.set(CookieData(name="li_at", value="t"))
            store.set(CookieData(name="JSESSIONID", value="j"))
            store.set(CookieData(name="non_essential", value="x"))
            essential = store.get_essential()
            names = [c.name for c in essential]
            assert "li_at" in names
            assert "JSESSIONID" in names
            assert "non_essential" not in names

    def test_save_and_reload(self):
        """Saved cookies should persist across CookieStore instances."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store1 = CookieStore("profile-1", tmpdir)
            store1.set(CookieData(name="li_at", value="persisted"))
            store1.save()

            store2 = CookieStore("profile-1", tmpdir)
            assert store2.get_li_at() == "persisted"

    def test_update_from_browser(self):
        """update_from_browser should filter to LinkedIn cookies only."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CookieStore("profile-1", tmpdir)
            browser_cookies = [
                {"name": "li_at", "value": "t", "domain": ".linkedin.com"},
                {"name": "JSESSIONID", "value": "j", "domain": ".linkedin.com"},
                {"name": "google_analytics", "value": "ga", "domain": ".google.com"},
            ]
            store.update_from_browser(browser_cookies)
            assert store.get("li_at") is not None
            assert store.get("JSESSIONID") is not None
            assert store.get("google_analytics") is None

    def test_clear(self):
        """clear should remove all cookies and delete the file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CookieStore("profile-1", tmpdir)
            store.set(CookieData(name="li_at", value="t"))
            store.save()
            store.clear()
            assert store.get("li_at") is None
            assert not store.cookies_file.exists()

    def test_to_playwright_cookies(self):
        """to_playwright_cookies should convert all cookies."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CookieStore("profile-1", tmpdir)
            store.set(CookieData(name="li_at", value="t"))
            store.set(CookieData(name="JSESSIONID", value="j"))
            pw_cookies = store.to_playwright_cookies()
            assert len(pw_cookies) == 2
            names = [c["name"] for c in pw_cookies]
            assert "li_at" in names
            assert "JSESSIONID" in names


class TestEssentialCookies:
    """Test ESSENTIAL_COOKIES constant."""

    def test_contains_li_at(self):
        assert "li_at" in ESSENTIAL_COOKIES

    def test_contains_jsessionid(self):
        assert "JSESSIONID" in ESSENTIAL_COOKIES

    def test_contains_bcookie(self):
        assert "bcookie" in ESSENTIAL_COOKIES
