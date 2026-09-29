"""Database repository for profile and cookie operations."""

import logging
from typing import Optional, List
from datetime import datetime, timedelta

from sqlalchemy.orm import Session
from sqlalchemy.exc import DBAPIError, ProgrammingError

from linkedin_mcp.db.models import (
    Profile,
    ProfileFingerprint,
    ProfileProxyConfig,
    ProfileCookie,
    ProfileChallengeEvent,
    ProfileBrowserState,
    ProfileBrowserRuntime,
    ProfileActionLedger,
    ESSENTIAL_COOKIES,
)
from linkedin_mcp.security import decrypt_envelope, encrypt_envelope, encrypt_secret

logger = logging.getLogger(__name__)


class ProfileRepository:
    """Repository for profile database operations."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_by_uuid(self, uuid: str) -> Optional[Profile]:
        """Get profile by UUID."""
        return self.db.query(Profile).filter(Profile.uuid == uuid).first()
    
    def get_by_id(self, profile_id: int) -> Optional[Profile]:
        """Get profile by ID."""
        return self.db.query(Profile).filter(Profile.id == profile_id).first()
    
    def list_active(self) -> List[Profile]:
        """List all active profiles."""
        return self.db.query(Profile).filter(Profile.is_active == True).all()
    
    def create(
        self,
        uuid: str,
        linkedin_email: str,
        linkedin_password: Optional[str],
        country: str,
        timezone: str,
        fingerprint_data: Optional[dict],
        totp_secret: Optional[str] = None,
        proxy_port: Optional[int] = None,
        state: Optional[str] = None,
        city: Optional[str] = None,
        ipfoxy_host: Optional[str] = None,
        ipfoxy_port: Optional[int] = None,
        ipfoxy_username: Optional[str] = None,
        ipfoxy_password: Optional[str] = None,
    ) -> Profile:
        """Create a new profile with fingerprint.
        
        Args:
            fingerprint_data: JSON blob with fingerprint (copy-paste from Chrome DevTools)
            proxy_port: Oxylabs sticky session port (auto-generated based on country)
            state: Optional sub-country target (normalized for Oxylabs, e.g., california)
            city: Optional city target (normalized for Oxylabs, e.g., los_angeles)
            ipfoxy_host: Dedicated IPFoxy host for this profile
            ipfoxy_port: Dedicated IPFoxy port for this profile
            ipfoxy_username: Dedicated IPFoxy username for this profile
            ipfoxy_password: Dedicated IPFoxy password for this profile
        """
        profile = Profile(
            uuid=uuid,
            linkedin_email=linkedin_email,
            linkedin_password_encrypted=encrypt_secret(linkedin_password),
            country=country.upper() if country else None,
            state=state.strip().lower().replace(" ", "_") if state else None,
            city=city.strip().lower().replace(" ", "_") if city else None,
            proxy_port=proxy_port,
            timezone=timezone,
            totp_secret=encrypt_envelope(totp_secret),
        )
        self.db.add(profile)
        self.db.flush()  # Get profile.id
        
        # Create fingerprint with JSON blob
        if fingerprint_data is not None:
            fingerprint = ProfileFingerprint(
                profile_id=profile.id,
                fingerprint_data=fingerprint_data,
            )
            self.db.add(fingerprint)

        # Persist provider-specific proxy config in extensible table
        if ipfoxy_host and ipfoxy_port and ipfoxy_username and ipfoxy_password:
            proxy_config = ProfileProxyConfig(
                profile_id=profile.id,
                provider="ipfoxy",
                host=ipfoxy_host.strip(),
                port=int(ipfoxy_port),
                username=ipfoxy_username.strip(),
                password=encrypt_envelope(ipfoxy_password),
                is_active=True,
            )
            self.db.add(proxy_config)
        
        self.db.commit()
        self.db.refresh(profile)
        
        logger.info(f"Created profile {uuid}")
        return profile
    
    def update_fingerprint(self, profile_id: int, fingerprint_data: dict) -> None:
        """Update profile fingerprint with new JSON blob."""
        fingerprint = self.db.query(ProfileFingerprint).filter(
            ProfileFingerprint.profile_id == profile_id
        ).first()
        
        if fingerprint:
            fingerprint.fingerprint_data = fingerprint_data
            fingerprint.updated_at = datetime.utcnow()
            self.db.commit()
            logger.info(f"Updated fingerprint for profile_id={profile_id}")
        else:
            raise ValueError(f"No fingerprint found for profile_id={profile_id}")
    
    def update(self, profile: Profile, **kwargs) -> Profile:
        """Update profile fields."""
        for key, value in kwargs.items():
            if key == "linkedin_password":
                profile.linkedin_password_encrypted = encrypt_secret(value)
                continue
            if hasattr(profile, key):
                setattr(profile, key, value)
        profile.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(profile)
        return profile
    
    def delete(self, profile: Profile) -> None:
        """Delete a profile (cascades to fingerprint and cookies)."""
        self.db.delete(profile)
        self.db.commit()
        logger.info(f"Deleted profile {profile.uuid}")


class CookieRepository:
    """Repository for cookie database operations."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_for_profile(self, profile_id: int) -> List[ProfileCookie]:
        """Get all cookies for a profile."""
        return self.db.query(ProfileCookie).filter(
            ProfileCookie.profile_id == profile_id
        ).all()
    
    def get_essential_for_profile(self, profile_id: int) -> List[ProfileCookie]:
        """Get essential LinkedIn cookies for a profile."""
        return self.db.query(ProfileCookie).filter(
            ProfileCookie.profile_id == profile_id,
            ProfileCookie.name.in_(ESSENTIAL_COOKIES),
        ).all()
    
    def get_by_name(self, profile_id: int, name: str) -> Optional[ProfileCookie]:
        """Get a specific cookie by name."""
        return self.db.query(ProfileCookie).filter(
            ProfileCookie.profile_id == profile_id,
            ProfileCookie.name == name,
        ).first()
    
    def get_li_at(self, profile_id: int) -> Optional[str]:
        """Get li_at cookie value (main auth token)."""
        cookie = self.get_by_name(profile_id, "li_at")
        return decrypt_envelope(cookie.value) if cookie else None
    
    def has_auth(self, profile_id: int) -> bool:
        """Check if profile has authentication cookies."""
        return self.get_by_name(profile_id, "li_at") is not None
    
    def set_cookie(
        self,
        profile_id: int,
        name: str,
        value: str,
        domain: str = ".linkedin.com",
        path: str = "/",
        secure: bool = True,
        http_only: bool = True,
        same_site: str = "None",
        expires: Optional[float] = None,
    ) -> ProfileCookie:
        """Set or update a cookie."""
        existing = self.get_by_name(profile_id, name)
        
        if existing:
            existing.value = encrypt_envelope(value)
            existing.domain = domain
            existing.path = path
            existing.secure = secure
            existing.http_only = http_only
            existing.same_site = same_site
            existing.expires = expires
            existing.updated_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(existing)
            return existing
        else:
            cookie = ProfileCookie(
                profile_id=profile_id,
                name=name,
                value=encrypt_envelope(value),
                domain=domain,
                path=path,
                secure=secure,
                http_only=http_only,
                same_site=same_site,
                expires=expires,
            )
            self.db.add(cookie)
            self.db.commit()
            self.db.refresh(cookie)
            return cookie
    
    def set_from_playwright(self, profile_id: int, cookies: List[dict]) -> int:
        """Set cookies from Playwright format (bulk update)."""
        count = 0
        for cookie in cookies:
            # Only save LinkedIn cookies
            domain = cookie.get("domain", "")
            if "linkedin.com" not in domain:
                continue
            
            self.set_cookie(
                profile_id=profile_id,
                name=cookie["name"],
                value=cookie["value"],
                domain=cookie.get("domain", ".linkedin.com"),
                path=cookie.get("path", "/"),
                secure=cookie.get("secure", True),
                http_only=cookie.get("httpOnly", True),
                same_site=cookie.get("sameSite", "None"),
                expires=cookie.get("expires"),
            )
            count += 1
        
        logger.info(f"Saved {count} cookies for profile_id={profile_id}")
        return count
    
    def to_playwright_format(self, profile_id: int) -> List[dict]:
        """Get all cookies in Playwright format."""
        cookies = self.get_for_profile(profile_id)
        return [c.to_playwright_cookie() for c in cookies]
    
    def delete_for_profile(self, profile_id: int) -> int:
        """Delete all cookies for a profile."""
        count = self.db.query(ProfileCookie).filter(
            ProfileCookie.profile_id == profile_id
        ).delete()
        self.db.commit()
        return count


class ChallengeEventRepository:
    """Repository for challenge/auth-wall event persistence and cooldown checks."""

    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _is_missing_table_error(exc: Exception) -> bool:
        """Return True when DB error indicates profile_challenge_events table is absent."""
        message = str(exc).lower()
        return "profile_challenge_events" in message and (
            "undefinedtable" in message or "does not exist" in message or "no such table" in message
        )

    def record_event(
        self,
        profile_id: int,
        source_tool: str,
        signal: str,
        reason: str,
        page_url: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> Optional[ProfileChallengeEvent]:
        try:
            event = ProfileChallengeEvent(
                profile_id=profile_id,
                source_tool=source_tool,
                signal=signal,
                reason=reason,
                page_url=page_url,
                details=details,
                detected_at=datetime.utcnow(),
            )
            self.db.add(event)
            self.db.flush()
            return event
        except (ProgrammingError, DBAPIError) as exc:
            if self._is_missing_table_error(exc):
                logger.warning("Challenge events table missing; skipping event record")
                self.db.rollback()
                return None
            raise

    def latest_for_profile(self, profile_id: int) -> Optional[ProfileChallengeEvent]:
        try:
            return (
                self.db.query(ProfileChallengeEvent)
                .filter(ProfileChallengeEvent.profile_id == profile_id)
                .order_by(ProfileChallengeEvent.detected_at.desc())
                .first()
            )
        except (ProgrammingError, DBAPIError) as exc:
            if self._is_missing_table_error(exc):
                logger.warning("Challenge events table missing; skipping challenge lock read")
                self.db.rollback()
                return None
            raise

    def get_active_lock(
        self,
        profile_id: int,
        cooldown_minutes: int,
        now: Optional[datetime] = None,
    ) -> Optional[dict]:
        if cooldown_minutes <= 0:
            return None

        latest = self.latest_for_profile(profile_id)
        if not latest:
            return None

        now = now or datetime.utcnow()
        expires_at = latest.detected_at + timedelta(minutes=cooldown_minutes)
        if now >= expires_at:
            return None

        remaining_seconds = max(1, int((expires_at - now).total_seconds()))
        return {
            "latest_event_id": latest.id,
            "signal": latest.signal,
            "reason": latest.reason,
            "source_tool": latest.source_tool,
            "detected_at": latest.detected_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "remaining_seconds": remaining_seconds,
            "remaining_minutes": round(remaining_seconds / 60, 2),
        }


class BrowserStateRepository:
    """Repository for browser storage state (cookies + localStorage) per profile.

    Stores the Playwright/Patchright storage_state JSON blob so each profile
    can restore its browser session from the database instead of a filesystem
    user_data_dir. The state includes:
    - cookies (all domains, with attributes)
    - origins (localStorage key-value pairs per origin)
    """

    def __init__(self, db: Session):
        self.db = db

    def get_state(self, profile_id: int) -> Optional[dict]:
        """Get the stored storage_state JSON for a profile.

        Returns:
            The storage_state dict (with 'cookies' and 'origins' keys),
            or None if no state has been saved yet.
        """
        row = self.db.query(ProfileBrowserState).filter(
            ProfileBrowserState.profile_id == profile_id
        ).first()
        if not row:
            return None
        state = row.storage_state
        if isinstance(state, dict) and state.get("format") == "fernet:v1":
            import json

            plaintext = decrypt_envelope(state.get("ciphertext"))
            return json.loads(plaintext) if plaintext else None
        return state

    def save_state(self, profile_id: int, storage_state: dict) -> None:
        """Insert or update the storage_state for a profile.

        Args:
            profile_id: The profile's database ID.
            storage_state: The Playwright storage_state dict containing
                           cookies and localStorage origins.
        """
        import json

        encrypted_state = {
            "format": "fernet:v1",
            "ciphertext": encrypt_envelope(json.dumps(storage_state, separators=(",", ":"))),
        }
        existing = self.db.query(ProfileBrowserState).filter(
            ProfileBrowserState.profile_id == profile_id
        ).first()

        if existing:
            existing.storage_state = encrypted_state
            existing.updated_at = datetime.utcnow()
        else:
            row = ProfileBrowserState(
                profile_id=profile_id,
                storage_state=encrypted_state,
            )
            self.db.add(row)

        self.db.commit()
        logger.info(f"Saved browser state for profile_id={profile_id}")

    def delete_state(self, profile_id: int) -> bool:
        """Delete the stored browser state for a profile.

        Returns:
            True if state was deleted, False if no state existed.
        """
        row = self.db.query(ProfileBrowserState).filter(
            ProfileBrowserState.profile_id == profile_id
        ).first()
        if not row:
            return False
        self.db.delete(row)
        self.db.commit()
        return True


class BrowserRuntimeRepository:
    """Manage per-profile runtime selection and migration state."""

    VALID_RUNTIMES = {"legacy_injected", "persistent_native"}
    VALID_STATUSES = {"pending", "validating", "complete", "failed"}

    def __init__(self, db: Session):
        self.db = db

    def get(self, profile_id: int) -> Optional[ProfileBrowserRuntime]:
        return self.db.query(ProfileBrowserRuntime).filter(
            ProfileBrowserRuntime.profile_id == profile_id
        ).first()

    def effective_runtime(self, profile_id: int, default: str) -> str:
        row = self.get(profile_id)
        return row.runtime_type if row else default

    def upsert(
        self,
        profile_id: int,
        runtime_type: str,
        migration_status: str,
        **metadata,
    ) -> ProfileBrowserRuntime:
        if runtime_type not in self.VALID_RUNTIMES:
            raise ValueError(f"Invalid browser runtime: {runtime_type}")
        if migration_status not in self.VALID_STATUSES:
            raise ValueError(f"Invalid migration status: {migration_status}")
        row = self.get(profile_id)
        if row is None:
            row = ProfileBrowserRuntime(profile_id=profile_id)
            self.db.add(row)
        row.runtime_type = runtime_type
        row.migration_status = migration_status
        for field in (
            "profile_path_version",
            "chrome_version",
            "patchright_version",
            "initialized_at",
            "last_verified_at",
        ):
            if field in metadata:
                setattr(row, field, metadata[field])
        self.db.flush()
        return row


class ActionLedgerRepository:
    """Persist write intent so uncertain submissions are never retried blindly."""

    VALID_STATES = {"prepared", "executing", "succeeded", "failed", "unknown"}

    def __init__(self, db: Session):
        self.db = db

    def get(self, profile_id: int, action_type: str, idempotency_key: str) -> Optional[ProfileActionLedger]:
        return self.db.query(ProfileActionLedger).filter(
            ProfileActionLedger.profile_id == profile_id,
            ProfileActionLedger.action_type == action_type,
            ProfileActionLedger.idempotency_key == idempotency_key,
        ).first()

    def prepare(
        self,
        profile_id: int,
        action_type: str,
        idempotency_key: str,
        target_identity_hash: Optional[str] = None,
        payload_hash: Optional[str] = None,
    ) -> ProfileActionLedger:
        existing = self.get(profile_id, action_type, idempotency_key)
        if existing:
            return existing
        row = ProfileActionLedger(
            profile_id=profile_id,
            action_type=action_type,
            idempotency_key=idempotency_key,
            target_identity_hash=target_identity_hash,
            payload_hash=payload_hash,
            state="prepared",
        )
        self.db.add(row)
        self.db.flush()
        return row

    def transition(
        self,
        row: ProfileActionLedger,
        state: str,
        result_identity: Optional[str] = None,
        error_code: Optional[str] = None,
    ) -> ProfileActionLedger:
        if state not in self.VALID_STATES:
            raise ValueError(f"Invalid action-ledger state: {state}")
        if row.state == "unknown" and state == "executing":
            raise ValueError("An unknown write outcome must be reconciled before retry")
        row.state = state
        row.result_identity = result_identity
        row.sanitized_error_code = error_code
        if state in {"succeeded", "failed", "unknown"}:
            row.completed_at = datetime.utcnow()
        self.db.flush()
        return row
