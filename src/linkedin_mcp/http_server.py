"""HTTP API Server for LinkedIn MCP.

Provides a REST API that wraps the MCP tools for remote client access.
Server listens on 0.0.0.0:8765 by default (configurable via MCP_HOST/MCP_PORT).

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
from aiohttp import web
from aiohttp.web import middleware

from linkedin_mcp.dispatcher import dispatch_tool, get_tool_names
from linkedin_mcp.browser.session import get_session_manager
from linkedin_mcp.config import get_settings, setup_logging

# Configure logging at module load
setup_logging()
logger = logging.getLogger(__name__)


@middleware
async def cors_middleware(request: web.Request, handler):
    """Add CORS headers for remote client access."""
    # Handle preflight OPTIONS requests
    if request.method == "OPTIONS":
        response = web.Response()
    else:
        response = await handler(request)
    
    # Allow all origins (configure ALLOWED_ORIGINS env var for production)
    origin = request.headers.get("Origin", "*")
    response.headers["Access-Control-Allow-Origin"] = origin
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
        tool_name = data.get("tool")
        arguments = data.get("arguments", {})
        
        if not tool_name:
            return web.json_response({"status": "error", "message": "Missing 'tool' field"}, status=400)
        
        logger.info(f"Tool call: {tool_name} with args: {list(arguments.keys())}")
        result = await dispatch_tool(tool_name, arguments)
        return web.json_response(result)
        
    except json.JSONDecodeError:
        return web.json_response({"status": "error", "message": "Invalid JSON"}, status=400)
    except Exception as e:
        logger.error(f"Tool call failed: {e}")
        return web.json_response({"status": "error", "message": str(e)}, status=500)


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
    app = web.Application(middlewares=[cors_middleware])
    app.router.add_get("/health", handle_health)
    app.router.add_get("/tools", handle_list_tools)
    app.router.add_post("/call", handle_tool_call)
    app.router.add_route("OPTIONS", "/call", handle_tool_call)  # CORS preflight
    app.on_shutdown.append(on_shutdown)
    return app


def main():
    """Run the HTTP server."""
    settings = get_settings()
    app = create_app()
    
    logger.info(f"Starting LinkedIn MCP HTTP server on {settings.mcp_host}:{settings.mcp_port}")
    web.run_app(app, host=settings.mcp_host, port=settings.mcp_port)


if __name__ == "__main__":
    main()
