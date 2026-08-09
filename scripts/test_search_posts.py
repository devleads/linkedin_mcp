#!/usr/bin/env python3
"""Test script for search_posts tool.

Search for LinkedIn posts by keywords using desktop browser.

Start the server first:
    uv run python -m linkedin_mcp.http_server

Usage:
    uv run python scripts/test_search_posts.py <profile-id> <keyword1> [keyword2] ... [--max N] [--scroll N]

Examples:
    uv run python scripts/test_search_posts.py my-profile ai marketing
    uv run python scripts/test_search_posts.py my-profile fintech --max 5
    uv run python scripts/test_search_posts.py my-profile startup entrepreneurship --max 10 --scroll 2
"""

import asyncio
import sys

from mcp_client import MCPClient


async def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    
    profile_id = sys.argv[1]
    
    # Parse arguments
    keywords = []
    max_posts = 10
    scroll_count = 15
    
    i = 2
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == "--max" and i + 1 < len(sys.argv):
            max_posts = int(sys.argv[i + 1])
            i += 2
        elif arg == "--scroll" and i + 1 < len(sys.argv):
            scroll_count = int(sys.argv[i + 1])
            i += 2
        else:
            keywords.append(arg)
            i += 1
    
    if not keywords:
        print("Error: At least one keyword is required")
        sys.exit(1)
    
    print(f"Searching posts for profile: {profile_id}")
    print(f"  Keywords: {keywords}")
    print(f"  Max posts: {max_posts}")
    print(f"  Scroll count: {scroll_count}")
    print()
    
    client = MCPClient()
    
    try:
        print("Connecting to server...")
        await client.start()
        
        print("Searching posts...")
        result = await client.search_posts(
            profile_id=profile_id,
            keywords=keywords,
            max_posts=max_posts,
            scroll_count=scroll_count,
        )
        
        print(f"\nResult status: {result.get('status')}")
        
        if result.get("status") == "ok":
            posts = result.get("posts", [])
            print(f"Posts found: {len(posts)}")
            
            for i, post in enumerate(posts, 1):
                matched = post.get('matched_keywords', [])
                print(f"\n--- Post {i} ---")
                author = post.get("author", {})
                print(f"Author: {author.get('name', 'Unknown')}")
                print(f"Headline: {author.get('headline', 'N/A')}")
                
                content = post.get("content", "")
                if content:
                    if len(content) > 200:
                        content = content[:200] + "..."
                    print(f"Content: {content}")
                
                engagement = post.get("engagement", {})
                print(f"Likes: {engagement.get('likes', 'N/A')}")
                print(f"Comments: {engagement.get('comments', 'N/A')}")
                print(f"Timestamp: {post.get('timestamp', 'N/A')}")
                print(f"URL: {post.get('url', 'N/A')}")
        else:
            print(f"Error: {result.get('message')}")
        
    finally:
        await client.stop()


if __name__ == "__main__":
    asyncio.run(main())
