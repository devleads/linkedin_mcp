"""Profile models for LinkedIn accounts."""

from dataclasses import dataclass, field
from typing import Optional, List
import json
import os
from pathlib import Path


@dataclass
class ProfileFingerprint:
    """Browser fingerprint configuration for a profile."""
    user_agent: str
    platform: str  # Win32, MacIntel, Linux x86_64
    screen_width: int = 1920
    screen_height: int = 1080
    color_depth: int = 24
    hardware_concurrency: int = 8
    device_memory: int = 8
    languages: List[str] = field(default_factory=lambda: ["en-US", "en"])
    webgl_vendor: str = "Google Inc."
    webgl_renderer: str = "ANGLE (Intel, Intel(R) UHD Graphics 630)"
    
    def to_dict(self) -> dict:
        return {
            "user_agent": self.user_agent,
            "platform": self.platform,
            "screen_width": self.screen_width,
            "screen_height": self.screen_height,
            "color_depth": self.color_depth,
            "hardware_concurrency": self.hardware_concurrency,
            "device_memory": self.device_memory,
            "languages": self.languages,
            "webgl_vendor": self.webgl_vendor,
            "webgl_renderer": self.webgl_renderer,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "ProfileFingerprint":
        return cls(**data)


@dataclass
class Profile:
    """LinkedIn profile configuration."""
    id: str  # Unique profile identifier
    linkedin_email: str
    country: str  # ISO country code for proxy (e.g., "US", "AE", "GB")
    timezone: str  # IANA timezone (e.g., "America/New_York", "Asia/Dubai")
    fingerprint: ProfileFingerprint
    linkedin_password_encrypted: Optional[str] = None
    state: Optional[str] = None  # Optional sub-country target (e.g., "california")
    city: Optional[str] = None  # Optional city target (e.g., "los_angeles")
    ipfoxy_host: Optional[str] = None
    ipfoxy_port: Optional[int] = None
    ipfoxy_username: Optional[str] = None
    ipfoxy_password: Optional[str] = None
    totp_secret: Optional[str] = None  # For 2FA (TOTP)
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "linkedin_email": self.linkedin_email,
            "linkedin_password_encrypted": self.linkedin_password_encrypted,
            "country": self.country,
            "state": self.state,
            "city": self.city,
            "ipfoxy_host": self.ipfoxy_host,
            "ipfoxy_port": self.ipfoxy_port,
            "ipfoxy_username": self.ipfoxy_username,
            "ipfoxy_password": self.ipfoxy_password,
            "timezone": self.timezone,
            "fingerprint": self.fingerprint.to_dict(),
            "totp_secret": self.totp_secret,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Profile":
        fingerprint = ProfileFingerprint.from_dict(data["fingerprint"])
        return cls(
            id=data["id"],
            linkedin_email=data["linkedin_email"],
            country=data["country"],
            linkedin_password_encrypted=data.get("linkedin_password_encrypted"),
            state=data.get("state"),
            city=data.get("city"),
            ipfoxy_host=data.get("ipfoxy_host"),
            ipfoxy_port=data.get("ipfoxy_port"),
            ipfoxy_username=data.get("ipfoxy_username"),
            ipfoxy_password=data.get("ipfoxy_password"),
            timezone=data["timezone"],
            fingerprint=fingerprint,
            totp_secret=data.get("totp_secret"),
        )
    
    def save(self, storage_path: str) -> None:
        """Save profile to JSON file."""
        profile_dir = Path(storage_path) / self.id
        profile_dir.mkdir(parents=True, exist_ok=True)
        
        profile_file = profile_dir / "profile.json"
        with open(profile_file, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
    
    @classmethod
    def load(cls, profile_id: str, storage_path: str) -> Optional["Profile"]:
        """Load profile from JSON file."""
        profile_file = Path(storage_path) / profile_id / "profile.json"
        if not profile_file.exists():
            return None
        
        with open(profile_file, "r") as f:
            data = json.load(f)
        return cls.from_dict(data)
    
    @classmethod
    def list_profiles(cls, storage_path: str) -> List[str]:
        """List all profile IDs in storage."""
        storage = Path(storage_path)
        if not storage.exists():
            return []
        
        profiles = []
        for item in storage.iterdir():
            if item.is_dir() and (item / "profile.json").exists():
                profiles.append(item.name)
        return profiles
