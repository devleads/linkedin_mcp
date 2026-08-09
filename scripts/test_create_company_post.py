#!/usr/bin/env python3
"""Test script for create_company_post tool.

Usage:
    # Post with content and image from data/ folder
    python test_create_company_post.py <profile_uuid> <company_url> <content_file> <image_file>
    
    # Post without image
    python test_create_company_post.py <profile_uuid> <company_url> <content_file> --no-image

Example:
    python test_create_company_post.py 239a345b-... https://linkedin.com/company/masterlabs-ai/ masterlabs_post.txt cost_of_not_automating_follow_up.jpg
"""

import sys
import asyncio
import argparse
from pathlib import Path
from mcp_client import MCPClient


# Data directory relative to project root
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"


async def main():
    parser = argparse.ArgumentParser(description="Create a company post on LinkedIn")
    parser.add_argument("profile_id", help="Profile UUID")
    parser.add_argument("company_url", help="LinkedIn company page URL")
    parser.add_argument("content_file", help="Content file name in data/ folder (e.g., masterlabs_post.txt)")
    parser.add_argument("image_file", nargs="?", help="Image file name in data/ folder (e.g., cost_of_not_automating_follow_up.jpg)")
    parser.add_argument("--no-image", action="store_true", help="Post without image")
    
    args = parser.parse_args()
    
    profile_id = args.profile_id
    company_url = args.company_url
    
    # Get content from data/ folder
    content_path = DATA_DIR / args.content_file
    if not content_path.exists():
        print(f"Error: Content file not found: {content_path}")
        print(f"Make sure the file exists in: {DATA_DIR}")
        sys.exit(1)
    content = content_path.read_text().strip()
    
    # Get image path from data/ folder
    image_path = None
    if not args.no_image and args.image_file:
        image_file_path = DATA_DIR / args.image_file
        if image_file_path.exists():
            image_path = str(image_file_path.absolute())
        else:
            print(f"Warning: Image file not found: {image_file_path}")
            print("Posting without image...")
    
    print(f"Creating company post")
    print(f"  Profile: {profile_id}")
    print(f"  Company: {company_url}")
    print(f"  Content length: {len(content)} chars")
    print(f"  Image: {image_path or 'None'}")
    print()
    print("--- Content Preview ---")
    preview = content[:300] + "..." if len(content) > 300 else content
    print(preview)
    print()
    
    client = MCPClient()
    
    try:
        print("Connecting to server...")
        await client.start()
        
        print("Creating post...")
        result = await client.create_company_post(
            profile_id=profile_id,
            company_url=company_url,
            content=content,
            image_path=image_path,
        )
        
        print(f"\nResult status: {result.get('status')}")
        
        if result.get("status") == "ok":
            print(f"\n✓ {result.get('message', 'Post created')}")
            print(f"  Has image: {result.get('has_image', False)}")
        else:
            error = result.get("message", "Unknown error")
            print(f"\n✗ Error: {error}")
    
    finally:
        await client.stop()


if __name__ == "__main__":
    asyncio.run(main())
