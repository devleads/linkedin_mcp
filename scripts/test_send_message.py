#!/usr/bin/env python3
"""Test sending a direct message via MCP.

This script sends a direct message through the MCP HTTP server.
Requires a profile with valid authentication and an existing connection.

Start the server first:
    uv run python -m linkedin_mcp.http_server

Usage:
    uv run python scripts/test_send_message.py <profile_id> <recipient_url> <message>

Example:
    uv run python scripts/test_send_message.py my-profile https://www.linkedin.com/in/someone/ "Hello!"
"""

import asyncio
import sys

from mcp_client import MCPClient


async def main():
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)
    
    profile_id = sys.argv[1]
    recipient_url = sys.argv[2]
    message = sys.argv[3]
    
    print(f"Sending message to: {recipient_url}")
    print(f"Using account: {profile_id}")
    print(f"Message: {message}")
    
    client = MCPClient()
    
    try:
        print("\nConnecting to server...")
        await client.start()
        
        print("Sending message...")
        result = await client.send_message(
            profile_id=profile_id,
            recipient_url=recipient_url,
            message=message,
        )
        
        print(f"\nResult status: {result.get('status')}")
        
        if result.get("status") == "ok":
            print("Message sent successfully!")
            print(f"Message length: {result.get('message_length')} characters")
        else:
            print(f"Error: {result.get('message')}")
        
    finally:
        await client.stop()


if __name__ == "__main__":
    asyncio.run(main())
