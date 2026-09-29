#!/usr/bin/env python3
"""Encrypt legacy plaintext cookies, TOTP, proxy secrets, and browser-state blobs.

The command is dry-run by default. Pass --apply after taking a database backup.
It never prints secret values.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linkedin_mcp.db import get_db
from linkedin_mcp.db.models import (
    Profile,
    ProfileBrowserState,
    ProfileCookie,
    ProfileProxyConfig,
)
from linkedin_mcp.security import ENVELOPE_PREFIX, encrypt_envelope


def needs_encryption(value: str | None) -> bool:
    return bool(value and not value.startswith(ENVELOPE_PREFIX))


def main() -> int:
    apply_changes = "--apply" in sys.argv[1:]
    counts = {"cookies": 0, "totp": 0, "proxy_passwords": 0, "browser_states": 0}
    with get_db() as db:
        for cookie in db.query(ProfileCookie).all():
            if needs_encryption(cookie.value):
                counts["cookies"] += 1
                if apply_changes:
                    cookie.value = encrypt_envelope(cookie.value)

        for profile in db.query(Profile).all():
            if needs_encryption(profile.totp_secret):
                counts["totp"] += 1
                if apply_changes:
                    profile.totp_secret = encrypt_envelope(profile.totp_secret)

        for proxy in db.query(ProfileProxyConfig).all():
            if needs_encryption(proxy.password):
                counts["proxy_passwords"] += 1
                if apply_changes:
                    proxy.password = encrypt_envelope(proxy.password)

        for state in db.query(ProfileBrowserState).all():
            if isinstance(state.storage_state, dict) and state.storage_state.get("format") != "fernet:v1":
                counts["browser_states"] += 1
                if apply_changes:
                    state.storage_state = {
                        "format": "fernet:v1",
                        "ciphertext": encrypt_envelope(
                            json.dumps(state.storage_state, separators=(",", ":"))
                        ),
                    }

        if not apply_changes:
            db.rollback()

    mode = "encrypted" if apply_changes else "would encrypt"
    print(f"{mode}: " + ", ".join(f"{name}={count}" for name, count in counts.items()))
    if not apply_changes:
        print("Dry run only. Re-run with --apply after taking a database backup.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
