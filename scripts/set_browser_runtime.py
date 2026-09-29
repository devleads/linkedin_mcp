#!/usr/bin/env python3
"""Select the browser runtime for one LinkedIn profile."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linkedin_mcp.db import get_db
from linkedin_mcp.db.repository import BrowserRuntimeRepository, ProfileRepository


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("profile_id")
    parser.add_argument("runtime", choices=["legacy_injected", "persistent_native"])
    args = parser.parse_args()
    with get_db() as db:
        profile = ProfileRepository(db).get_by_uuid(args.profile_id)
        if not profile:
            parser.error(f"Profile {args.profile_id} was not found")
        existing = BrowserRuntimeRepository(db).get(profile.id)
        migration_status = (
            existing.migration_status
            if existing and existing.runtime_type == args.runtime
            else "pending"
        )
        BrowserRuntimeRepository(db).upsert(
            profile.id,
            args.runtime,
            migration_status,
        )
    print(f"profile {args.profile_id}: runtime={args.runtime}, migration_status={migration_status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
