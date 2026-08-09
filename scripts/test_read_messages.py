#!/usr/bin/env python3
"""Test reading LinkedIn messages via MCP.

This script reads LinkedIn messages/conversations through the MCP HTTP server.
Requires a profile with valid authentication.

Start the server first:
    uv run python -m linkedin_mcp.http_server

Usage:
    uv run python scripts/test_read_messages.py <profile_id> [max_conversations] [max_messages_per_conversation]

Example:
    uv run python scripts/test_read_messages.py my-profile
    uv run python scripts/test_read_messages.py my-profile 5
    uv run python scripts/test_read_messages.py my-profile 0  # random latest 6-14
    uv run python scripts/test_read_messages.py my-profile 12 30
"""

import asyncio
import sys

from mcp_client import MCPClient


async def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    profile_id = sys.argv[1]
    max_conversations = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    max_messages_per_conversation = int(sys.argv[3]) if len(sys.argv) > 3 else 20
    
    print(f"Reading messages for profile: {profile_id}")
    print(f"  Max conversations: {max_conversations} (0 = random latest 6-14)")
    print(f"  Max messages per conversation: {max_messages_per_conversation} (<=0 uses default)")
    
    client = MCPClient()
    
    try:
        print("\nConnecting to server...")
        await client.start()
        
        print("Reading messages...")
        result = await client.read_messages(
            profile_id=profile_id,
            max_conversations=max_conversations,
            max_messages_per_conversation=max_messages_per_conversation,
        )
        
        print(f"\nResult status: {result.get('status')}")
        
        if result.get("status") == "ok":
            version = result.get("read_messages_version")
            if version:
                print(f"Read messages version: {version}")
            conversations = result.get("conversations", [])
            applied_max = result.get("applied_max_conversations")
            if applied_max is not None:
                print(f"Applied max conversations: {applied_max}")
            applied_message_max = result.get("applied_max_messages_per_conversation")
            if applied_message_max is not None:
                print(f"Applied max messages per conversation: {applied_message_max}")
            print(f"Conversations found: {len(conversations)}")
            
            for i, conv in enumerate(conversations, 1):
                print(f"\n--- Conversation {i} ---")
                print(f"Participant: {conv.get('participant', 'Unknown')}")
                if conv.get("conversation_id"):
                    print(f"Conversation ID: {conv.get('conversation_id')}")
                if conv.get("participant_profile_id"):
                    print(f"Participant Profile ID: {conv.get('participant_profile_id')}")
                if conv.get("participant_profile_url"):
                    print(f"Participant Profile URL: {conv.get('participant_profile_url')}")
                print(f"Last message: {conv.get('last_message', 'N/A')}")
                print(f"Timestamp: {conv.get('timestamp', 'N/A')}")
                print(f"Unread: {conv.get('unread', False)}")
                diagnostics = conv.get("thread_extraction")
                if diagnostics:
                    print(f"Thread extraction: {diagnostics}")
                messages = conv.get("messages") or []
                if messages:
                    print(f"Messages ({len(messages)}):")
                    for msg in messages:
                        message_id = msg.get("message_id") or ""
                        sender = msg.get("sender") or "Unknown"
                        ts = msg.get("timestamp") or ""
                        text = msg.get("text") or ""
                        if ts:
                            if message_id:
                                print(f"  - ({message_id}) [{ts}] {sender}: {text}")
                            else:
                                print(f"  - [{ts}] {sender}: {text}")
                        else:
                            if message_id:
                                print(f"  - ({message_id}) {sender}: {text}")
                            else:
                                print(f"  - {sender}: {text}")
        else:
            print(f"Error: {result.get('message')}")
        
    finally:
        await client.stop()


if __name__ == "__main__":
    asyncio.run(main())
