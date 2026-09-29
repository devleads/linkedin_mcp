# LinkedIn MCP Server — Technical Reference

This document contains technical/reference material moved out of `README.md`.
For setup and run instructions, use `README.md`.

## Features

- MCP protocol server for AI agents
- HTTP REST interface (`/health`, `/tools`, `/call`)
- Stealth browser automation via Patchright
- Multi-profile execution with persisted cookies/fingerprint
- Proxy-provider architecture (`oxylabs` / `ipfoxy`)
- TOTP support for 2FA login flows

## Architecture

```
Remote Client / MCP Client
        |
   HTTP or stdio
        |
 LinkedIn MCP Server
        |
  Tool Dispatcher
        |
  Session Manager
        |
 Patchright Browser
        |
 Proxy Provider (Oxylabs/IPFoxy)
        |
 PostgreSQL (profiles/cookies/fingerprints/proxy-configs)
```

## HTTP API

### Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Health check |
| `/mcp` | POST | Standard MCP Streamable HTTP transport for AI agents |
| `/tools` | GET | List tools |
| `/call` | POST | Execute MCP tool |

### Example call

```bash
curl -X POST http://localhost:8765/call \
  -H "Content-Type: application/json" \
  -d '{
    "tool": "read_feed",
    "arguments": {
      "profile_id": "<profile-uuid>",
      "max_posts": 5
    }
  }'
```

## Core MCP Tools

- `set_cookies`
- `login`
- `get_session_status`
- `open_manual_browser`
- `save_session_cookies`
- `close_session`
- `read_feed`
- `get_profile`
- `get_company`
- `search_people`
- `search_posts`
- `get_post`
- `like_post`
- `comment_post`
- `like_and_comment_post`
- `read_messages`
- `send_message`
- `send_inbox_message`
- `send_connection_request`
- `create_post`
- `create_company_post`

## Configuration

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | PostgreSQL URL | `postgresql://linkedin:linkedin@localhost:5432/linkedin` |
| `PROXY_PROVIDER` | Proxy backend for profiles with a country (`oxylabs`, `ipfoxy`, or `apify`) | `oxylabs` |
| `OXYLABS_USERNAME` | Required when `PROXY_PROVIDER=oxylabs` | - |
| `OXYLABS_PASSWORD` | Required when `PROXY_PROVIDER=oxylabs` | - |
| `OXYLABS_PROXY_TYPE` | `mobile` or `residentials` | `mobile` |
| `OXYLABS_RESIDENTIAL_HOST` | Oxylabs residential host | `pr.oxylabs.io` |
| `HEADLESS` | Browser headless mode | `false` |
| `BROWSER_PROFILE_ROOT` | Persistent browser state root | `./data/browser_state` |
| `MCP_HOST` | Bind host for HTTP server | `0.0.0.0` |
| `MCP_PORT` | Bind port for HTTP server | `8765` |
| `MCP_API_KEY` | Bearer or X-API-Key credential required for non-loopback HTTP binding | - |

## Database Schema (High Level)

```
profiles
├── id, uuid, linkedin_email, linkedin_password_encrypted
├── country, state, city, proxy_port
├── timezone, totp_secret, is_active
└── created_at, updated_at

profile_fingerprints
├── id, profile_id
├── fingerprint_data (JSON)
└── created_at, updated_at

profile_proxy_configs
├── id, profile_id, provider
├── host, port, username, password
├── config (JSON), is_active
└── created_at, updated_at

profile_cookies
├── id, profile_id
├── name, value, domain, path
├── secure, http_only, same_site, expires
└── created_at, updated_at
```

## Fingerprint and Cookie Notes

### Fingerprint cloning

- Extract fingerprint JSON from Chrome DevTools (`scripts/extract_fingerprint.js`)
- Pipe into `scripts/create_profile.py` or `scripts/clone_fingerprint.py`

### Cookie-first auth (purchased accounts)

- Prefer importing real LinkedIn cookie sets
- `li_at` alone is often insufficient
- Keep essential cookies together (e.g., `li_at`, `JSESSIONID`, `bcookie`, `bscookie`)

## Anti-detection Principles

- Non-headless browser sessions
- Stable per-profile fingerprint
- Geo/timezone consistency with proxy
- Human-like delays and interactions

## Project Structure

```
linkedin-mcp/
├── src/linkedin_mcp/
│   ├── browser/
│   ├── db/
│   ├── models/
│   ├── proxy/
│   ├── tools/
│   └── server modules
├── alembic/
├── scripts/
├── data/
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

## MCP stdio client config

```json
{
  "mcpServers": {
    "linkedin": {
      "command": "uv",
      "args": ["run", "linkedin-mcp"],
      "cwd": "/path/to/linkedin"
    }
  }
}
```

Remote MCP clients can connect to `http://localhost:8765/mcp`. When
`MCP_API_KEY` is configured, send it as either `Authorization: Bearer <key>` or
`X-API-Key: <key>`. The `/tools` and `/call` endpoints remain available for
legacy REST clients.
