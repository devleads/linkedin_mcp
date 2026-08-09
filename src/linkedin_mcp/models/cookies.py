"""Cookie management for LinkedIn sessions."""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
import json
from pathlib import Path
from datetime import datetime


@dataclass
class CookieData:
    """Single cookie data."""
    name: str
    value: str
    domain: str = ".linkedin.com"
    path: str = "/"
    secure: bool = True
    http_only: bool = True
    same_site: str = "None"
    expires: Optional[float] = None  # Unix timestamp
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "value": self.value,
            "domain": self.domain,
            "path": self.path,
            "secure": self.secure,
            "httpOnly": self.http_only,
            "sameSite": self.same_site,
            "expires": self.expires,
        }
    
    def to_playwright_cookie(self) -> dict:
        """Convert to Playwright/Patchright cookie format."""
        cookie = {
            "name": self.name,
            "value": self.value,
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
    def from_dict(cls, data: dict) -> "CookieData":
        return cls(
            name=data["name"],
            value=data["value"],
            domain=data.get("domain", ".linkedin.com"),
            path=data.get("path", "/"),
            secure=data.get("secure", True),
            http_only=data.get("httpOnly", True),
            same_site=data.get("sameSite", "None"),
            expires=data.get("expires"),
        )
    
    @classmethod
    def from_playwright_cookie(cls, cookie: dict) -> "CookieData":
        """Create from Playwright/Patchright cookie."""
        return cls(
            name=cookie["name"],
            value=cookie["value"],
            domain=cookie.get("domain", ".linkedin.com"),
            path=cookie.get("path", "/"),
            secure=cookie.get("secure", True),
            http_only=cookie.get("httpOnly", True),
            same_site=cookie.get("sameSite", "None"),
            expires=cookie.get("expires"),
        )


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


class CookieStore:
    """Manages cookies for a profile."""
    
    def __init__(self, profile_id: str, storage_path: str):
        self.profile_id = profile_id
        self.storage_path = storage_path
        self._cookies: Dict[str, CookieData] = {}
        self._load()
    
    @property
    def cookies_file(self) -> Path:
        return Path(self.storage_path) / self.profile_id / "cookies.json"
    
    def _load(self) -> None:
        """Load cookies from file."""
        if not self.cookies_file.exists():
            return
        
        try:
            with open(self.cookies_file, "r") as f:
                data = json.load(f)
            
            for cookie_data in data.get("cookies", []):
                cookie = CookieData.from_dict(cookie_data)
                self._cookies[cookie.name] = cookie
        except Exception:
            pass
    
    def save(self) -> None:
        """Save cookies to file."""
        self.cookies_file.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            "profile_id": self.profile_id,
            "updated_at": datetime.utcnow().isoformat(),
            "cookies": [c.to_dict() for c in self._cookies.values()],
        }
        
        with open(self.cookies_file, "w") as f:
            json.dump(data, f, indent=2)
    
    def set(self, cookie: CookieData) -> None:
        """Set a cookie."""
        self._cookies[cookie.name] = cookie
    
    def set_many(self, cookies: List[CookieData]) -> None:
        """Set multiple cookies."""
        for cookie in cookies:
            self._cookies[cookie.name] = cookie
    
    def get(self, name: str) -> Optional[CookieData]:
        """Get a cookie by name."""
        return self._cookies.get(name)
    
    def get_all(self) -> List[CookieData]:
        """Get all cookies."""
        return list(self._cookies.values())
    
    def get_essential(self) -> List[CookieData]:
        """Get essential LinkedIn cookies."""
        return [c for c in self._cookies.values() if c.name in ESSENTIAL_COOKIES]
    
    def get_li_at(self) -> Optional[str]:
        """Get li_at cookie value (main auth token)."""
        cookie = self._cookies.get("li_at")
        return cookie.value if cookie else None
    
    def has_auth(self) -> bool:
        """Check if we have authentication cookies."""
        return "li_at" in self._cookies
    
    def to_playwright_cookies(self) -> List[dict]:
        """Convert all cookies to Playwright format."""
        return [c.to_playwright_cookie() for c in self._cookies.values()]
    
    def update_from_browser(self, browser_cookies: List[dict]) -> None:
        """Update cookies from browser (Playwright format)."""
        for bc in browser_cookies:
            # Only save LinkedIn cookies
            domain = bc.get("domain", "")
            if "linkedin.com" not in domain:
                continue
            
            cookie = CookieData.from_playwright_cookie(bc)
            self._cookies[cookie.name] = cookie
    
    def clear(self) -> None:
        """Clear all cookies."""
        self._cookies.clear()
        if self.cookies_file.exists():
            self.cookies_file.unlink()
