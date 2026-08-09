#!/usr/bin/env python3
"""Test LinkedIn authentication with detailed debugging.

Opens LinkedIn and shows what happens with the cookies.

Usage:
    uv run python scripts/test_linkedin_auth.py <profile-uuid>
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linkedin_mcp.db import get_db
from linkedin_mcp.db.repository import ProfileRepository, CookieRepository
from linkedin_mcp.browser.session import SessionManager


async def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    profile_uuid = sys.argv[1]
    
    print(f"Testing LinkedIn auth for profile: {profile_uuid}")
    
    # Check cookies in DB
    with get_db() as db:
        profile_repo = ProfileRepository(db)
        cookie_repo = CookieRepository(db)
        
        profile = profile_repo.get_by_uuid(profile_uuid)
        if not profile:
            print(f"Error: Profile {profile_uuid} not found")
            sys.exit(1)
        
        print(f"\nProfile: {profile.uuid}")
        print(f"Country: {profile.country}")
        
        cookies = cookie_repo.get_for_profile(profile.id)
        print(f"\nCookies in DB: {len(cookies)}")
        for c in cookies:
            print(f"  - {c.name}: {c.value[:40]}...")
            print(f"    domain={c.domain}, secure={c.secure}, httpOnly={c.http_only}")
    
    session_manager = SessionManager()
    
    try:
        print("\n" + "=" * 50)
        print("Starting browser session...")
        print("=" * 50)
        
        session = await session_manager.create_session(profile_uuid)
        browser = session.browser
        
        # Check cookies in browser before navigation
        print("\nCookies in browser context:")
        browser_cookies = await browser._context.cookies()
        for c in browser_cookies:
            if "linkedin" in c.get("domain", ""):
                print(f"  - {c['name']}: {c['value'][:40]}...")
        
        if not browser_cookies:
            print("  (no cookies)")
        
        # Navigate to LinkedIn homepage first (not feed)
        print("\n" + "=" * 50)
        print("Navigating to linkedin.com...")
        print("=" * 50)
        
        try:
            result = await browser.navigate("https://www.linkedin.com/", wait_until="domcontentloaded")
            print(f"URL after navigation: {result['url']}")
            print(f"Status: {result['status']}")
        except Exception as e:
            print(f"Navigation error: {e}")
        
        # Check current URL
        current_url = browser._page.url
        print(f"\nCurrent URL: {current_url}")
        
        # Get page title
        title = await browser._page.title()
        print(f"Page title: {title}")
        
        # Check if we're logged in
        if "/login" in current_url or "/checkpoint" in current_url:
            print("\n⚠️  NOT LOGGED IN - redirected to login/checkpoint")
            print("The li_at cookie may be invalid or expired.")
        elif "/feed" in current_url:
            print("\n✅ LOGGED IN - redirected to feed")
        else:
            print(f"\n? Unknown state - URL: {current_url}")
        
        # Check cookies after navigation
        print("\nCookies after navigation:")
        browser_cookies = await browser._context.cookies()
        linkedin_cookies = [c for c in browser_cookies if "linkedin" in c.get("domain", "")]
        print(f"  Total LinkedIn cookies: {len(linkedin_cookies)}")
        for c in linkedin_cookies[:5]:  # Show first 5
            print(f"  - {c['name']}: {c['value'][:30]}...")
        
        print("\n" + "=" * 50)
        print("Browser will stay open for 30 seconds.")
        print("Check the browser window to see the state.")
        print("Press Ctrl+C to close earlier.")
        print("=" * 50)
        
        try:
            await asyncio.sleep(30)
        except KeyboardInterrupt:
            print("\nClosing...")
        
    finally:
        print("\nClosing session...")
        await session_manager.close_session(profile_uuid)
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
