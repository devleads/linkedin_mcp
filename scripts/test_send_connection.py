#!/usr/bin/env python3
"""Test sending a connection request via MCP.

This script sends a connection request through the MCP HTTP server.
Requires a profile with valid authentication.

Start the server first:
    uv run python -m linkedin_mcp.http_server

Usage:
    uv run python scripts/test_send_connection.py <profile_id> <recipient_url> <note>

Example:
    uv run python scripts/test_send_connection.py my-profile https://www.linkedin.com/in/someone/ "Hi, I'd like to connect!"

Note: The connection note/cover letter is REQUIRED (max 300 characters).
"""

import asyncio
import sys

from mcp_client import MCPClient


async def main():
    if len(sys.argv) < 4:
        print(__doc__)
        print("Error: Note is required!")
        sys.exit(1)
    
    profile_id = sys.argv[1]
    recipient_url = sys.argv[2]
    note = sys.argv[3]
    
    if len(note) > 300:
        print(f"Error: Note must be 300 characters or less (currently {len(note)})")
        sys.exit(1)
    
    print(f"Sending connection request to: {recipient_url}")
    print(f"Using account: {profile_id}")
    print(f"Note: {note}")
    
    client = MCPClient()
    
    try:
        print("\nConnecting to server...")
        await client.start()
        
        print("Sending connection request...")
        result = await client.send_connection_request(
            profile_id=profile_id,
            recipient_url=recipient_url,
            note=note,
        )
        
        print(f"\nResult status: {result.get('status')}")
        
        if result.get("status") == "ok":
            print("Connection request sent successfully!")
            print(f"Note included: {result.get('note_included', False)}")
        elif result.get("status") == "already_connected":
            print("Already connected with this user.")
        elif result.get("status") == "already_pending":
            print("Connection request already pending.")
        else:
            print(f"Error: {result.get('message')}")
        
    finally:
        await client.stop()


if __name__ == "__main__":
    asyncio.run(main())
