#!/usr/bin/env python3
"""Test searching for people on LinkedIn via MCP.

This script searches for people on LinkedIn through the MCP HTTP server.
Requires a profile with valid authentication.

Start the server first:
    uv run python -m linkedin_mcp.http_server

Usage:
    uv run python scripts/test_search_people.py <profile_id> <keywords> [country] [page]

Example:
    uv run python scripts/test_search_people.py my-profile "Software Engineer"
    uv run python scripts/test_search_people.py my-profile "CEO" US 1
"""

import asyncio
import sys

from mcp_client import MCPClient


async def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    
    profile_id = sys.argv[1]
    keywords = sys.argv[2]
    country = sys.argv[3] if len(sys.argv) > 3 else None
    page = int(sys.argv[4]) if len(sys.argv) > 4 else 1
    
    print(f"Searching for: {keywords}")
    print(f"Using account: {profile_id}")
    if country:
        print(f"Country filter: {country}")
    print(f"Page: {page}")
    
    client = MCPClient()
    
    try:
        print("\nConnecting to server...")
        await client.start()
        
        print("Searching...")
        result = await client.search_people(
            profile_id=profile_id,
            keywords=keywords,
            country=country,
            connection_degree=["2", "3"],  # 2nd and 3rd connections
            page=page,
            max_results=10,
        )
        
        print(f"\nResult status: {result.get('status')}")
        
        if result.get("status") == "ok":
            results = result.get("results", [])
            print(f"Results found: {len(results)}")
            
            for i, person in enumerate(results, 1):
                print(f"\n--- Result {i} ---")
                print(f"Name: {person.get('name', 'N/A')}")
                print(f"Headline: {person.get('headline', 'N/A')}")
                print(f"Location: {person.get('location', 'N/A')}")
                print(f"Connection: {person.get('connection_degree', 'N/A')}")
                print(f"URL: {person.get('url', 'N/A')}")
        else:
            print(f"Error: {result.get('message')}")
        
    finally:
        await client.stop()


if __name__ == "__main__":
    asyncio.run(main())
