"""Run the opt-in Chrome consistency integration test."""

import os
import subprocess
import sys


def main() -> int:
    environment = os.environ.copy()
    environment["RUN_BROWSER_INTEGRATION"] = "1"
    return subprocess.call(
        [sys.executable, "-m", "pytest", "-q", "tests/browser/test_browser_consistency.py"],
        env=environment,
    )


if __name__ == "__main__":
    raise SystemExit(main())
