#!/usr/bin/env python3
"""Test script for comment_post tool."""

import sys
import asyncio
from mcp_client import MCPClient


async def main():
    if len(sys.argv) < 4:
        print("Usage: python test_comment_post.py <profile_uuid> <post_url> <comment_text>")
        print("\nExample:")
        print('  python test_comment_post.py 239a345b-2b81-4cfb-ab90-0632982c823e https://www.linkedin.com/feed/update/urn:li:activity:123456789 "Great post!"')
        sys.exit(1)
    
    profile_id = sys.argv[1]
    post_url = sys.argv[2]
    comment_text = sys.argv[3]
    
    print(f"Commenting on post for profile: {profile_id}")
    print(f"  Post URL: {post_url}")
    print(f"  Comment: {comment_text}")
    print()
    
    client = MCPClient()
    
    try:
        print("Connecting to server...")
        await client.start()
        
        print("Posting comment...")
        result = await client.comment_post(profile_id, post_url, comment_text)
        
        print(f"\nResult status: {result.get('status')}")
        
        if result.get("status") == "ok":
            message = result.get("message", "")
            print(f"\n{message}")
            print(f"Comment: {result.get('comment_text', '')}")
        else:
            error = result.get("message", "Unknown error")
            print(f"Error: {error}")
    
    finally:
        await client.stop()


if __name__ == "__main__":
    asyncio.run(main())
