#!/usr/bin/env python3
"""Encrypt a LinkedIn password for profiles.linkedin_password_encrypted.

Examples:
    uv run python scripts/encrypt_linkedin_password.py 'plain-password-here'
    LINKEDIN_CREDENTIAL_ENCRYPTION_KEY='your-fernet-key' uv run python scripts/encrypt_linkedin_password.py 'plain-password-here'

Generate a key if needed:
    uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linkedin_mcp.security import encrypt_secret


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Encrypt a LinkedIn password for profiles.linkedin_password_encrypted."
    )
    parser.add_argument("password", help="Plaintext LinkedIn password to encrypt")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    encrypted = encrypt_secret(args.password)
    if not encrypted:
        raise SystemExit("Password must not be empty")
    print(encrypted)


if __name__ == "__main__":
    main()
