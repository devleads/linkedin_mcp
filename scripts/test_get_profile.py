#!/usr/bin/env python3
"""Test getting a LinkedIn profile via MCP.

This script retrieves LinkedIn profile details through the MCP HTTP server.
Requires a profile with valid authentication.

Start the server first:
    uv run python -m linkedin_mcp.http_server

Usage:
    uv run python scripts/test_get_profile.py <profile_id> <linkedin_url> [--activity]

Example:
    uv run python scripts/test_get_profile.py my-profile https://www.linkedin.com/in/satyanadella/
    uv run python scripts/test_get_profile.py my-profile https://www.linkedin.com/in/satyanadella/ --activity
"""

import asyncio
import sys

from mcp_client import MCPClient


async def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    
    profile_id = sys.argv[1]
    linkedin_url = sys.argv[2]
    include_activity = "--activity" in sys.argv
    
    print(f"Getting profile for: {linkedin_url}")
    print(f"Using account: {profile_id}")
    if include_activity:
        print("Including recent activity (posts & comments)")
    
    client = MCPClient()
    
    try:
        print("\nConnecting to server...")
        await client.start()
        
        print("Fetching profile...")
        result = await client.get_profile(
            profile_id=profile_id,
            linkedin_url=linkedin_url,
            include_activity=include_activity,
            max_posts=5,
        )
        
        print(f"\nResult status: {result.get('status')}")
        
        if result.get("status") == "ok":
            data = result.get("data", {})
            print(f"\n--- Profile Data ---")
            print(f"Name: {data.get('name', 'N/A')}")
            print(f"Headline: {data.get('headline', 'N/A')}")
            print(f"Location: {data.get('location', 'N/A')}")
            print(f"Connections: {data.get('connections', 'N/A')}")
            print(f"Connection Status: {data.get('connection_status', 'N/A')}")
            print(f"Connection Degree: {data.get('connection_degree', 'N/A')}")
            print(f"Connection Status Evidence: {data.get('connection_status_evidence', 'N/A')}")
            
            if data.get('profile_picture'):
                print(f"Profile Picture: {data.get('profile_picture')[:80]}...")
            
            # About/Bio
            about = data.get("about", "")
            if about:
                print(f"\n--- About ---")
                print(about)
            
            # Experience
            experiences = data.get("experiences", [])
            if experiences:
                print(f"\n--- Experience ({len(experiences)}) ---")
                for i, exp in enumerate(experiences[:3], 1):
                    print(f"{i}. {exp.get('title', 'N/A')} at {exp.get('company', 'N/A')}")
                    if exp.get('duration'):
                        print(f"   {exp.get('duration')}")
            else:
                print(f"\nCurrent Role: {data.get('current_role', 'N/A')}")
                print(f"Current Company: {data.get('current_company', 'N/A')}")
            
            if data.get('company_linkedin_url'):
                print(f"Company LinkedIn: {data.get('company_linkedin_url')}")
            
            # Education
            education = data.get("education", [])
            if education:
                print(f"\n--- Education ({len(education)}) ---")
                for i, edu in enumerate(education[:3], 1):
                    print(f"{i}. {edu.get('school', 'N/A')}")
                    if edu.get('degree'):
                        print(f"   {edu.get('degree')}")
            
            # Skills
            skills = data.get("skills", [])
            if skills:
                print(f"\n--- Skills ({len(skills)}) ---")
                print(", ".join(skills[:10]))
            
            # Display recent posts
            recent_posts = data.get("recent_posts", [])
            if recent_posts:
                print(f"\n--- Recent Posts ({len(recent_posts)}) ---")
                for i, post in enumerate(recent_posts, 1):
                    content = post.get("content", "")
                    print(f"\n{i}. {post.get('timestamp', 'N/A')}")
                    print(f"   {content}")
                    print(f"   Likes: {post.get('likes', 'N/A')} | Comments: {post.get('comments', 'N/A')}")
                    if post.get("url"):
                        print(f"   URL: {post.get('url')}")
            
            # Display recent comments
            recent_comments = data.get("recent_comments", [])
            if recent_comments:
                print(f"\n--- Recent Comments ({len(recent_comments)}) ---")
                for i, comment in enumerate(recent_comments, 1):
                    content = comment.get("content", "")
                    print(f"\n{i}. {comment.get('timestamp', 'N/A')}")
                    if comment.get("original_author"):
                        print(f"   On post by: {comment.get('original_author')}")
                    print(f"   {content}")
        else:
            print(f"Error: {result.get('message')}")
        
    finally:
        await client.stop()


if __name__ == "__main__":
    asyncio.run(main())
