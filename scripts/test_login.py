#!/usr/bin/env python3
"""Test LinkedIn login with username/password + OTP.

This script performs a full login using credentials from the profile database.
It uses email/password and TOTP secret (if set) to authenticate.
All cookies (including li_at) are saved to the database after successful login.

Usage:
    uv run python scripts/test_login.py <profile-uuid> [totp_code]

Example:
    uv run python scripts/test_login.py b18a89c7-6443-4094-8e09-c0b9a67e5694
    uv run python scripts/test_login.py b18a89c7-6443-4094-8e09-c0b9a67e5694 123456
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linkedin_mcp.db import get_db
from linkedin_mcp.db.repository import ProfileRepository, CookieRepository
from linkedin_mcp.browser.session import SessionManager
from linkedin_mcp.browser.human import HumanBehavior
from linkedin_mcp.security import decrypt_secret
import pyotp


async def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    profile_uuid = sys.argv[1]
    totp_code = sys.argv[2] if len(sys.argv) > 2 else None
    
    # Load profile from database
    with get_db() as db:
        profile_repo = ProfileRepository(db)
        profile = profile_repo.get_by_uuid(profile_uuid)
        
        if not profile:
            print(f"Error: Profile {profile_uuid} not found")
            sys.exit(1)
        
        print(f"Profile: {profile.uuid}")
        print(f"  Email: {profile.linkedin_email or '(not set)'}")
        print(f"  Password: {'***' if profile.linkedin_password_encrypted else '(not set)'}")
        print(f"  TOTP secret: {'set' if profile.totp_secret else '(not set)'}")
        print(f"  Country: {profile.country}")
        
        login_email = profile.linkedin_email
        login_password = decrypt_secret(profile.linkedin_password_encrypted)
        totp_secret = profile.totp_secret
        profile_db_id = profile.id
    
    if not login_email or not login_password:
        print("\nError: Email and password are required for login")
        print("Update the profile with credentials first.")
        sys.exit(1)
    
    session_manager = SessionManager()
    human = HumanBehavior()
    
    try:
        print("\n" + "=" * 50)
        print("Starting browser session...")
        print("=" * 50)
        
        session = await session_manager.create_session(profile_uuid)
        browser = session.browser
        
        # Navigate to login page
        print("\nNavigating to LinkedIn login...")
        await browser.navigate("https://www.linkedin.com/login")
        await human.page_load_delay()
        
        # Fill email
        print("Entering email...")
        if not await browser.type_text("#username", login_email):
            print("Error: Failed to enter email")
            sys.exit(1)
        
        await human.delay(500, 1000)
        
        # Fill password
        print("Entering password...")
        if not await browser.type_text("#password", login_password):
            print("Error: Failed to enter password")
            sys.exit(1)
        
        await human.delay(300, 700)
        
        # Click login button
        print("Clicking login button...")
        if not await browser.click("button[type='submit']"):
            print("Error: Failed to click login button")
            sys.exit(1)
        
        await human.page_load_delay()
        
        # Check for 2FA
        current_url = await browser.get_current_url()
        print(f"Current URL: {current_url}")
        
        if "checkpoint" in current_url or "two-step-verification" in current_url:
            print("\n2FA required...")
            
            # Get TOTP code
            code = totp_code
            if not code and totp_secret:
                print("Generating TOTP code from secret...")
                totp = pyotp.TOTP(totp_secret)
                code = totp.now()
                print(f"Generated code: {code}")
            
            if not code:
                print("Error: 2FA code required but not provided")
                print("Provide code as argument or set totp_secret in profile")
                sys.exit(1)
            
            await human.delay(1000, 2000)
            
            # Try different selectors for 2FA input
            selectors = [
                "input[name='pin']",
                "input#input__phone_verification_pin",
                "input.two-step-verification__input",
            ]
            
            entered = False
            for selector in selectors:
                if await browser.wait_for_selector(selector, timeout=3000):
                    print(f"Entering 2FA code in {selector}...")
                    if await browser.type_text(selector, code):
                        entered = True
                        break
            
            if not entered:
                print("Error: Failed to enter 2FA code")
                sys.exit(1)
            
            await human.delay(500, 1000)
            
            # Submit 2FA
            print("Submitting 2FA...")
            if not await browser.click("button[type='submit']"):
                print("Error: Failed to submit 2FA")
                sys.exit(1)
            
            await human.page_load_delay()
        
        # Check login success
        current_url = await browser.get_current_url()
        print(f"\nFinal URL: {current_url}")
        
        if "feed" in current_url or await browser.wait_for_selector("#global-nav", timeout=5000):
            print("\n✅ LOGIN SUCCESSFUL!")
            
            # Save ALL cookies to database
            print("\nSaving cookies to database...")
            browser_cookies = await browser.get_cookies(["https://www.linkedin.com"])
            
            with get_db() as db:
                cookie_repo = CookieRepository(db)
                count = cookie_repo.set_from_playwright(profile_db_id, browser_cookies)
                print(f"  Saved {count} cookies")
                
                # Show saved cookies
                saved_cookies = cookie_repo.get_for_profile(profile_db_id)
                print("\n  Saved cookies:")
                for c in saved_cookies:
                    value_preview = c.value[:30] + "..." if len(c.value) > 30 else c.value
                    print(f"    - {c.name}: {value_preview}")
                
                # Check for li_at specifically
                li_at = cookie_repo.get_li_at(profile_db_id)
                if li_at:
                    print(f"\n  ✅ li_at cookie saved ({len(li_at)} chars)")
                else:
                    print("\n  ⚠️  li_at cookie NOT found!")
        else:
            print("\n❌ LOGIN FAILED")
            title = await browser._page.title()
            print(f"  Page title: {title}")
        
        print("\n" + "=" * 50)
        print("Browser will stay open for 10 seconds...")
        print("=" * 50)
        
        await asyncio.sleep(10)
        
    finally:
        print("\nClosing session...")
        await session_manager.close_session(profile_uuid)
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
