"""Unit tests for database repository (ProfileRepository, CookieRepository).

Uses SQLite in-memory database for real SQL behavior without external dependencies.
"""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from linkedin_mcp.db.base import Base
from linkedin_mcp.db.models import (
    Profile,
    ProfileFingerprint,
    ProfileCookie,
    ProfileChallengeEvent,
    ProfileProxyConfig,
    ProfileBrowserState,
    ProfileActionLedger,
)
from linkedin_mcp.db.repository import (
    ProfileRepository,
    CookieRepository,
    ChallengeEventRepository,
    BrowserStateRepository,
    BrowserRuntimeRepository,
    ActionLedgerRepository,
)


@pytest.fixture
def db_session(env_test):
    """Create an in-memory SQLite database with all tables for each test."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def sample_fingerprint_data():
    """Return a sample fingerprint dict for testing."""
    return {
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


# ── ProfileRepository tests ─────────────────────────────────────

class TestProfileRepository:
    """Test ProfileRepository CRUD operations."""

    def test_create_profile(self, db_session, sample_fingerprint_data):
        """Should create a profile with fingerprint."""
        repo = ProfileRepository(db_session)
        profile = repo.create(
            uuid="test-uuid-1",
            linkedin_email="test@example.com",
            linkedin_password="secret",
            country="us",
            timezone="America/Los_Angeles",
            fingerprint_data=sample_fingerprint_data,
        )
        assert profile.id is not None
        assert profile.uuid == "test-uuid-1"
        assert profile.linkedin_email == "test@example.com"
        assert profile.country == "US"
        assert profile.fingerprint is not None
        assert profile.fingerprint.fingerprint_data["user_agent"] == sample_fingerprint_data["user_agent"]

    def test_get_by_uuid(self, db_session, sample_fingerprint_data):
        """Should retrieve profile by UUID."""
        repo = ProfileRepository(db_session)
        repo.create(
            uuid="uuid-find-me",
            linkedin_email="test@example.com",
            linkedin_password=None,
            country="AE",
            timezone="Asia/Dubai",
            fingerprint_data=sample_fingerprint_data,
        )
        found = repo.get_by_uuid("uuid-find-me")
        assert found is not None
        assert found.linkedin_email == "test@example.com"

    def test_get_by_uuid_not_found(self, db_session):
        """Should return None for non-existent UUID."""
        repo = ProfileRepository(db_session)
        assert repo.get_by_uuid("nonexistent") is None

    def test_get_by_id(self, db_session, sample_fingerprint_data):
        """Should retrieve profile by numeric ID."""
        repo = ProfileRepository(db_session)
        created = repo.create(
            uuid="uuid-by-id",
            linkedin_email="test@example.com",
            linkedin_password=None,
            country="US",
            timezone="America/New_York",
            fingerprint_data=sample_fingerprint_data,
        )
        found = repo.get_by_id(created.id)
        assert found is not None
        assert found.uuid == "uuid-by-id"

    def test_list_active(self, db_session, sample_fingerprint_data):
        """Should list only active profiles."""
        repo = ProfileRepository(db_session)
        repo.create(
            uuid="uuid-active",
            linkedin_email="a@test.com",
            linkedin_password=None,
            country="US",
            timezone="America/New_York",
            fingerprint_data=sample_fingerprint_data,
        )
        active = repo.list_active()
        assert len(active) == 1
        assert active[0].uuid == "uuid-active"

    def test_update_fingerprint(self, db_session, sample_fingerprint_data):
        """Should update fingerprint data."""
        repo = ProfileRepository(db_session)
        profile = repo.create(
            uuid="uuid-update-fp",
            linkedin_email="test@example.com",
            linkedin_password=None,
            country="US",
            timezone="America/New_York",
            fingerprint_data=sample_fingerprint_data,
        )
        new_data = {**sample_fingerprint_data, "user_agent": "new_ua"}
        repo.update_fingerprint(profile.id, new_data)
        updated = repo.get_by_id(profile.id)
        assert updated.fingerprint.fingerprint_data["user_agent"] == "new_ua"

    def test_update_fingerprint_not_found(self, db_session):
        """Should raise ValueError for non-existent fingerprint."""
        repo = ProfileRepository(db_session)
        with pytest.raises(ValueError, match="No fingerprint found"):
            repo.update_fingerprint(999, {})

    def test_update_profile(self, db_session, sample_fingerprint_data):
        """Should update profile fields."""
        repo = ProfileRepository(db_session)
        profile = repo.create(
            uuid="uuid-update",
            linkedin_email="old@test.com",
            linkedin_password=None,
            country="US",
            timezone="America/New_York",
            fingerprint_data=sample_fingerprint_data,
        )
        repo.update(profile, linkedin_email="new@test.com", country="AE")
        updated = repo.get_by_id(profile.id)
        assert updated.linkedin_email == "new@test.com"
        assert updated.country == "AE"

    def test_update_password(self, db_session, sample_fingerprint_data):
        """Should encrypt password on update."""
        repo = ProfileRepository(db_session)
        profile = repo.create(
            uuid="uuid-pwd",
            linkedin_email="test@test.com",
            linkedin_password="old_pass",
            country="US",
            timezone="America/New_York",
            fingerprint_data=sample_fingerprint_data,
        )
        repo.update(profile, linkedin_password="new_pass")
        updated = repo.get_by_id(profile.id)
        assert updated.linkedin_password_encrypted != "new_pass"

    def test_delete_profile(self, db_session, sample_fingerprint_data):
        """Should delete profile and cascade to fingerprint."""
        repo = ProfileRepository(db_session)
        profile = repo.create(
            uuid="uuid-delete",
            linkedin_email="test@test.com",
            linkedin_password=None,
            country="US",
            timezone="America/New_York",
            fingerprint_data=sample_fingerprint_data,
        )
        profile_id = profile.id
        repo.delete(profile)
        assert repo.get_by_id(profile_id) is None
        # Fingerprint should be cascade-deleted
        fp = db_session.query(ProfileFingerprint).filter(
            ProfileFingerprint.profile_id == profile_id
        ).first()
        assert fp is None

    def test_create_with_ipfoxy(self, db_session, sample_fingerprint_data):
        """Should create profile with IPFoxy proxy config."""
        repo = ProfileRepository(db_session)
        profile = repo.create(
            uuid="uuid-ipfoxy",
            linkedin_email="test@test.com",
            linkedin_password=None,
            country="US",
            timezone="America/New_York",
            fingerprint_data=sample_fingerprint_data,
            ipfoxy_host="1.2.3.4",
            ipfoxy_port=8080,
            ipfoxy_username="user",
            ipfoxy_password="pass",
        )
        configs = db_session.query(ProfileProxyConfig).filter(
            ProfileProxyConfig.profile_id == profile.id
        ).all()
        assert len(configs) == 1
        assert configs[0].provider == "ipfoxy"
        assert configs[0].host == "1.2.3.4"

    def test_state_normalization(self, db_session, sample_fingerprint_data):
        """Should normalize state to lowercase with underscores."""
        repo = ProfileRepository(db_session)
        profile = repo.create(
            uuid="uuid-state",
            linkedin_email="test@test.com",
            linkedin_password=None,
            country="US",
            timezone="America/New_York",
            fingerprint_data=sample_fingerprint_data,
            state="New York",
        )
        assert profile.state == "new_york"


# ── CookieRepository tests ──────────────────────────────────────

class TestCookieRepository:
    """Test CookieRepository operations."""

    def _create_profile(self, repo, fp_data):
        return repo.create(
            uuid="cookie-test-uuid",
            linkedin_email="test@test.com",
            linkedin_password=None,
            country="US",
            timezone="America/New_York",
            fingerprint_data=fp_data,
        )

    def test_set_and_get_cookie(self, db_session, sample_fingerprint_data):
        """Should set and retrieve a cookie."""
        profile_repo = ProfileRepository(db_session)
        profile = self._create_profile(profile_repo, sample_fingerprint_data)

        cookie_repo = CookieRepository(db_session)
        cookie_repo.set_cookie(profile_id=profile.id, name="li_at", value="token123")

        cookie = cookie_repo.get_by_name(profile.id, "li_at")
        assert cookie is not None
        assert cookie.value != "token123"
        assert cookie_repo.get_li_at(profile.id) == "token123"

    def test_update_existing_cookie(self, db_session, sample_fingerprint_data):
        """Should update existing cookie value."""
        profile_repo = ProfileRepository(db_session)
        profile = self._create_profile(profile_repo, sample_fingerprint_data)

        cookie_repo = CookieRepository(db_session)
        cookie_repo.set_cookie(profile_id=profile.id, name="li_at", value="old")
        cookie_repo.set_cookie(profile_id=profile.id, name="li_at", value="new")

        cookie = cookie_repo.get_by_name(profile.id, "li_at")
        assert cookie.value != "new"
        assert cookie_repo.get_li_at(profile.id) == "new"

    def test_get_li_at(self, db_session, sample_fingerprint_data):
        """get_li_at should return the li_at value."""
        profile_repo = ProfileRepository(db_session)
        profile = self._create_profile(profile_repo, sample_fingerprint_data)

        cookie_repo = CookieRepository(db_session)
        cookie_repo.set_cookie(profile_id=profile.id, name="li_at", value="my_token")
        assert cookie_repo.get_li_at(profile.id) == "my_token"

    def test_get_li_at_missing(self, db_session, sample_fingerprint_data):
        """get_li_at should return None when li_at is not set."""
        profile_repo = ProfileRepository(db_session)
        profile = self._create_profile(profile_repo, sample_fingerprint_data)

        cookie_repo = CookieRepository(db_session)
        assert cookie_repo.get_li_at(profile.id) is None

    def test_has_auth_true(self, db_session, sample_fingerprint_data):
        """has_auth should return True when li_at exists."""
        profile_repo = ProfileRepository(db_session)
        profile = self._create_profile(profile_repo, sample_fingerprint_data)

        cookie_repo = CookieRepository(db_session)
        cookie_repo.set_cookie(profile_id=profile.id, name="li_at", value="t")
        assert cookie_repo.has_auth(profile.id) is True

    def test_has_auth_false(self, db_session, sample_fingerprint_data):
        """has_auth should return False when li_at is missing."""
        profile_repo = ProfileRepository(db_session)
        profile = self._create_profile(profile_repo, sample_fingerprint_data)

        cookie_repo = CookieRepository(db_session)
        assert cookie_repo.has_auth(profile.id) is False

    def test_get_essential_for_profile(self, db_session, sample_fingerprint_data):
        """Should return only essential cookies."""
        profile_repo = ProfileRepository(db_session)
        profile = self._create_profile(profile_repo, sample_fingerprint_data)

        cookie_repo = CookieRepository(db_session)
        cookie_repo.set_cookie(profile_id=profile.id, name="li_at", value="t")
        cookie_repo.set_cookie(profile_id=profile.id, name="JSESSIONID", value="j")
        cookie_repo.set_cookie(profile_id=profile.id, name="non_essential", value="x")

        essential = cookie_repo.get_essential_for_profile(profile.id)
        names = [c.name for c in essential]
        assert "li_at" in names
        assert "JSESSIONID" in names
        assert "non_essential" not in names

    def test_set_from_playwright(self, db_session, sample_fingerprint_data):
        """Should import cookies from Playwright format, filtering non-LinkedIn."""
        profile_repo = ProfileRepository(db_session)
        profile = self._create_profile(profile_repo, sample_fingerprint_data)

        cookie_repo = CookieRepository(db_session)
        pw_cookies = [
            {"name": "li_at", "value": "t", "domain": ".linkedin.com"},
            {"name": "JSESSIONID", "value": "j", "domain": ".linkedin.com"},
            {"name": "ga", "value": "x", "domain": ".google.com"},
        ]
        count = cookie_repo.set_from_playwright(profile.id, pw_cookies)
        assert count == 2  # Only LinkedIn cookies
        assert cookie_repo.has_auth(profile.id) is True

    def test_to_playwright_format(self, db_session, sample_fingerprint_data):
        """Should export cookies in Playwright format."""
        profile_repo = ProfileRepository(db_session)
        profile = self._create_profile(profile_repo, sample_fingerprint_data)

        cookie_repo = CookieRepository(db_session)
        cookie_repo.set_cookie(profile_id=profile.id, name="li_at", value="t")
        pw_cookies = cookie_repo.to_playwright_format(profile.id)
        assert len(pw_cookies) == 1
        assert pw_cookies[0]["name"] == "li_at"
        assert pw_cookies[0]["httpOnly"] is True

    def test_delete_for_profile(self, db_session, sample_fingerprint_data):
        """Should delete all cookies for a profile."""
        profile_repo = ProfileRepository(db_session)
        profile = self._create_profile(profile_repo, sample_fingerprint_data)

        cookie_repo = CookieRepository(db_session)
        cookie_repo.set_cookie(profile_id=profile.id, name="li_at", value="t")
        cookie_repo.set_cookie(profile_id=profile.id, name="JSESSIONID", value="j")
        count = cookie_repo.delete_for_profile(profile.id)
        assert count == 2
        assert cookie_repo.get_for_profile(profile.id) == []


# ── ChallengeEventRepository tests ──────────────────────────────

class TestChallengeEventRepository:
    """Test ChallengeEventRepository operations."""

    def _create_profile(self, db, fp_data):
        repo = ProfileRepository(db)
        return repo.create(
            uuid="challenge-test-uuid",
            linkedin_email="test@test.com",
            linkedin_password=None,
            country="US",
            timezone="America/New_York",
            fingerprint_data=fp_data,
        )

    def test_record_event(self, db_session, sample_fingerprint_data):
        """Should record a challenge event."""
        profile = self._create_profile(db_session, sample_fingerprint_data)
        repo = ChallengeEventRepository(db_session)
        event = repo.record_event(
            profile_id=profile.id,
            source_tool="read_feed",
            signal="checkpoint",
            reason="checkpoint detected",
        )
        assert event is not None
        assert event.signal == "checkpoint"
        assert event.source_tool == "read_feed"

    def test_latest_for_profile(self, db_session, sample_fingerprint_data):
        """Should return the most recent challenge event."""
        profile = self._create_profile(db_session, sample_fingerprint_data)
        repo = ChallengeEventRepository(db_session)
        repo.record_event(profile.id, "read_feed", "authwall", "first")
        repo.record_event(profile.id, "get_profile", "checkpoint", "second")
        latest = repo.latest_for_profile(profile.id)
        assert latest is not None
        assert latest.reason == "second"

    def test_latest_for_profile_none(self, db_session, sample_fingerprint_data):
        """Should return None when no events exist."""
        profile = self._create_profile(db_session, sample_fingerprint_data)
        repo = ChallengeEventRepository(db_session)
        assert repo.latest_for_profile(profile.id) is None

    def test_get_active_lock_within_cooldown(self, db_session, sample_fingerprint_data):
        """Should return lock data when event is within cooldown."""
        profile = self._create_profile(db_session, sample_fingerprint_data)
        repo = ChallengeEventRepository(db_session)
        repo.record_event(profile.id, "read_feed", "checkpoint", "detected")
        lock = repo.get_active_lock(profile.id, cooldown_minutes=15)
        assert lock is not None
        assert lock["signal"] == "checkpoint"
        assert lock["remaining_minutes"] > 0

    def test_get_active_lock_expired(self, db_session, sample_fingerprint_data):
        """Should return None when cooldown has expired."""
        profile = self._create_profile(db_session, sample_fingerprint_data)
        repo = ChallengeEventRepository(db_session)
        repo.record_event(profile.id, "read_feed", "checkpoint", "old event")
        # Manually set detected_at to past
        event = db_session.query(ProfileChallengeEvent).first()
        event.detected_at = datetime.utcnow() - timedelta(minutes=30)
        db_session.commit()
        lock = repo.get_active_lock(profile.id, cooldown_minutes=15)
        assert lock is None

    def test_get_active_lock_zero_cooldown(self, db_session, sample_fingerprint_data):
        """Should return None when cooldown is 0."""
        profile = self._create_profile(db_session, sample_fingerprint_data)
        repo = ChallengeEventRepository(db_session)
        repo.record_event(profile.id, "read_feed", "checkpoint", "detected")
        lock = repo.get_active_lock(profile.id, cooldown_minutes=0)
        assert lock is None

    def test_get_active_lock_no_events(self, db_session, sample_fingerprint_data):
        """Should return None when no events exist."""
        profile = self._create_profile(db_session, sample_fingerprint_data)
        repo = ChallengeEventRepository(db_session)
        lock = repo.get_active_lock(profile.id, cooldown_minutes=15)
        assert lock is None


# ── BrowserStateRepository tests ────────────────────────────────

class TestBrowserStateRepository:
    """Test BrowserStateRepository operations."""

    def _create_profile(self, db, fp_data):
        repo = ProfileRepository(db)
        return repo.create(
            uuid="browser-state-test-uuid",
            linkedin_email="test@test.com",
            linkedin_password=None,
            country="US",
            timezone="America/New_York",
            fingerprint_data=fp_data,
        )

    def test_get_state_none(self, db_session, sample_fingerprint_data):
        """Should return None when no state exists."""
        profile = self._create_profile(db_session, sample_fingerprint_data)
        repo = BrowserStateRepository(db_session)
        assert repo.get_state(profile.id) is None

    def test_save_and_get_state(self, db_session, sample_fingerprint_data):
        """Should save and retrieve storage state."""
        profile = self._create_profile(db_session, sample_fingerprint_data)
        repo = BrowserStateRepository(db_session)
        state = {
            "cookies": [{"name": "li_at", "value": "token", "domain": ".linkedin.com"}],
            "origins": [{"origin": "https://www.linkedin.com", "localStorage": [{"name": "key", "value": "val"}]}],
        }
        repo.save_state(profile.id, state)
        loaded = repo.get_state(profile.id)
        assert loaded is not None
        assert loaded["cookies"][0]["name"] == "li_at"
        assert loaded["origins"][0]["origin"] == "https://www.linkedin.com"
        stored = db_session.query(ProfileBrowserState).filter(
            ProfileBrowserState.profile_id == profile.id
        ).one()
        assert stored.storage_state["format"] == "fernet:v1"
        assert '"value":"token"' not in str(stored.storage_state)

    def test_save_state_upsert(self, db_session, sample_fingerprint_data):
        """Should update existing state on re-save."""
        profile = self._create_profile(db_session, sample_fingerprint_data)
        repo = BrowserStateRepository(db_session)
        repo.save_state(profile.id, {"cookies": [{"name": "old", "value": "x"}], "origins": []})
        repo.save_state(profile.id, {"cookies": [{"name": "new", "value": "y"}], "origins": []})
        loaded = repo.get_state(profile.id)
        assert loaded["cookies"][0]["name"] == "new"
        # Should not create duplicate rows
        rows = db_session.query(ProfileBrowserState).filter(
            ProfileBrowserState.profile_id == profile.id
        ).all()
        assert len(rows) == 1

    def test_delete_state(self, db_session, sample_fingerprint_data):
        """Should delete state and return True."""
        profile = self._create_profile(db_session, sample_fingerprint_data)
        repo = BrowserStateRepository(db_session)
        repo.save_state(profile.id, {"cookies": [], "origins": []})
        assert repo.delete_state(profile.id) is True
        assert repo.get_state(profile.id) is None

    def test_delete_state_not_found(self, db_session, sample_fingerprint_data):
        """Should return False when no state exists to delete."""
        profile = self._create_profile(db_session, sample_fingerprint_data)
        repo = BrowserStateRepository(db_session)
        assert repo.delete_state(profile.id) is False

    def test_cascade_delete_with_profile(self, db_session, sample_fingerprint_data):
        """Browser state should be cascade-deleted when profile is deleted."""
        profile_repo = ProfileRepository(db_session)
        profile = self._create_profile(db_session, sample_fingerprint_data)
        state_repo = BrowserStateRepository(db_session)
        state_repo.save_state(profile.id, {"cookies": [], "origins": []})
        profile_repo.delete(profile)
        assert state_repo.get_state(profile.id) is None


class TestBrowserRuntimeRepository:
    def test_per_profile_override_and_migration_state(self, db_session, sample_fingerprint_data):
        profile = ProfileRepository(db_session).create(
            uuid="runtime-test-uuid",
            linkedin_email="runtime@test.com",
            linkedin_password=None,
            country="US",
            timezone="UTC",
            fingerprint_data=sample_fingerprint_data,
        )
        repo = BrowserRuntimeRepository(db_session)
        assert repo.effective_runtime(profile.id, "legacy_injected") == "legacy_injected"
        row = repo.upsert(profile.id, "persistent_native", "validating", profile_path_version=1)
        assert row.runtime_type == "persistent_native"
        assert repo.effective_runtime(profile.id, "legacy_injected") == "persistent_native"


class TestActionLedgerRepository:
    def test_unknown_outcome_cannot_be_retried(self, db_session, sample_fingerprint_data):
        profile = ProfileRepository(db_session).create(
            uuid="ledger-test-uuid",
            linkedin_email="ledger@test.com",
            linkedin_password=None,
            country="US",
            timezone="UTC",
            fingerprint_data=sample_fingerprint_data,
        )
        repo = ActionLedgerRepository(db_session)
        row = repo.prepare(profile.id, "send_message", "request-1", "target", "payload")
        repo.transition(row, "executing")
        repo.transition(row, "unknown", error_code="SESSION_CLOSED")
        with pytest.raises(ValueError, match="must be reconciled"):
            repo.transition(row, "executing")

    def test_prepare_is_idempotent(self, db_session, sample_fingerprint_data):
        profile = ProfileRepository(db_session).create(
            uuid="ledger-idempotent-uuid",
            linkedin_email="ledger2@test.com",
            linkedin_password=None,
            country="US",
            timezone="UTC",
            fingerprint_data=sample_fingerprint_data,
        )
        repo = ActionLedgerRepository(db_session)
        first = repo.prepare(profile.id, "like_post", "request-2")
        second = repo.prepare(profile.id, "like_post", "request-2")
        assert first.id == second.id
        assert db_session.query(ProfileActionLedger).count() == 1
