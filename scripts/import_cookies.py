#!/usr/bin/env python3
"""Import LinkedIn cookies from a JSON file exported from browser.

Usage:
    1. In Chrome, install "EditThisCookie" extension or use DevTools
    2. Go to linkedin.com while logged in
    3. Export cookies as JSON (EditThisCookie: export button, or manually copy from DevTools)
    4. Save to a file (e.g., cookies.json)
    5. Run: uv run python scripts/import_cookies.py <profile_uuid> cookies.json

The JSON should be an array of cookie objects:
[
    {"name": "li_at", "value": "...", "domain": ".linkedin.com", ...},
    {"name": "JSESSIONID", "value": "...", "domain": ".www.linkedin.com", ...},
    ...
]
"""

import sys
import json
import asyncio

from linkedin_mcp.db import get_db
from linkedin_mcp.db.repository import ProfileRepository, CookieRepository


async def main():
    if len(sys.argv) < 3:
        print("Usage: uv run python scripts/import_cookies.py <profile_uuid> <cookies.json>")
        print("\nTo export cookies from Chrome:")
        print("  1. Open DevTools (F12) -> Application -> Cookies -> linkedin.com")
        print("  2. Right-click -> Copy all as JSON (or use EditThisCookie extension)")
        print("  3. Save to cookies.json")
        sys.exit(1)
    
    profile_uuid = sys.argv[1]
    cookies_file = sys.argv[2]
    
    # Load cookies from file
    try:
        with open(cookies_file, 'r') as f:
            cookies = json.load(f)
    except FileNotFoundError:
        print(f"Error: File not found: {cookies_file}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in {cookies_file}: {e}")
        sys.exit(1)
    
    if not isinstance(cookies, list):
        print("Error: Cookies file should contain a JSON array")
        sys.exit(1)
    
    print(f"Loaded {len(cookies)} cookies from {cookies_file}")
    
    # Get profile
    with get_db() as db:
        profile_repo = ProfileRepository(db)
        profile = profile_repo.get_by_uuid(profile_uuid)
        
        if not profile:
            print(f"Error: Profile {profile_uuid} not found")
            sys.exit(1)
        
        print(f"Found profile: {profile.linkedin_email}")
        
        # Filter LinkedIn cookies only
        linkedin_cookies = [c for c in cookies if "linkedin.com" in c.get("domain", "")]
        print(f"Found {len(linkedin_cookies)} LinkedIn cookies")
        
        if not linkedin_cookies:
            print("Error: No LinkedIn cookies found in the file. Existing cookies preserved.")
            sys.exit(1)
        
        # Import cookies
        cookie_repo = CookieRepository(db)
        
        # Import new cookies
        count = 0
        for cookie in linkedin_cookies:
            try:
                cookie_repo.set_cookie(
                    profile_id=profile.id,
                    name=cookie["name"],
                    value=cookie["value"],
                    domain=cookie.get("domain", ".linkedin.com"),
                    path=cookie.get("path", "/"),
                    secure=cookie.get("secure", True),
                    http_only=cookie.get("httpOnly", True),
                    same_site=cookie.get("sameSite", "None"),
                    expires=cookie.get("expirationDate") or cookie.get("expires"),
                )
                count += 1
                print(f"  + {cookie['name']}")
            except Exception as e:
                print(f"  ! Failed to import {cookie['name']}: {e}")
        
        print(f"\nImported {count} cookies for profile {profile_uuid[:8]}...")
        
        # Verify li_at is present
        li_at = cookie_repo.get_by_name(profile.id, "li_at")
        if li_at:
            print(f"✓ li_at cookie present (length={len(li_at.value)})")
        else:
            print("✗ WARNING: li_at cookie not found - authentication will fail!")
        
        jsessionid = cookie_repo.get_by_name(profile.id, "JSESSIONID")
        if jsessionid:
            print(f"✓ JSESSIONID cookie present")
        else:
            print("✗ WARNING: JSESSIONID cookie not found")


if __name__ == "__main__":
    asyncio.run(main())
