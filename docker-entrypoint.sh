#!/bin/sh
# Docker entrypoint — starts Xvfb (if enabled) then runs the MCP server.
#
# When USE_XVFB=1, starts a virtual X framebuffer display so Chrome
# runs in headful mode inside the container. This is required for
# LinkedIn bot detection avoidance — headless Chrome is easily detected.
#
# The DISPLAY env var is set to :99 and exported to the Python process.
# If Xvfb fails to start, startup fails rather than changing browser identity.

set -e

if [ "${USE_XVFB:-1}" = "1" ]; then
  echo "[entrypoint] Starting Xvfb on display :99 (1920x1080x24)..."
  Xvfb :99 -screen 0 1920x1080x24 -ac -nolisten tcp &
  XVFB_PID=$!
  export DISPLAY=:99

  # Give Xvfb a moment to initialize.
  sleep 1

  # Verify Xvfb is running.
  if ! kill -0 "$XVFB_PID" 2>/dev/null; then
    echo "[entrypoint] ERROR: Xvfb failed to start." >&2
    exit 1
  else
    echo "[entrypoint] Xvfb started (PID $XVFB_PID, DISPLAY=$DISPLAY)"
  fi
fi

# Execute the MCP HTTP server.
exec uv run python -m linkedin_mcp.http_server
