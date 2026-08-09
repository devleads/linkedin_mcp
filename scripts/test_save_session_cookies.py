#!/usr/bin/env python3
"""Test script for save_session_cookies tool."""

import sys
import asyncio
from mcp_client import MCPClient


async def main():
    if len(sys.argv) < 2:
        print("Usage: python test_save_session_cookies.py <profile_uuid>")
        print("\nExample:")
        print("  python test_save_session_cookies.py 239a345b-2b81-4cfb-ab90-0632982c823e")
        sys.exit(1)

    profile_id = sys.argv[1]

    print(f"Saving session cookies for profile: {profile_id}")
    print()

    client = MCPClient()

    try:
        print("Connecting to server...")
        await client.start()

        print("Saving cookies...")
        result = await client.save_session_cookies(profile_id)

        print(f"\nResult status: {result.get('status')}")
        if result.get("status") == "ok":
            print(result.get("message", ""))
            print(f"Cookies saved: {result.get('cookies_saved')}")
        else:
            print(f"Error: {result.get('message', 'Unknown error')}")

    finally:
        await client.stop()


if __name__ == "__main__":
    asyncio.run(main())
