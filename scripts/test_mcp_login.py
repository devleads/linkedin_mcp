#!/usr/bin/env python3
"""Test LinkedIn login via MCP HTTP server.

This script calls the MCP `login` tool and uses credentials from the
profiles table by default (`linkedin_email`, `linkedin_password_encrypted`, `totp_secret`).
You can optionally override email/password and pass a manual 2FA code.

Start server first:
    uv run python -m linkedin_mcp.http_server

Usage:
    uv run python scripts/test_mcp_login.py <profile_id> [totp_code] [--email=<email>] [--password=<password>]

Examples:
    uv run python scripts/test_mcp_login.py b18a89c7-6443-4094-8e09-c0b9a67e5694
    uv run python scripts/test_mcp_login.py b18a89c7-6443-4094-8e09-c0b9a67e5694 123456
    uv run python scripts/test_mcp_login.py b18a89c7-6443-4094-8e09-c0b9a67e5694 --email=user@example.com --password=secret
"""

import asyncio
import sys

from mcp_client import MCPClient


def _parse_args(argv: list[str]) -> tuple[str, str | None, str | None, str | None]:
    if len(argv) < 2:
        print(__doc__)
        sys.exit(1)

    profile_id = argv[1]
    totp_code = None
    email = None
    password = None

    for arg in argv[2:]:
        if arg.startswith("--email="):
            email = arg.split("=", 1)[1]
        elif arg.startswith("--password="):
            password = arg.split("=", 1)[1]
        elif not arg.startswith("--") and totp_code is None:
            totp_code = arg

    return profile_id, totp_code, email, password


async def main() -> None:
    profile_id, totp_code, email, password = _parse_args(sys.argv)

    print(f"Logging in profile: {profile_id}")
    print(f"  Email override: {'yes' if email else 'no (use profiles table)'}")
    print(f"  Password override: {'yes' if password else 'no (use profiles table)'}")
    print(f"  TOTP code provided: {'yes' if totp_code else 'no (use profiles.totp_secret if needed)'}")

    client = MCPClient()

    try:
        print("\nConnecting to server...")
        await client.start()

        print("Calling login tool...")
        result = await client.login(
            profile_id=profile_id,
            email=email,
            password=password,
            totp_code=totp_code,
        )

        print(f"\nResult status: {result.get('status')}")
        if result.get("method"):
            print(f"Method: {result.get('method')}")
        if result.get("message"):
            print(f"Message: {result.get('message')}")

        if result.get("status") == "2fa_required":
            print("\n2FA is required and no valid code was supplied.")
            print("Set profiles.totp_secret or pass a code as positional arg.")

    finally:
        await client.stop()


if __name__ == "__main__":
    asyncio.run(main())
