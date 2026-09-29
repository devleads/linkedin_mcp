"""Standard MCP server for LinkedIn browser tools."""

import asyncio
import json
import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent, Tool

from linkedin_mcp.browser.session import get_session_manager
from linkedin_mcp.dispatcher import dispatch_tool
from linkedin_mcp.tools.registry import get_tool_specs


logger = logging.getLogger(__name__)

server = Server(
    "linkedin-mcp",
    version="0.1.0",
    instructions=(
        "LinkedIn browser tools. Pass the target account UUID as profile_id on "
        "every tool call. Read tools may be retried. For write tools, provide a "
        "stable idempotency_key and do not retry UNKNOWN_WRITE_OUTCOME until the "
        "result has been reconciled. A profile with country=null uses a direct "
        "network connection."
    ),
)


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List the canonical LinkedIn tool definitions."""
    return [spec.as_mcp_tool() for spec in get_tool_specs().values()]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
    """Dispatch a tool and preserve structured results and MCP error semantics."""
    try:
        result = await dispatch_tool(name, arguments)
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(result, indent=2))],
            structuredContent=result,
            isError=result.get("status") == "error",
        )
    except Exception as exc:
        logger.error("Tool %s failed (%s)", name, type(exc).__name__)
        result = {
            "status": "error",
            "code": "INTERNAL_ERROR",
            "message": "Tool execution failed",
        }
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(result))],
            structuredContent=result,
            isError=True,
        )


async def cleanup() -> None:
    """Close browser sessions during transport shutdown."""
    await get_session_manager().close_all()


def main() -> None:
    """Run the MCP server over stdio."""

    async def run() -> None:
        async with stdio_server() as (read_stream, write_stream):
            try:
                await server.run(
                    read_stream,
                    write_stream,
                    server.create_initialization_options(),
                )
            finally:
                await cleanup()

    asyncio.run(run())


if __name__ == "__main__":
    main()
