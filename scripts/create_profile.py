#!/usr/bin/env python3
"""Create a new LinkedIn profile configuration.

This script creates a profile in the PostgreSQL database.
Profile UUID is auto-generated. Fingerprint can be piped from clipboard.

Usage:
    # With fingerprint from clipboard (RECOMMENDED):
    pbpaste | uv run python scripts/create_profile.py <country> <timezone> --li_at=<cookie>
    
    # Without fingerprint (clone later):
    uv run python scripts/create_profile.py <country> <timezone> --li_at=<cookie>

Examples:
    # Best: Fingerprint + li_at cookie
    pbpaste | uv run python scripts/create_profile.py AE Asia/Dubai --li_at="AQEDAQNxyz..."
    
    # Create profile, clone fingerprint later
    uv run python scripts/create_profile.py AE Asia/Dubai --li_at="AQEDAQNxyz..."
    pbpaste | uv run python scripts/clone_fingerprint.py <profile-uuid>
"""

import sys
import uuid
from pathlib import Path
from typing import Optional

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linkedin_mcp.db import get_db
from linkedin_mcp.db.repository import ProfileRepository
from linkedin_mcp.config import get_settings
from linkedin_mcp.proxy.oxylabs import get_proxy_provider


# Default fingerprint (placeholder - should be replaced with real Chrome fingerprint)
DEFAULT_FINGERPRINT = {
    "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
    "platform": "MacIntel",
    "screen_width": 1920,
    "screen_height": 1080,
    "color_depth": 24,
    "hardware_concurrency": 8,
    "device_memory": 8,
    "languages": ["en-US", "en"],
    "webgl_vendor": "Google Inc.",
    "webgl_renderer": "ANGLE (Intel, Intel Iris OpenGL Engine)",
}


def create_profile(
    profile_uuid: str,
    country: str,
    timezone: str,
    state: Optional[str] = None,
    city: Optional[str] = None,
    ipfoxy_host: Optional[str] = None,
    ipfoxy_port: Optional[int] = None,
    ipfoxy_username: Optional[str] = None,
    ipfoxy_password: Optional[str] = None,
    email: str = "",
    password: str = "",
    totp_secret: str = None,
    li_at: str = None,
    fingerprint_json: str = None,
):
    """Create a new profile in the database.
    
    Args:
        profile_uuid: Unique identifier for the profile
        country: ISO country code (US, AE, GB, etc.)
        state: Optional sub-country target (e.g., california)
        city: Optional city target (e.g., los_angeles)
        ipfoxy_host: Dedicated IPFoxy host (per profile)
        ipfoxy_port: Dedicated IPFoxy port (per profile)
        ipfoxy_username: Dedicated IPFoxy username (per profile)
        ipfoxy_password: Dedicated IPFoxy password (per profile)
        timezone: IANA timezone (America/New_York, Asia/Dubai, etc.)
        email: LinkedIn email (optional if using li_at)
        password: LinkedIn password (optional if using li_at)
        totp_secret: TOTP secret for 2FA (optional)
        li_at: LinkedIn auth cookie (recommended for purchased accounts)
        fingerprint_json: JSON string with fingerprint data from Chrome DevTools
    
    Returns:
        dict with profile info (uuid, id, country, timezone)
    """
    import json
    
    if fingerprint_json:
        fingerprint_data = json.loads(fingerprint_json)
    else:
        fingerprint_data = DEFAULT_FINGERPRINT.copy()
    
    with get_db() as db:
        profile_repo = ProfileRepository(db)
        settings = get_settings()
        
        # Check if profile already exists
        existing = profile_repo.get_by_uuid(profile_uuid)
        if existing:
            raise ValueError(f"Profile {profile_uuid} already exists")
        
        # Generate sticky proxy port for the country
        proxy_port = None
        if settings.proxy_provider == "oxylabs" and country:
            proxy_provider = get_proxy_provider()
            proxy_port = proxy_provider.generate_port_for_country(country.upper())

        if settings.proxy_provider == "ipfoxy":
            missing_fields = []
            if not ipfoxy_host:
                missing_fields.append("--ipfoxy-host")
            if ipfoxy_port is None:
                missing_fields.append("--ipfoxy-port")
            if not ipfoxy_username:
                missing_fields.append("--ipfoxy-username")
            if not ipfoxy_password:
                missing_fields.append("--ipfoxy-password")
            if missing_fields:
                missing_csv = ", ".join(missing_fields)
                raise ValueError(
                    "PROXY_PROVIDER=ipfoxy requires per-profile dedicated proxy fields: "
                    f"{missing_csv}"
                )
        
        profile = profile_repo.create(
            uuid=profile_uuid,
            linkedin_email=email or "cookie-auth@linkedin.com",
            linkedin_password=password or None,
            country=country.upper() if country else None,
            state=state,
            city=city,
            proxy_port=proxy_port,
            ipfoxy_host=ipfoxy_host,
            ipfoxy_port=ipfoxy_port,
            ipfoxy_username=ipfoxy_username,
            ipfoxy_password=ipfoxy_password,
            timezone=timezone,
            fingerprint_data=fingerprint_data,
            totp_secret=totp_secret,
        )
        
        # Set li_at cookie if provided
        if li_at:
            from linkedin_mcp.db.repository import CookieRepository
            cookie_repo = CookieRepository(db)
            cookie_repo.set_cookie(
                profile_id=profile.id,
                name="li_at",
                value=li_at,
            )
        
        # Return dict with profile info (before session closes)
        return {
            "uuid": profile.uuid,
            "id": profile.id,
            "country": profile.country,
            "state": profile.state,
            "city": profile.city,
            "proxy_port": profile.proxy_port,
            "ipfoxy_host": ipfoxy_host,
            "ipfoxy_port": ipfoxy_port,
            "ipfoxy_username": ipfoxy_username,
            "timezone": profile.timezone,
        }


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        print("\nRequired arguments: country timezone")
        print("\nOptional arguments:")
        print("  --li_at=<cookie>      LinkedIn auth cookie (RECOMMENDED)")
        print("  --email=<email>       LinkedIn email")
        print("  --password=<password> LinkedIn password")
        print("  --state=<state>       Optional state/region (e.g., california)")
        print("  --city=<city>         Optional city (e.g., los_angeles)")
        print("  --ipfoxy-host=<host>  Dedicated IPFoxy host (per profile)")
        print("  --ipfoxy-port=<port>  Dedicated IPFoxy port (per profile)")
        print("  --ipfoxy-username=<u> Dedicated IPFoxy username (per profile)")
        print("  --ipfoxy-password=<p> Dedicated IPFoxy password (per profile)")
        print("  --totp=<secret>       TOTP secret for 2FA")
        print("\nFingerprint: Paste JSON from Chrome DevTools when prompted")
        sys.exit(1)
    
    country = sys.argv[1].upper()
    timezone = sys.argv[2]
    
    # Auto-generate proper UUID
    profile_uuid = str(uuid.uuid4())
    
    # Parse optional arguments
    totp_secret = None
    email = ""
    password = ""
    li_at = None
    state = None
    city = None
    ipfoxy_host = None
    ipfoxy_port = None
    ipfoxy_username = None
    ipfoxy_password = None
    
    for arg in sys.argv[3:]:
        if arg.startswith("--totp="):
            totp_secret = arg.split("=", 1)[1]
        elif arg.startswith("--email="):
            email = arg.split("=", 1)[1]
        elif arg.startswith("--password="):
            password = arg.split("=", 1)[1]
        elif arg.startswith("--li_at="):
            li_at = arg.split("=", 1)[1]
        elif arg.startswith("--state="):
            state = arg.split("=", 1)[1]
        elif arg.startswith("--city="):
            city = arg.split("=", 1)[1]
        elif arg.startswith("--ipfoxy-host="):
            ipfoxy_host = arg.split("=", 1)[1]
        elif arg.startswith("--ipfoxy-port="):
            ipfoxy_port = int(arg.split("=", 1)[1])
        elif arg.startswith("--ipfoxy-username="):
            ipfoxy_username = arg.split("=", 1)[1]
        elif arg.startswith("--ipfoxy-password="):
            ipfoxy_password = arg.split("=", 1)[1]
    
    print(f"Creating profile: {profile_uuid}")
    print(f"  Country: {country}")
    print(f"  State: {state or '(country-only)'}")
    print(f"  City: {city or '(none)'}")
    print(f"  IPFoxy Host: {ipfoxy_host or '(none)'}")
    print(f"  IPFoxy Port: {ipfoxy_port or '(none)'}")
    print(f"  IPFoxy Username: {(ipfoxy_username[:5] + '***') if ipfoxy_username else '(none)'}")
    print(f"  Timezone: {timezone}")
    print(f"  Auth: {'li_at cookie' if li_at else 'credentials' if email else 'none (set later)'}")
    
    # Read fingerprint JSON from stdin if available
    import select
    fingerprint_json = None
    
    # Check if there's data on stdin (piped input)
    if select.select([sys.stdin], [], [], 0.0)[0]:
        fingerprint_json = sys.stdin.read().strip()
        if fingerprint_json:
            print(f"  Fingerprint: from stdin ✓")
    
    if not fingerprint_json:
        print(f"  Fingerprint: default (clone later with clone_fingerprint.py)")
    
    try:
        profile_data = create_profile(
            profile_uuid=profile_uuid,
            country=country,
            state=state,
            city=city,
            ipfoxy_host=ipfoxy_host,
            ipfoxy_port=ipfoxy_port,
            ipfoxy_username=ipfoxy_username,
            ipfoxy_password=ipfoxy_password,
            timezone=timezone,
            email=email,
            password=password,
            totp_secret=totp_secret,
            li_at=li_at,
            fingerprint_json=fingerprint_json,
        )
        
        print(f"\nProfile created successfully!")
        print(f"  UUID: {profile_data['uuid']}")
        print(f"  ID: {profile_data['id']}")
        print(f"  Country: {profile_data['country']}")
        print(f"  State: {profile_data.get('state') or '(none)'}")
        print(f"  City: {profile_data.get('city') or '(none)'}")
        if profile_data.get("proxy_port") is not None:
            print(f"  Proxy Port: {profile_data['proxy_port']} (oxylabs sticky session)")
        if profile_data.get("ipfoxy_host"):
            print(
                f"  IPFoxy: {profile_data.get('ipfoxy_host')}:{profile_data.get('ipfoxy_port')} "
                f"({(profile_data.get('ipfoxy_username') or '')[:5]}***)"
            )
        print(f"  Timezone: {profile_data['timezone']}")
        if li_at:
            print(f"  li_at cookie: set ✓")
        
        if not fingerprint_json:
            print(f"\n  Next: Clone your Chrome fingerprint:")
            print(f"    pbpaste | uv run python scripts/clone_fingerprint.py {profile_uuid}")
        
    except ValueError as e:
        print(f"\nError: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nDatabase error: {e}")
        print("\nMake sure PostgreSQL is running and migrations are applied:")
        print("  uv run alembic upgrade head")
        sys.exit(1)


if __name__ == "__main__":
    main()
