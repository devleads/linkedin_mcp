#!/usr/bin/env python3
"""Test bot detection by checking various detection vectors.

This script navigates to bot detection test sites and LinkedIn
to help diagnose what's triggering detection.

Usage:
    uv run python scripts/test_bot_detection.py <profile_id>
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linkedin_mcp.db import get_db
from linkedin_mcp.db.repository import ProfileRepository
from linkedin_mcp.browser.session import SessionManager


async def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    profile_uuid = sys.argv[1]
    
    print(f"Testing bot detection for profile: {profile_uuid}")
    
    with get_db() as db:
        profile_repo = ProfileRepository(db)
        profile = profile_repo.get_by_uuid(profile_uuid)
        if not profile:
            print(f"Error: Profile {profile_uuid} not found")
            sys.exit(1)
        print(f"  Country: {profile.country}")
        print(f"  Timezone: {profile.timezone}")
        if profile.fingerprint:
            print(f"  Fingerprint: platform={profile.fingerprint.platform}, ua={profile.fingerprint.user_agent[:50]}...")
    
    session_manager = SessionManager()
    
    try:
        print("\nStarting browser session...")
        session = await session_manager.create_session(profile_uuid)
        browser = session.browser
        
        # Test 1: Check bot detection sites
        print("\n" + "=" * 60)
        print("TEST 1: Bot Detection Sites")
        print("=" * 60)
        
        # Navigate to bot detection test
        print("\nNavigating to bot.sannysoft.com...")
        await browser.navigate("https://bot.sannysoft.com/")
        await asyncio.sleep(3)
        
        # Check results
        results = await browser.evaluate("""
            () => {
                const rows = document.querySelectorAll('table tr');
                const results = {};
                for (const row of rows) {
                    const cells = row.querySelectorAll('td');
                    if (cells.length >= 2) {
                        const test = cells[0].textContent.trim();
                        const result = cells[1].textContent.trim();
                        const passed = cells[1].classList.contains('passed') || 
                                       result.toLowerCase().includes('passed') ||
                                       !cells[1].classList.contains('failed');
                        results[test] = { result, passed };
                    }
                }
                return results;
            }
        """)
        
        print("\nBot Detection Results:")
        failed_tests = []
        for test, data in results.items():
            status = "✓" if data['passed'] else "✗"
            print(f"  {status} {test}: {data['result']}")
            if not data['passed']:
                failed_tests.append(test)
        
        if failed_tests:
            print(f"\n⚠️  FAILED TESTS: {', '.join(failed_tests)}")
        else:
            print("\n✓ All bot detection tests passed!")
        
        # Test 2: Check creepjs (more advanced)
        print("\n" + "=" * 60)
        print("TEST 2: CreepJS (Advanced Detection)")
        print("=" * 60)
        
        print("\nNavigating to creepjs-api.web.app...")
        await browser.navigate("https://abrahamjuliot.github.io/creepjs/")
        await asyncio.sleep(5)
        
        # Get trust score
        trust_score = await browser.evaluate("""
            () => {
                const scoreEl = document.querySelector('.score-container .score');
                return scoreEl ? scoreEl.textContent : 'Not found';
            }
        """)
        print(f"\nCreepJS Trust Score: {trust_score}")
        
        # Test 3: Check LinkedIn
        print("\n" + "=" * 60)
        print("TEST 3: LinkedIn Feed")
        print("=" * 60)
        
        print("\nNavigating to LinkedIn feed...")
        await browser.navigate("https://www.linkedin.com/feed/")
        await asyncio.sleep(5)
        
        current_url = await browser.get_current_url()
        print(f"Current URL: {current_url}")
        
        if "login" in current_url or "authwall" in current_url:
            print("⚠️  Redirected to login - cookies may be invalid")
        elif "checkpoint" in current_url or "challenge" in current_url:
            print("⚠️  Security challenge detected!")
        else:
            print("✓ Successfully loaded feed")
            
            # Check for any error messages
            error_check = await browser.evaluate("""
                () => {
                    const body = document.body.innerText.toLowerCase();
                    return {
                        hasError: body.includes('something went wrong') || 
                                  body.includes('error') ||
                                  body.includes('unusual activity'),
                        hasFeed: document.querySelector('.feed-shared-update-v2') !== null ||
                                 document.querySelector('[data-urn]') !== null
                    };
                }
            """)
            
            if error_check['hasError']:
                print("⚠️  Error message detected on page")
            if error_check['hasFeed']:
                print("✓ Feed content loaded successfully")
            else:
                print("⚠️  No feed content found")
        
        print("\n" + "=" * 60)
        print("Browser will stay open for 120 seconds for manual inspection.")
        print("Check the browser window for any issues.")
        print("Press Ctrl+C to close earlier.")
        print("=" * 60)
        
        try:
            await asyncio.sleep(120)
        except KeyboardInterrupt:
            print("\nClosing browser...")
        
    finally:
        print("\nClosing session...")
        await session_manager.close_session(profile_uuid)
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
