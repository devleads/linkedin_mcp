#!/usr/bin/env python3
"""Test getting LinkedIn company details via MCP.

This script retrieves LinkedIn company details through the MCP HTTP server.
Requires a profile with valid authentication.

Start the server first:
    uv run python -m linkedin_mcp.http_server

Usage:
    uv run python scripts/test_get_company.py <profile_id> <company_url>

Example:
    uv run python scripts/test_get_company.py my-profile https://www.linkedin.com/company/microsoft/
    uv run python scripts/test_get_company.py my-profile https://www.linkedin.com/company/google/
"""

import asyncio
import sys

from mcp_client import MCPClient


async def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    
    profile_id = sys.argv[1]
    company_url = sys.argv[2]
    
    print(f"Getting company details for: {company_url}")
    print(f"Using account: {profile_id}")
    
    client = MCPClient()
    
    try:
        print("\nConnecting to server...")
        await client.start()
        
        print("Fetching company details...")
        result = await client.get_company(
            profile_id=profile_id,
            company_url=company_url,
        )
        
        print(f"\nResult status: {result.get('status')}")
        
        if result.get("status") == "ok":
            data = result.get("data", {})
            print(f"\n--- Company Data ---")
            print(f"Name: {data.get('name', 'N/A')}")
            print(f"Tagline: {data.get('tagline', 'N/A')}")
            print(f"Website: {data.get('website', 'N/A')}")
            print(f"Industry: {data.get('industry', 'N/A')}")
            print(f"Company size: {data.get('company_size', 'N/A')}")
            print(f"Headquarters: {data.get('headquarters', data.get('location', 'N/A'))}")
            print(f"Founded: {data.get('founded', 'N/A')}")
            print(f"Specialties: {data.get('specialties', 'N/A')}")
            print(f"Followers: {data.get('followers', 'N/A')}")
            
            about = data.get("about", "")
            if about:
                if len(about) > 400:
                    about = about[:400] + "..."
                print(f"\nAbout:\n{about}")
            
            # Print any additional fields
            known_fields = {'name', 'tagline', 'website', 'industry', 'company_size', 
                          'headquarters', 'location', 'founded', 'specialties', 
                          'followers', 'about', 'logo_url', 'type', 'posts'}
            extra_fields = set(data.keys()) - known_fields
            if extra_fields:
                print(f"\nAdditional fields:")
                for field in extra_fields:
                    print(f"  {field}: {data.get(field, 'N/A')}")
            
            # Print latest posts
            posts = data.get("posts", [])
            if posts:
                print(f"\n--- Latest Posts ({len(posts)}) ---")
                for i, post in enumerate(posts, 1):
                    print(f"\n[Post {i}]")
                    if post.get("author"):
                        print(f"  Author: {post['author']}")
                    if post.get("timestamp"):
                        print(f"  Time: {post['timestamp']}")
                    if post.get("text"):
                        text = post['text']
                        if len(text) > 200:
                            text = text[:200] + "..."
                        print(f"  Text: {text}")
                    stats = []
                    if post.get("reactions"):
                        stats.append(f"{post['reactions']} reactions")
                    if post.get("comments"):
                        stats.append(f"{post['comments']} comments")
                    if post.get("reposts"):
                        stats.append(f"{post['reposts']} reposts")
                    if stats:
                        print(f"  Engagement: {', '.join(stats)}")
        else:
            print(f"Error: {result.get('message')}")
        
    finally:
        await client.stop()


if __name__ == "__main__":
    asyncio.run(main())
