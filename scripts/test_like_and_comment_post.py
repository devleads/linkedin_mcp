#!/usr/bin/env python3
"""Test script for like_and_comment_post tool."""

import sys
import asyncio
from mcp_client import MCPClient


async def main():
    if len(sys.argv) < 4:
        print("Usage: python test_like_and_comment_post.py <profile_uuid> <post_url> <comment_text>")
        print("\nExample:")
        print('  python test_like_and_comment_post.py 239a345b-2b81-4cfb-ab90-0632982c823e https://www.linkedin.com/feed/update/urn:li:activity:123456789 "Great post!"')
        sys.exit(1)

    profile_id = sys.argv[1]
    post_url = sys.argv[2]
    comment_text = sys.argv[3]

    print(f"Running like+comment for profile: {profile_id}")
    print(f"  Post URL: {post_url}")
    print(f"  Comment: {comment_text}")
    print()

    client = MCPClient()

    try:
        print("Connecting to server...")
        await client.start()

        print("Running combined action...")
        result = await client.like_and_comment_post(profile_id, post_url, comment_text)

        print(f"\nResult status: {result.get('status')}")
        print(f"Page loaded once: {result.get('page_loaded_once')}")

        like_result = result.get("like_result", {})
        comment_result = result.get("comment_result", {})

        print(f"Like status: {like_result.get('status')}")
        if like_result:
            print(f"Like message: {like_result.get('message')}")

        print(f"Comment status: {comment_result.get('status')}")
        if comment_result:
            print(f"Comment message: {comment_result.get('message')}")

        if result.get("status") != "ok":
            print(f"Error: {result.get('message', 'Unknown error')}")

    finally:
        await client.stop()


if __name__ == "__main__":
    asyncio.run(main())
