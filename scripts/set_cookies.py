#!/usr/bin/env python3
"""Set LinkedIn cookies for a profile.

This script sets the li_at cookie (and optionally JSESSIONID) for a profile
without starting a browser. Use this for purchased accounts.

Usage:
    uv run python scripts/set_cookies.py <profile_id> <li_at> [jsessionid]

Example:
    uv run python scripts/set_cookies.py my-profile "AQEDAQNxyz..."
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from mcp_client import MCPClient


async def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    
    profile_id = sys.argv[1]
    li_at = sys.argv[2]
    jsessionid = sys.argv[3] if len(sys.argv) > 3 else None
    
    print(f"Setting cookies for profile: {profile_id}")
    print(f"  li_at: {li_at[:20]}...")
    if jsessionid:
        print(f"  JSESSIONID: {jsessionid[:20]}...")
    
    client = MCPClient()
    
    try:
        await client.start()
        
        result = await client.set_cookies(
            profile_id=profile_id,
            li_at=li_at,
            jsessionid=jsessionid,
        )
        
        print(f"\nResult: {result}")
        
    finally:
        await client.stop()


if __name__ == "__main__":
    asyncio.run(main())
