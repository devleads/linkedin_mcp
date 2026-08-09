#!/usr/bin/env python3
"""Test browser fingerprint and IP via proxy.

Opens browserleaks.com to show the browser's fingerprint and IP address.
This helps verify that the proxy and fingerprint spoofing are working correctly.

Usage:
    uv run python scripts/test_fingerprint.py <profile_id>

Example:
    uv run python scripts/test_fingerprint.py d52e8d51-0abe-4a43-8d96-5da195803235
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linkedin_mcp.db import get_db
from linkedin_mcp.db.repository import ProfileRepository
from linkedin_mcp.browser.session import SessionManager


async def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    profile_uuid = sys.argv[1]
    
    print(f"Testing fingerprint for profile: {profile_uuid}")
    
    # Verify profile exists
    with get_db() as db:
        profile_repo = ProfileRepository(db)
        profile = profile_repo.get_by_uuid(profile_uuid)
        if not profile:
            print(f"Error: Profile {profile_uuid} not found")
            sys.exit(1)
        print(f"  Country: {profile.country}")
        print(f"  Timezone: {profile.timezone}")
    
    session_manager = SessionManager()
    
    try:
        print("\nStarting browser session...")
        session = await session_manager.create_session(profile_uuid)
        browser = session.browser
        
        # Test sites for IP and fingerprint
        test_sites = [
            ("https://browserleaks.com/ip", "IP Address & Geolocation"),
            ("https://browserleaks.com/canvas", "Canvas Fingerprint"),
            ("https://browserleaks.com/webgl", "WebGL Fingerprint"),
        ]
        
        print("\n" + "=" * 50)
        print("Browser is open. Check the following sites:")
        print("=" * 50)
        
        for url, description in test_sites:
            print(f"\n→ {description}")
            print(f"  {url}")
        
        # Navigate to IP check first
        print(f"\nNavigating to IP check...")
        await browser.navigate("https://browserleaks.com/ip")
        await asyncio.sleep(2)
        
        print("\n" + "=" * 50)
        print("Browser will stay open for 60 seconds.")
        print("Navigate to other tabs to check fingerprint.")
        print("Press Ctrl+C to close earlier.")
        print("=" * 50)
        
        # Keep browser open for inspection
        try:
            await asyncio.sleep(60)
        except KeyboardInterrupt:
            print("\nClosing browser...")
        
    finally:
        print("\nClosing session...")
        await session_manager.close_session(profile_uuid)
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
