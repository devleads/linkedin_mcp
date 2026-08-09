#!/usr/bin/env python3
"""Clone Chrome fingerprint to a LinkedIn profile.

This script updates an existing profile's fingerprint with JSON from Chrome DevTools.

Usage:
    1. Open Chrome DevTools (F12) on any page
    2. Paste and run: scripts/extract_fingerprint.js
    3. Copy the JSON output
    4. Run this script and paste the JSON

Example:
    uv run python scripts/clone_fingerprint.py <profile-uuid>
    
    # Pipe JSON directly:
    pbpaste | uv run python scripts/clone_fingerprint.py <profile-uuid>
"""

import sys
import json
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linkedin_mcp.db import get_db
from linkedin_mcp.db.repository import ProfileRepository


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    profile_uuid = sys.argv[1]
    
    print(f"Profile: {profile_uuid}")
    print("\nPaste fingerprint JSON (Ctrl+D when done):\n")
    
    # Read JSON from stdin
    try:
        json_input = sys.stdin.read().strip()
        if not json_input:
            print("Error: No JSON input")
            sys.exit(1)
        
        fingerprint_data = json.loads(json_input)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON - {e}")
        sys.exit(1)
    
    # Update fingerprint in database
    try:
        with get_db() as db:
            profile_repo = ProfileRepository(db)
            profile = profile_repo.get_by_uuid(profile_uuid)
            
            if not profile:
                print(f"Error: Profile {profile_uuid} not found")
                sys.exit(1)
            
            profile_repo.update_fingerprint(profile.id, fingerprint_data)
        
        print(f"\n✓ Fingerprint updated!")
        print(f"  Platform: {fingerprint_data.get('platform')}")
        print(f"  Screen: {fingerprint_data.get('screen_width')}x{fingerprint_data.get('screen_height')}")
        print(f"  WebGL: {fingerprint_data.get('webgl_renderer', '')[:50]}...")
        
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
