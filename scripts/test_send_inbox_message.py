#!/usr/bin/env python3
"""Test sending a LinkedIn inbox-thread message via MCP.

This script sends a message through LinkedIn messaging inbox flow (thread-based,
not profile-direct messaging).

Start the server first:
    uv run python -m linkedin_mcp.http_server

Usage:
    # Target by conversation id (preferred)
    uv run python scripts/test_send_inbox_message.py <profile_id> --conversation-id <conversation_id> --message "Hello!"

    # Target by participant profile URL (opens profile and uses compose flow)
    uv run python scripts/test_send_inbox_message.py <profile_id> --participant-profile-url https://www.linkedin.com/in/someone/ --message "Hello!"
"""

import argparse
import asyncio
import sys

from mcp_client import MCPClient


def _parse_bool(raw: str) -> bool:
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"Invalid boolean value: {raw}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Send message via LinkedIn inbox thread flow")
    parser.add_argument("profile_id", help="Profile UUID")
    parser.add_argument("--conversation-id", dest="conversation_id", help="LinkedIn inbox conversation id")
    parser.add_argument(
        "--participant-profile-url",
        dest="participant_profile_url",
        help="LinkedIn participant profile URL (profile compose route)",
    )
    parser.add_argument("--message", required=True, help="Message text to send")
    parser.add_argument(
        "--existing-thread-only",
        default="true",
        help="Legacy flag retained for compatibility (default: true)",
    )
    return parser


async def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not args.conversation_id and not args.participant_profile_url:
        parser.error("Provide either --conversation-id or --participant-profile-url")

    try:
        existing_thread_only = _parse_bool(args.existing_thread_only)
    except ValueError as exc:
        print(str(exc))
        sys.exit(1)

    print(f"Sending inbox message for profile: {args.profile_id}")
    if args.conversation_id:
        print(f"Conversation ID: {args.conversation_id}")
    if args.participant_profile_url:
        print(f"Participant Profile URL: {args.participant_profile_url}")
    print(f"Existing thread only: {existing_thread_only}")
    print(f"Message: {args.message}")

    client = MCPClient()

    try:
        print("\nConnecting to server...")
        await client.start()

        print("Sending inbox message...")
        result = await client.send_inbox_message(
            profile_id=args.profile_id,
            message=args.message,
            conversation_id=args.conversation_id,
            participant_profile_url=args.participant_profile_url,
            existing_thread_only=existing_thread_only,
        )

        print(f"\nResult status: {result.get('status')}")
        if result.get("status") == "ok":
            print("Inbox message sent successfully!")
            print(f"Conversation ID: {result.get('conversation_id')}")
            print(f"Participant Name: {result.get('participant_name')}")
            print(f"Participant Profile URL: {result.get('participant_profile_url')}")
            print(f"Participant Profile ID: {result.get('participant_profile_id')}")
            print(f"Message ID: {result.get('message_id')}")
            print(f"Message length: {result.get('message_length')} characters")
        else:
            print(f"Error: {result.get('message')}")
            if result.get("code"):
                print(f"Code: {result.get('code')}")

    finally:
        await client.stop()


if __name__ == "__main__":
    asyncio.run(main())
