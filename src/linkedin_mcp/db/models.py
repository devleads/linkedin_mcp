"""SQLAlchemy models for LinkedIn MCP Server."""

from datetime import datetime
from typing import Optional, List
import json

from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Boolean,
    Float,
    DateTime,
    ForeignKey,
    JSON,
    Index,
    UniqueConstraint,
    CheckConstraint,
)
from sqlalchemy.orm import relationship

from linkedin_mcp.db.base import Base


class Profile(Base):
    """LinkedIn profile configuration stored in database."""
    
    __tablename__ = "profiles"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    uuid = Column(String(36), unique=True, nullable=False, index=True)
    linkedin_email = Column(String(255), nullable=False)
    linkedin_password_encrypted = Column(Text, nullable=True)
    country = Column(String(10), nullable=True)  # ISO country code (null = no proxy)
    state = Column(String(64), nullable=True)  # Optional sub-country targeting (e.g., california)
    city = Column(String(96), nullable=True)  # Optional city targeting (e.g., los_angeles)
    proxy_port = Column(Integer, nullable=True)  # Oxylabs sticky session port (10000-49999)
    timezone = Column(String(50), nullable=True)  # IANA timezone
    totp_secret = Column(Text, nullable=True)  # Versioned encrypted 2FA secret
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    fingerprint = relationship("ProfileFingerprint", back_populates="profile", uselist=False, cascade="all, delete-orphan")
    cookies = relationship("ProfileCookie", back_populates="profile", cascade="all, delete-orphan")
    challenge_events = relationship("ProfileChallengeEvent", back_populates="profile", cascade="all, delete-orphan")
    proxy_configs = relationship("ProfileProxyConfig", back_populates="profile", cascade="all, delete-orphan")
    browser_state = relationship("ProfileBrowserState", back_populates="profile", uselist=False, cascade="all, delete-orphan")
    browser_runtime = relationship("ProfileBrowserRuntime", back_populates="profile", uselist=False, cascade="all, delete-orphan")
    action_ledger_entries = relationship("ProfileActionLedger", back_populates="profile", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Profile(uuid={self.uuid}, email={self.linkedin_email}, country={self.country})>"


class ProfileFingerprint(Base):
    """Browser fingerprint configuration for a profile.
    
    Stores fingerprint as a single JSON blob for easy copy-paste from Chrome DevTools.
    """
    
    __tablename__ = "profile_fingerprints"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    profile_id = Column(Integer, ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, unique=True)
    fingerprint_data = Column(JSON, nullable=False)  # Single JSON blob with all fingerprint data
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    profile = relationship("Profile", back_populates="fingerprint")
    
    # Property accessors for backward compatibility
    @property
    def user_agent(self) -> str:
        return self.fingerprint_data.get("user_agent", "")
    
    @property
    def platform(self) -> str:
        return self.fingerprint_data.get("platform", "")
    
    @property
    def screen_width(self) -> int:
        return self.fingerprint_data.get("screen_width", 1920)
    
    @property
    def screen_height(self) -> int:
        return self.fingerprint_data.get("screen_height", 1080)
    
    @property
    def color_depth(self) -> int:
        return self.fingerprint_data.get("color_depth", 24)
    
    @property
    def hardware_concurrency(self) -> int:
        return self.fingerprint_data.get("hardware_concurrency", 8)
    
    @property
    def device_memory(self) -> int:
        return self.fingerprint_data.get("device_memory", 8)
    
    @property
    def languages(self) -> list:
        return self.fingerprint_data.get("languages", ["en-US", "en"])
    
    @property
    def webgl_vendor(self) -> str:
        return self.fingerprint_data.get("webgl_vendor", "Google Inc.")
    
    @property
    def webgl_renderer(self) -> str:
        return self.fingerprint_data.get("webgl_renderer", "")
    
    def to_dict(self) -> dict:
        """Convert to dictionary for browser config."""
        return self.fingerprint_data.copy()
    
    def __repr__(self):
        return f"<ProfileFingerprint(profile_id={self.profile_id}, platform={self.platform})>"


class ProfileCookie(Base):
    """LinkedIn cookies stored for a profile."""
    
    __tablename__ = "profile_cookies"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    profile_id = Column(Integer, ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    value = Column(Text, nullable=False)
    domain = Column(String(255), default=".linkedin.com", nullable=False)
    path = Column(String(255), default="/", nullable=False)
    secure = Column(Boolean, default=True, nullable=False)
    http_only = Column(Boolean, default=True, nullable=False)
    same_site = Column(String(20), default="None", nullable=False)
    expires = Column(Float, nullable=True)  # Unix timestamp
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Unique constraint: one cookie name per profile
    __table_args__ = (
        UniqueConstraint("profile_id", "name", name="uq_profile_cookie_name"),
    )
    
    # Relationships
    profile = relationship("Profile", back_populates="cookies")
    
    def to_playwright_cookie(self) -> dict:
        """Convert to Playwright/Patchright cookie format."""
        from linkedin_mcp.security import decrypt_envelope

        cookie = {
            "name": self.name,
            "value": decrypt_envelope(self.value) or "",
            "domain": self.domain,
            "path": self.path,
            "secure": self.secure,
            "httpOnly": self.http_only,
            "sameSite": self.same_site,
        }
        if self.expires:
            cookie["expires"] = self.expires
        return cookie
    
    @classmethod
    def from_playwright_cookie(cls, profile_id: int, cookie: dict) -> "ProfileCookie":
        """Create from Playwright/Patchright cookie."""
        from linkedin_mcp.security import encrypt_envelope

        return cls(
            profile_id=profile_id,
            name=cookie["name"],
            value=encrypt_envelope(cookie["value"]),
            domain=cookie.get("domain", ".linkedin.com"),
            path=cookie.get("path", "/"),
            secure=cookie.get("secure", True),
            http_only=cookie.get("httpOnly", True),
            same_site=cookie.get("sameSite", "None"),
            expires=cookie.get("expires"),
        )
    
    def __repr__(self):
        return f"<ProfileCookie(profile_id={self.profile_id}, name={self.name})>"


class ProfileChallengeEvent(Base):
    """Challenge/auth-wall event records used for temporary profile cooldown lock."""

    __tablename__ = "profile_challenge_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    profile_id = Column(Integer, ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    source_tool = Column(String(64), nullable=False)
    signal = Column(String(64), nullable=False)
    reason = Column(Text, nullable=False)
    page_url = Column(Text, nullable=True)
    details = Column(JSON, nullable=True)
    detected_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_profile_challenge_events_profile_detected", "profile_id", "detected_at"),
    )

    profile = relationship("Profile", back_populates="challenge_events")

    def __repr__(self):
        return (
            f"<ProfileChallengeEvent(profile_id={self.profile_id}, "
            f"signal={self.signal}, detected_at={self.detected_at})>"
        )


class ProfileProxyConfig(Base):
    """Provider-specific proxy configuration per profile (extensible for future services)."""

    __tablename__ = "profile_proxy_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    profile_id = Column(Integer, ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    provider = Column(String(32), nullable=False)  # e.g., ipfoxy, oxylabs, brightdata
    host = Column(String(255), nullable=True)
    port = Column(Integer, nullable=True)
    username = Column(String(255), nullable=True)
    password = Column(Text, nullable=True)
    config = Column(JSON, nullable=True)  # optional provider-specific extras
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("profile_id", "provider", name="uq_profile_proxy_provider"),
        Index("ix_profile_proxy_configs_profile_provider", "profile_id", "provider"),
    )

    profile = relationship("Profile", back_populates="proxy_configs")

    def __repr__(self):
        return f"<ProfileProxyConfig(profile_id={self.profile_id}, provider={self.provider})>"


class ProfileBrowserState(Base):
    """Browser storage state (cookies + localStorage) persisted per profile.

    Stores the Playwright/Patchright storage_state JSON blob so each profile
    can restore its browser session without a persistent user_data_dir on disk.
    The state includes:
    - cookies (all domains)
    - origins (localStorage key-value pairs per origin)

    This replaces the filesystem-based PROFILE_STORAGE_PATH approach.
    """

    __tablename__ = "profile_browser_states"

    id = Column(Integer, primary_key=True, autoincrement=True)
    profile_id = Column(Integer, ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, unique=True)
    storage_state = Column(JSON, nullable=False)  # Playwright storage_state blob
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    profile = relationship("Profile", back_populates="browser_state")

    def __repr__(self):
        return f"<ProfileBrowserState(profile_id={self.profile_id})>"


class ProfileBrowserRuntime(Base):
    """Per-profile browser runtime selection and migration state."""

    __tablename__ = "profile_browser_runtimes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    profile_id = Column(Integer, ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, unique=True)
    runtime_type = Column(String(32), nullable=False, default="legacy_injected")
    profile_path_version = Column(Integer, nullable=False, default=1)
    migration_status = Column(String(32), nullable=False, default="pending")
    chrome_version = Column(String(64), nullable=True)
    patchright_version = Column(String(64), nullable=True)
    initialized_at = Column(DateTime, nullable=True)
    last_verified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    profile = relationship("Profile", back_populates="browser_runtime")

    __table_args__ = (
        CheckConstraint(
            "runtime_type IN ('legacy_injected', 'persistent_native')",
            name="ck_profile_browser_runtime_type",
        ),
        CheckConstraint(
            "migration_status IN ('pending', 'validating', 'complete', 'failed')",
            name="ck_profile_browser_migration_status",
        ),
    )


class ProfileActionLedger(Base):
    """Durable intent and outcome record for LinkedIn write actions."""

    __tablename__ = "profile_action_ledger"

    id = Column(Integer, primary_key=True, autoincrement=True)
    profile_id = Column(Integer, ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    action_type = Column(String(64), nullable=False)
    idempotency_key = Column(String(128), nullable=False)
    target_identity_hash = Column(String(64), nullable=True)
    payload_hash = Column(String(64), nullable=True)
    state = Column(String(16), nullable=False, default="prepared")
    result_identity = Column(String(255), nullable=True)
    sanitized_error_code = Column(String(64), nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "profile_id",
            "action_type",
            "idempotency_key",
            name="uq_profile_action_idempotency",
        ),
        Index("ix_profile_action_ledger_profile_started", "profile_id", "started_at"),
        CheckConstraint(
            "state IN ('prepared', 'executing', 'succeeded', 'failed', 'unknown')",
            name="ck_profile_action_ledger_state",
        ),
    )

    profile = relationship("Profile", back_populates="action_ledger_entries")


# Essential LinkedIn cookies to preserve
ESSENTIAL_COOKIES = [
    "li_at",       # Main auth token
    "JSESSIONID",  # Session ID
    "bcookie",     # Browser ID
    "bscookie",    # Secure browser cookie
    "li_gc",       # GDPR consent
    "lidc",        # Datacenter routing
    "li_rm",       # Remember me
    "lang",        # Language preference
]
