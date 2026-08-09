#!/usr/bin/env python3
"""Test script for close_session tool."""

import sys
import asyncio
from mcp_client import MCPClient


async def main():
    if len(sys.argv) < 2:
        print("Usage: python test_close_session.py <profile_uuid>")
        print("\nExample:")
        print("  python test_close_session.py 239a345b-2b81-4cfb-ab90-0632982c823e")
        sys.exit(1)

    profile_id = sys.argv[1]

    print(f"Closing browser session for profile: {profile_id}")
    print()

    client = MCPClient()

    try:
        print("Connecting to server...")
        await client.start()

        print("Closing session...")
        result = await client.close_session(profile_id)

        print(f"\nResult status: {result.get('status')}")
        if result.get("status") in {"closed", "ok"}:
            print("Session closed and cookies saved.")
        else:
            print(f"Message: {result.get('message', 'No message')}")

    finally:
        await client.stop()


if __name__ == "__main__":
    asyncio.run(main())
