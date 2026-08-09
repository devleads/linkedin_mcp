"""LinkedIn MCP Server implementation."""

import asyncio
import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from linkedin_mcp.dispatcher import dispatch_tool
from linkedin_mcp.browser.session import get_session_manager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create MCP server
server = Server("linkedin-mcp")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available LinkedIn MCP tools."""
    return [
        Tool(
            name="set_cookies",
            description="Set LinkedIn authentication cookies (li_at) for a profile. Use this for purchased accounts.",
            inputSchema={
                "type": "object",
                "properties": {
                    "profile_id": {
                        "type": "string",
                        "description": "Profile identifier",
                    },
                    "li_at": {
                        "type": "string",
                        "description": "LinkedIn auth token (li_at cookie value)",
                    },
                    "jsessionid": {
                        "type": "string",
                        "description": "Optional JSESSIONID cookie value",
                    },
                },
                "required": ["profile_id", "li_at"],
            },
        ),
        Tool(
            name="login",
            description="Login to LinkedIn with credentials and optional 2FA. First tries stored cookies.",
            inputSchema={
                "type": "object",
                "properties": {
                    "profile_id": {
                        "type": "string",
                        "description": "Profile identifier",
                    },
                    "email": {
                        "type": "string",
                        "description": "LinkedIn email (optional, uses profile email if not provided)",
                    },
                    "password": {
                        "type": "string",
                        "description": "LinkedIn password (optional, uses profile password if not provided)",
                    },
                    "totp_code": {
                        "type": "string",
                        "description": "2FA TOTP code if required",
                    },
                },
                "required": ["profile_id"],
            },
        ),
        Tool(
            name="get_session_status",
            description="Get status of a browser session.",
            inputSchema={
                "type": "object",
                "properties": {
                    "profile_id": {
                        "type": "string",
                        "description": "Profile identifier",
                    },
                },
                "required": ["profile_id"],
            },
        ),
        Tool(
            name="open_manual_browser",
            description="Open and pin a persistent browser window for manual profile actions.",
            inputSchema={
                "type": "object",
                "properties": {
                    "profile_id": {
                        "type": "string",
                        "description": "Profile identifier",
                    },
                    "url": {
                        "type": "string",
                        "description": "Optional URL to open (defaults to LinkedIn home)",
                    },
                },
                "required": ["profile_id"],
            },
        ),
        Tool(
            name="save_session_cookies",
            description="Save cookies from active browser session to profile storage.",
            inputSchema={
                "type": "object",
                "properties": {
                    "profile_id": {
                        "type": "string",
                        "description": "Profile identifier",
                    },
                },
                "required": ["profile_id"],
            },
        ),
        Tool(
            name="close_session",
            description="Close a browser session and save cookies.",
            inputSchema={
                "type": "object",
                "properties": {
                    "profile_id": {
                        "type": "string",
                        "description": "Profile identifier",
                    },
                },
                "required": ["profile_id"],
            },
        ),
        Tool(
            name="read_feed",
            description="Read LinkedIn feed posts.",
            inputSchema={
                "type": "object",
                "properties": {
                    "profile_id": {
                        "type": "string",
                        "description": "Profile identifier",
                    },
                    "max_posts": {
                        "type": "integer",
                        "description": "Maximum number of posts to return (default: 10)",
                        "default": 10,
                    },
                    "scroll_count": {
                        "type": "integer",
                        "description": "Number of times to scroll for more content (default: 3)",
                        "default": 3,
                    },
                },
                "required": ["profile_id"],
            },
        ),
        Tool(
            name="get_profile",
            description="Get LinkedIn profile details by URL.",
            inputSchema={
                "type": "object",
                "properties": {
                    "profile_id": {
                        "type": "string",
                        "description": "Profile identifier (your account)",
                    },
                    "linkedin_url": {
                        "type": "string",
                        "description": "URL of the LinkedIn profile to view",
                    },
                },
                "required": ["profile_id", "linkedin_url"],
            },
        ),
        Tool(
            name="get_company",
            description="Get LinkedIn company details by URL.",
            inputSchema={
                "type": "object",
                "properties": {
                    "profile_id": {
                        "type": "string",
                        "description": "Profile identifier (your account)",
                    },
                    "company_url": {
                        "type": "string",
                        "description": "URL of the LinkedIn company page",
                    },
                },
                "required": ["profile_id", "company_url"],
            },
        ),
        Tool(
            name="search_people",
            description="Search for people on LinkedIn.",
            inputSchema={
                "type": "object",
                "properties": {
                    "profile_id": {
                        "type": "string",
                        "description": "Profile identifier (your account)",
                    },
                    "keywords": {
                        "type": "string",
                        "description": "Search keywords",
                    },
                    "country": {
                        "type": "string",
                        "description": "Country code to filter by (e.g., 'US', 'AE', 'GB')",
                    },
                    "connection_degree": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Connection degrees to filter by (e.g., ['2', '3'])",
                    },
                    "page": {
                        "type": "integer",
                        "description": "Page number for pagination (default: 1)",
                        "default": 1,
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum results to return (default: 10)",
                        "default": 10,
                    },
                },
                "required": ["profile_id", "keywords"],
            },
        ),
        Tool(
            name="search_posts",
            description="Search for LinkedIn posts by keywords.",
            inputSchema={
                "type": "object",
                "properties": {
                    "profile_id": {
                        "type": "string",
                        "description": "Profile identifier (your account)",
                    },
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of keywords to search for in posts",
                    },
                    "max_posts": {
                        "type": "integer",
                        "description": "Maximum posts to return (default: 10)",
                        "default": 10,
                    },
                    "scroll_count": {
                        "type": "integer",
                        "description": "Number of times to scroll for more content (default: 5)",
                        "default": 5,
                    },
                },
                "required": ["profile_id", "keywords"],
            },
        ),
        Tool(
            name="get_post",
            description="Get a LinkedIn post by URL. Returns post details including whether the current account has liked or commented on it.",
            inputSchema={
                "type": "object",
                "properties": {
                    "profile_id": {
                        "type": "string",
                        "description": "Profile identifier",
                    },
                    "post_url": {
                        "type": "string",
                        "description": "Full LinkedIn post URL or path (e.g., /feed/update/urn:li:activity:...)",
                    },
                },
                "required": ["profile_id", "post_url"],
            },
        ),
        Tool(
            name="like_post",
            description="Like a LinkedIn post.",
            inputSchema={
                "type": "object",
                "properties": {
                    "profile_id": {
                        "type": "string",
                        "description": "Profile identifier",
                    },
                    "post_url": {
                        "type": "string",
                        "description": "Full LinkedIn post URL or path",
                    },
                },
                "required": ["profile_id", "post_url"],
            },
        ),
        Tool(
            name="comment_post",
            description="Comment on a LinkedIn post.",
            inputSchema={
                "type": "object",
                "properties": {
                    "profile_id": {
                        "type": "string",
                        "description": "Profile identifier",
                    },
                    "post_url": {
                        "type": "string",
                        "description": "Full LinkedIn post URL or path",
                    },
                    "comment_text": {
                        "type": "string",
                        "description": "Comment text to post",
                    },
                },
                "required": ["profile_id", "post_url", "comment_text"],
            },
        ),
        Tool(
            name="like_and_comment_post",
            description="Like and comment on a LinkedIn post in one operation (single page load).",
            inputSchema={
                "type": "object",
                "properties": {
                    "profile_id": {
                        "type": "string",
                        "description": "Profile identifier",
                    },
                    "post_url": {
                        "type": "string",
                        "description": "Full LinkedIn post URL or path",
                    },
                    "comment_text": {
                        "type": "string",
                        "description": "Comment text to post",
                    },
                },
                "required": ["profile_id", "post_url", "comment_text"],
            },
        ),
        Tool(
            name="read_messages",
            description="Read LinkedIn messages/conversations.",
            inputSchema={
                "type": "object",
                "properties": {
                    "profile_id": {
                        "type": "string",
                        "description": "Profile identifier",
                    },
                    "max_conversations": {
                        "type": "integer",
                        "description": "Maximum number of latest conversations to return (0 = random 6-14)",
                        "default": 0,
                    },
                    "max_messages_per_conversation": {
                        "type": "integer",
                        "description": "Latest messages to return per conversation (<=0 uses default)",
                        "default": 20,
                    },
                },
                "required": ["profile_id"],
            },
        ),
        Tool(
            name="send_message",
            description="Send a direct message to a LinkedIn connection.",
            inputSchema={
                "type": "object",
                "properties": {
                    "profile_id": {
                        "type": "string",
                        "description": "Profile identifier",
                    },
                    "recipient_url": {
                        "type": "string",
                        "description": "LinkedIn profile URL of the recipient",
                    },
                    "message": {
                        "type": "string",
                        "description": "Message text to send",
                    },
                },
                "required": ["profile_id", "recipient_url", "message"],
            },
        ),
        Tool(
            name="send_inbox_message",
            description="Send a message using conversation-id thread routing or profile-url compose routing.",
            inputSchema={
                "type": "object",
                "properties": {
                    "profile_id": {
                        "type": "string",
                        "description": "Profile identifier",
                    },
                    "message": {
                        "type": "string",
                        "description": "Message text to send",
                    },
                    "conversation_id": {
                        "type": "string",
                        "description": "LinkedIn inbox conversation id (routes directly to thread)",
                    },
                    "participant_profile_url": {
                        "type": "string",
                        "description": "LinkedIn participant profile URL (routes via profile compose flow)",
                    },
                    "existing_thread_only": {
                        "type": "boolean",
                        "description": "Legacy compatibility flag retained for callers",
                        "default": True,
                    },
                },
                "required": ["profile_id", "message"],
            },
        ),
        Tool(
            name="send_connection_request",
            description="Send a connection request to a LinkedIn user.",
            inputSchema={
                "type": "object",
                "properties": {
                    "profile_id": {
                        "type": "string",
                        "description": "Profile identifier",
                    },
                    "recipient_url": {
                        "type": "string",
                        "description": "LinkedIn profile URL of the recipient",
                    },
                    "note": {
                        "type": "string",
                        "description": "Optional connection note (max 300 chars)",
                    },
                },
                "required": ["profile_id", "recipient_url"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls."""
    import json
    
    try:
        result = await dispatch_tool(name, arguments)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    except Exception as e:
        logger.error(f"Tool {name} failed: {e}")
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "message": str(e),
        }))]


async def cleanup():
    """Cleanup on shutdown."""
    session_manager = get_session_manager()
    await session_manager.close_all()


def main():
    """Main entry point for MCP server."""
    async def run():
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
