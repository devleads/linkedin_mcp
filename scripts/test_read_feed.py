#!/usr/bin/env python3
"""Test reading LinkedIn feed via MCP.

This script reads the LinkedIn feed through the MCP HTTP server.
Requires a profile with valid authentication (cookies or credentials).

Start the server first:
    uv run python -m linkedin_mcp.http_server

Usage:
    uv run python scripts/test_read_feed.py <profile_id> [max_posts] [scroll_count]

Example:
    uv run python scripts/test_read_feed.py my-profile
    uv run python scripts/test_read_feed.py my-profile 5 2
"""

import asyncio
import random
import sys

from mcp_client import MCPClient


async def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    profile_id = sys.argv[1]
    max_posts = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    scroll_count = int(sys.argv[3]) if len(sys.argv) > 3 else random.randint(8, 15)
    
    print(f"Reading feed for profile: {profile_id}")
    print(f"  Max posts: {max_posts}")
    print(f"  Scroll count: {scroll_count}")
    
    client = MCPClient()
    
    try:
        print("\nConnecting to server...")
        await client.start()
        
        print("Reading feed...")
        result = await client.read_feed(
            profile_id=profile_id,
            max_posts=max_posts,
            scroll_count=scroll_count,
        )
        
        print(f"\nResult status: {result.get('status')}")
        
        if result.get("status") == "ok":
            posts = result.get("posts", [])
            print(f"Posts found: {len(posts)}")
            
            for i, post in enumerate(posts, 1):
                print(f"\n--- Post {i} ---")
                author = post.get("author", {})
                print(f"Author: {author.get('name', 'Unknown')}")
                print(f"Headline: {author.get('headline', 'N/A')}")
                
                content = post.get("content", "")
                if content:
                    print(f"Content: {content}")
                
                engagement = post.get("engagement", {})
                print(f"Likes: {engagement.get('likes', 'N/A')}")
                print(f"Comments: {engagement.get('comments', 'N/A')}")
                print(f"Timestamp: {post.get('timestamp', 'N/A')}")
                print(f"URL: {post.get('url', 'N/A')}")
                print(f"Post URL: {post.get('post_url', 'N/A')}")
                print(f"Profile URL: {post.get('profile_url', 'N/A')}")
                print(f"Company URL: {post.get('company_url', 'N/A')}")
        else:
            print(f"Error: {result.get('message')}")
        
    finally:
        await client.stop()


if __name__ == "__main__":
    asyncio.run(main())
