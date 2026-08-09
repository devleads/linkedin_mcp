#!/usr/bin/env python3
"""Test script for get_post tool."""

import sys
import asyncio
from mcp_client import MCPClient


async def main():
    if len(sys.argv) < 3:
        print("Usage: python test_get_post.py <profile_uuid> <post_url>")
        print("\nExample:")
        print("  python test_get_post.py 239a345b-2b81-4cfb-ab90-0632982c823e https://www.linkedin.com/feed/update/urn:li:activity:123456789")
        sys.exit(1)
    
    profile_id = sys.argv[1]
    post_url = sys.argv[2]
    
    print(f"Getting post for profile: {profile_id}")
    print(f"  Post URL: {post_url}")
    print()
    
    client = MCPClient()
    
    try:
        print("Connecting to server...")
        await client.start()
        
        print("Getting post...")
        result = await client.get_post(profile_id, post_url)
        
        print(f"\nResult status: {result.get('status')}")
        
        if result.get("status") == "ok":
            post = result.get("post", {})
            print("\n=== Post Details ===")
            
            # Author info (flat structure)
            author_name = post.get("author_name", "N/A")
            author_headline = post.get("author_headline", "N/A")
            print(f"\nAuthor: {author_name}")
            print(f"Headline: {author_headline}")
            
            content = post.get("content", "")
            if content:
                print(f"\nContent: {content[:200]}{'...' if len(content) > 200 else ''}")
            
            # Engagement (flat structure)
            likes = post.get("likes", "N/A")
            comments = post.get("comments", "N/A")
            print(f"\nLikes: {likes}")
            print(f"Comments: {comments}")
            
            # Display user interaction status
            is_liked = post.get("is_liked", False)
            has_commented = post.get("has_commented", False)
            user_comment_count = post.get("user_comment_count", 0)
            
            print(f"\n=== Your Interaction ===")
            print(f"You liked this: {is_liked}")
            print(f"You commented: {has_commented}")
            if has_commented:
                print(f"Your comments: {user_comment_count}")
                user_comments = post.get("user_comments", [])
                for i, comment in enumerate(user_comments, 1):
                    comment_text = comment.get("text", "")
                    print(f"  {i}. {comment_text[:100]}{'...' if len(comment_text) > 100 else ''}")
            
            timestamp = post.get("timestamp")
            if timestamp:
                print(f"\nPosted: {timestamp}")
            
            url = post.get("url")
            if url:
                print(f"URL: {url}")
        else:
            error = result.get("message", "Unknown error")
            print(f"Error: {error}")
    
    finally:
        await client.stop()


if __name__ == "__main__":
    asyncio.run(main())
