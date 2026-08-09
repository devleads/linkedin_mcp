#!/usr/bin/env python3
"""Test script for open_manual_browser tool."""

import sys
import asyncio
from mcp_client import MCPClient


async def main():
    if len(sys.argv) < 2:
        print("Usage: python test_open_manual_browser.py <profile_uuid> [url]")
        print("\nExample:")
        print("  python test_open_manual_browser.py 239a345b-2b81-4cfb-ab90-0632982c823e")
        print("  python test_open_manual_browser.py 239a345b-2b81-4cfb-ab90-0632982c823e https://www.linkedin.com/feed/")
        sys.exit(1)

    profile_id = sys.argv[1]
    url = sys.argv[2] if len(sys.argv) > 2 else None

    print(f"Opening manual browser for profile: {profile_id}")
    if url:
        print(f"  URL: {url}")
    print()

    client = MCPClient()

    try:
        print("Connecting to server...")
        await client.start()

        print("Opening browser...")
        result = await client.open_manual_browser(profile_id, url=url)

        print(f"\nResult status: {result.get('status')}")
        if result.get("status") == "ok":
            print(result.get("message", ""))
            print(f"Persistent: {result.get('persistent')}")
            print(f"Current URL: {result.get('current_url')}")
            print("\nBrowser will remain open until you call close_session.")
            print("After manual login/actions, run: test_save_session_cookies.py")
        else:
            print(f"Error: {result.get('message', 'Unknown error')}")

    finally:
        await client.stop()


if __name__ == "__main__":
    asyncio.run(main())
