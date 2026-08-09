#!/usr/bin/env python3
"""Test script for like_post tool."""

import sys
import asyncio
from mcp_client import MCPClient


async def main():
    if len(sys.argv) < 3:
        print("Usage: python test_like_post.py <profile_uuid> <post_url>")
        print("\nExample:")
        print("  python test_like_post.py 239a345b-2b81-4cfb-ab90-0632982c823e https://www.linkedin.com/feed/update/urn:li:activity:123456789")
        sys.exit(1)
    
    profile_id = sys.argv[1]
    post_url = sys.argv[2]
    
    print(f"Liking post for profile: {profile_id}")
    print(f"  Post URL: {post_url}")
    print()
    
    client = MCPClient()
    
    try:
        print("Connecting to server...")
        await client.start()
        
        print("Liking post...")
        result = await client.like_post(profile_id, post_url)
        
        print(f"\nResult status: {result.get('status')}")
        
        if result.get("status") == "ok":
            message = result.get("message", "")
            already_liked = result.get("already_liked", False)
            
            print(f"\n{message}")
            if already_liked:
                print("(Post was already liked)")
        else:
            error = result.get("message", "Unknown error")
            print(f"Error: {error}")
    
    finally:
        await client.stop()


if __name__ == "__main__":
    asyncio.run(main())
