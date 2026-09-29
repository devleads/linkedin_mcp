"""HTTP API Server for LinkedIn MCP.

Provides a REST API that wraps the MCP tools for remote client access.
Server listens on 127.0.0.1:8765 by default (configurable via MCP_HOST/MCP_PORT).

Remote clients can connect via HTTP POST to /call endpoint.

Usage:
    uv run python -m linkedin_mcp.http_server

Endpoints:
    GET  /health  - Health check
    GET  /tools   - List available tools
    POST /call    - Execute a tool (JSON body: {"tool": "name", "arguments": {...}})
"""

import json
import logging
import asyncio
import hmac
import time
from collections import defaultdict, deque
from aiohttp import web
from aiohttp.web import middleware

from linkedin_mcp.dispatcher import dispatch_tool, get_tool_names
from linkedin_mcp.browser.session import get_session_manager
from linkedin_mcp.config import get_settings, setup_logging

# Configure logging at module load
setup_logging()
logger = logging.getLogger(__name__)
RATE_LIMIT_EVENTS_KEY = web.AppKey("rate_limit_events", dict)


def _allowed_origins() -> set[str]:
    return {
        origin.strip()
        for origin in get_settings().allowed_origins.split(",")
        if origin.strip()
    }


def _provided_api_key(request: web.Request) -> str:
    api_key = request.headers.get("X-API-Key", "")
    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("bearer "):
        api_key = authorization[7:].strip()
    return api_key


@middleware
async def authentication_middleware(request: web.Request, handler):
    """Protect every non-health HTTP endpoint when an API key is configured."""
    if request.path == "/health" or request.method == "OPTIONS":
        return await handler(request)

    expected = get_settings().mcp_api_key.get_secret_value()
    if expected and not hmac.compare_digest(_provided_api_key(request), expected):
        return web.json_response(
            {"status": "error", "code": "UNAUTHORIZED", "message": "Unauthorized"},
            status=401,
        )
    return await handler(request)


@middleware
async def rate_limit_middleware(request: web.Request, handler):
    """Apply a bounded per-client HTTP request rate."""
    if request.path == "/health" or request.method == "OPTIONS":
        return await handler(request)
    client = request.remote or "unknown"
    now = time.monotonic()
    events = request.app[RATE_LIMIT_EVENTS_KEY][client]
    while events and events[0] <= now - 60:
        events.popleft()
    if len(events) >= get_settings().http_rate_limit_per_minute:
        return web.json_response(
            {"status": "error", "code": "RATE_LIMITED", "message": "Too many requests"},
            status=429,
        )
    events.append(now)
    return await handler(request)


@middleware
async def cors_middleware(request: web.Request, handler):
    """Add CORS headers only for explicitly allowed origins."""
    # Handle preflight OPTIONS requests
    if request.method == "OPTIONS":
        response = web.Response()
    else:
        response = await handler(request)
    
    origin = request.headers.get("Origin")
    if origin and origin in _allowed_origins():
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-API-Key"
        response.headers["Access-Control-Max-Age"] = "86400"
    return response


async def handle_tool_call(request: web.Request) -> web.Response:
    """Handle tool call requests.
    
    Request body:
        {
            "tool": "tool_name",
            "arguments": {
                "arg1": "value1",
                ...
            }
        }
    
    Response:
        Tool-specific JSON response with "status" field.
    """
    try:
        data = await request.json()
        if not isinstance(data, dict):
            return web.json_response(
                {"status": "error", "code": "INVALID_REQUEST", "message": "JSON body must be an object"},
                status=400,
            )
        tool_name = data.get("tool")
        arguments = data.get("arguments", {})
        
        if not tool_name:
            return web.json_response({"status": "error", "message": "Missing 'tool' field"}, status=400)
        
        if not isinstance(arguments, dict):
            return web.json_response(
                {"status": "error", "code": "INVALID_REQUEST", "message": "'arguments' must be an object"},
                status=400,
            )

        logger.info(f"Tool call: {tool_name} with args: {list(arguments.keys())}")
        try:
            result = await asyncio.wait_for(
                dispatch_tool(tool_name, arguments),
                timeout=get_settings().http_tool_timeout_seconds,
            )
        except asyncio.TimeoutError:
            return web.json_response(
                {"status": "error", "code": "TOOL_TIMEOUT", "message": "Tool execution timed out"},
                status=504,
            )
        return web.json_response(result)
        
    except (json.JSONDecodeError, web.HTTPBadRequest):
        return web.json_response({"status": "error", "message": "Invalid JSON"}, status=400)
    except web.HTTPRequestEntityTooLarge:
        return web.json_response(
            {"status": "error", "code": "REQUEST_TOO_LARGE", "message": "Request body is too large"},
            status=413,
        )
    except Exception as exc:
        logger.error("Tool call failed (%s)", type(exc).__name__)
        return web.json_response(
            {"status": "error", "code": "INTERNAL_ERROR", "message": "Internal server error"},
            status=500,
        )


async def handle_health(request: web.Request) -> web.Response:
    """Health check endpoint."""
    return web.json_response({
        "status": "ok",
        "service": "linkedin-mcp",
        "version": "1.0.0",
    })


async def handle_list_tools(request: web.Request) -> web.Response:
    """List available tools with descriptions."""
    tools = get_tool_names()
    return web.json_response({
        "tools": tools,
        "count": len(tools),
    })


async def on_shutdown(app: web.Application):
    """Cleanup on shutdown."""
    logger.info("Shutting down, closing all sessions...")
    session_manager = get_session_manager()
    await session_manager.close_all()


def create_app() -> web.Application:
    """Create the aiohttp application with CORS support."""
    validate_http_settings()
    app = web.Application(
        middlewares=[cors_middleware, authentication_middleware, rate_limit_middleware],
        client_max_size=get_settings().http_max_request_bytes,
    )
    app[RATE_LIMIT_EVENTS_KEY] = defaultdict(deque)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/tools", handle_list_tools)
    app.router.add_post("/call", handle_tool_call)
    app.router.add_route("OPTIONS", "/call", handle_tool_call)  # CORS preflight
    app.on_shutdown.append(on_shutdown)
    return app


def validate_http_settings() -> None:
    """Refuse unauthenticated binding to a non-loopback interface."""
    settings = get_settings()
    loopback_hosts = {"127.0.0.1", "::1", "localhost"}
    if settings.mcp_host not in loopback_hosts and not settings.mcp_api_key.get_secret_value():
        raise RuntimeError("MCP_API_KEY is required when MCP_HOST is not loopback")


def main():
    """Run the HTTP server."""
    settings = get_settings()
    validate_http_settings()
    app = create_app()
    
    logger.info(f"Starting LinkedIn MCP HTTP server on {settings.mcp_host}:{settings.mcp_port}")
    web.run_app(app, host=settings.mcp_host, port=settings.mcp_port)


if __name__ == "__main__":
    main()
