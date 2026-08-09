# LinkedIn MCP Server

This README is intentionally minimal and focused on run instructions only.

> Technical details moved to `README_TECHNICAL.md`.
>
> Use `README_TECHNICAL.md` for architecture, API details, schema, tools reference, and implementation notes.

## Prerequisites

- Python 3.11+
- `uv`
- PostgreSQL
- Proxy credentials (Oxylabs or IPFoxy)

## 1) Run Without Docker (local)

```bash
# 1. Install Python dependencies
uv sync

# 2. Install Chromium for Patchright
uv run patchright install chromium

# 3. Prepare environment variables
cp .env.example .env
# Edit .env and set DATABASE_URL + proxy settings

# 4. Run DB migrations
uv run alembic upgrade head

# 5. Create a profile (cookie-first recommended)
uv run python scripts/create_profile.py AE Asia/Dubai --li_at="AQEDAQNxyz..."

# 6. Start HTTP MCP server (for test scripts and HTTP clients)
#    Server runs on http://127.0.0.1:8765
uv run python -m linkedin_mcp.http_server

# 7. (Alternative) Start stdio MCP server (for Claude Desktop, Cursor, etc.)
#    This waits for JSON-RPC on stdin — it will appear to hang in a terminal.
#    Use this only when configured as an MCP server in your client app.
uv run linkedin-mcp
```

### Local profile examples

```bash
# Oxylabs with state targeting
uv run python scripts/create_profile.py US America/Los_Angeles --state=california --li_at="AQEDAQNxyz..."

# Oxylabs with city targeting
uv run python scripts/create_profile.py DE Europe/Berlin --city=munich --li_at="AQEDAQNxyz..."

# IPFoxy dedicated proxy per profile (requires PROXY_PROVIDER=ipfoxy)
uv run python scripts/create_profile.py US America/New_York \
  --ipfoxy-host=gw.ipfoxy.com \
  --ipfoxy-port=12345 \
  --ipfoxy-username=your_profile_user \
  --ipfoxy-password=your_profile_pass \
  --li_at="AQEDAQNxyz..."
```

## 2) Run With Docker

```bash
# 1. Prepare environment variables
cp .env.example .env
# Edit .env and set DATABASE_URL + proxy settings

# 2. Build and start services
docker compose up -d --build

# 3. Check server health
curl http://localhost:8765/health

# 4. Follow logs if needed
docker compose logs -f mcp-server

# 5. Stop services
docker compose down
```

Notes:
- `docker-compose.yml` runs migrations via a dedicated `migration` service before `mcp-server` starts.
- Browser state is persisted in Docker volume `browser_state`.

## 3) Common Commands

```bash
# -----------------------------------------------------------------------------
# Profile setup and auth scripts
# -----------------------------------------------------------------------------

# scripts/create_profile.py - create a profile (cookie-first recommended)
uv run python scripts/create_profile.py AE Asia/Dubai --li_at="AQEDAQNxyz..."

# scripts/set_cookies.py - update li_at for an existing profile
uv run python scripts/set_cookies.py <profile-uuid> "AQEDAQNxyz..."

# scripts/import_cookies.py - import cookies JSON (exported from browser)
uv run python scripts/import_cookies.py <profile-uuid> data/cookies.json

# scripts/clone_fingerprint.py - clone fingerprint to existing profile
pbpaste | uv run python scripts/clone_fingerprint.py <profile-uuid>

# scripts/extract_fingerprint.js - run in Chrome DevTools Console to copy fingerprint JSON
# 1) Open any page in Chrome
# 2) Open DevTools -> Console
# 3) Paste content of scripts/extract_fingerprint.js and run it

# -----------------------------------------------------------------------------
# Utility scripts (direct browser/session tests; no HTTP server required)
# -----------------------------------------------------------------------------

# scripts/test_fingerprint.py - verify proxy IP + fingerprint attributes
uv run python scripts/test_fingerprint.py <profile-uuid>

# scripts/test_login.py - direct login flow with optional OTP code
uv run python scripts/test_login.py <profile-uuid> [totp_code]

# scripts/test_linkedin_auth.py - validate LinkedIn auth/session state
uv run python scripts/test_linkedin_auth.py <profile-uuid>

# scripts/test_bot_detection.py - inspect bot-detection signals and feed behavior
uv run python scripts/test_bot_detection.py <profile-uuid>

# -----------------------------------------------------------------------------
# HTTP client script
# -----------------------------------------------------------------------------

# scripts/mcp_client.py - basic client connectivity + list tools test
# (requires HTTP server running at localhost:8765)
uv run python scripts/mcp_client.py

# -----------------------------------------------------------------------------
# MCP API test scripts (HTTP server must be running)
# -----------------------------------------------------------------------------

# Start server first (terminal 1)
uv run python -m linkedin_mcp.http_server

# scripts/test_mcp_login.py - login via MCP using stored credentials
uv run python scripts/test_mcp_login.py <profile-uuid>

# scripts/test_open_manual_browser.py - open pinned manual browser session
uv run python scripts/test_open_manual_browser.py <profile-uuid>

# scripts/test_save_session_cookies.py - save cookies from active manual session
uv run python scripts/test_save_session_cookies.py <profile-uuid>

# scripts/test_close_session.py - close active session and persist cookies
uv run python scripts/test_close_session.py <profile-uuid>

# scripts/test_read_feed.py - fetch feed items
uv run python scripts/test_read_feed.py <profile-uuid>

# scripts/test_read_messages.py - fetch inbox/conversations
uv run python scripts/test_read_messages.py <profile-uuid>

# scripts/test_get_profile.py - fetch profile by LinkedIn URL
uv run python scripts/test_get_profile.py <profile-uuid> https://linkedin.com/in/someone/

# scripts/test_get_company.py - fetch company by LinkedIn URL
uv run python scripts/test_get_company.py <profile-uuid> https://linkedin.com/company/microsoft/

# scripts/test_search_people.py - search people by keywords
uv run python scripts/test_search_people.py <profile-uuid> "Software Engineer" US

# scripts/test_search_posts.py - search posts by keywords
uv run python scripts/test_search_posts.py <profile-uuid> ai marketing

# scripts/test_get_post.py - fetch a specific post by URL
uv run python scripts/test_get_post.py <profile-uuid> https://linkedin.com/feed/update/urn:li:activity:123456789

# scripts/test_like_post.py - like a post
uv run python scripts/test_like_post.py <profile-uuid> https://linkedin.com/feed/update/urn:li:activity:123456789

# scripts/test_comment_post.py - comment on a post
uv run python scripts/test_comment_post.py <profile-uuid> https://linkedin.com/feed/update/urn:li:activity:123456789 "Great post!"

# scripts/test_like_and_comment_post.py - like and comment in one call
uv run python scripts/test_like_and_comment_post.py <profile-uuid> https://linkedin.com/feed/update/urn:li:activity:123456789 "Great post!"

# scripts/test_send_connection.py - send connection request with a note
uv run python scripts/test_send_connection.py <profile-uuid> https://linkedin.com/in/someone/ "Hi!"

# scripts/test_send_message.py - send direct message
uv run python scripts/test_send_message.py <profile-uuid> https://linkedin.com/in/someone/ "Hello!"

# scripts/test_send_inbox_message.py - send message by conversation thread or profile compose route
uv run python scripts/test_send_inbox_message.py <profile-uuid> --conversation-id <conversation-id> --message "Hello!"
uv run python scripts/test_send_inbox_message.py <profile-uuid> --participant-profile-url https://linkedin.com/in/someone/ --message "Hello!"

# scripts/test_create_post.py - create personal post with optional image
uv run python scripts/test_create_post.py <profile-uuid> masterlabs_post.txt cost_of_not_automating_follow_up.jpg

# scripts/test_create_company_post.py - create company page post
uv run python scripts/test_create_company_post.py <profile-uuid> https://linkedin.com/company/masterlabs-ai/ masterlabs_post.txt cost_of_not_automating_follow_up.jpg
```

## 4) Unit Tests

Unit tests use mocks and an in-memory SQLite database — no real browser, network, or PostgreSQL required.

```bash
# Run all tests
uv run pytest

# Run with verbose output
uv run pytest -v

# Run a specific test module
uv run pytest tests/test_proxy.py

# Run a specific test class
uv run pytest tests/test_proxy.py::TestApifyProxy

# Run with coverage summary (requires pytest-cov)
uv run pytest --cov=linkedin_mcp --cov-report=term-missing
```

### Test coverage

| Module | Tests | Description |
|--------|-------|-------------|
| `test_security.py` | 10 | Fernet encrypt/decrypt round-trip, edge cases, invalid keys |
| `test_config.py` | 8 | Settings loading from env, singleton, logging setup |
| `test_proxy.py` | 30 | Apify/Oxylabs/IPFoxy providers, session IDs, geo-targeting |
| `test_stealth.py` | 22 | Stealth launch args, init script generation, fingerprint patches |
| `test_navigation.py` | 8 | Navigation retry on transient network errors |
| `test_human.py` | 20 | Human-like typing, mouse movement, delays, Bezier paths |
| `test_models.py` | 25 | Profile/Fingerprint/CookieData/CookieStore serialization & persistence |
| `test_repository.py` | 31 | Profile/Cookie/ChallengeEvent/BrowserState CRUD with in-memory SQLite |
| `test_dispatcher.py` | 18 | Tool routing, auth recovery, fatal session error detection |
| `test_challenge_lock.py` | 10 | Challenge signal classification, lock response builder |

## Technical Documentation

- Full technical reference: `README_TECHNICAL.md`
