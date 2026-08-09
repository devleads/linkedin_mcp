"""HTTP Client for LinkedIn MCP Server.

This module provides a client to connect to the LinkedIn MCP HTTP server
running at 127.0.0.1:8765. Used by test scripts.

Start the server first:
    uv run python -m linkedin_mcp.http_server
"""

import asyncio
import aiohttp
from typing import Any, Optional


class MCPClient:
    """Client for communicating with LinkedIn MCP HTTP Server."""
    
    def __init__(self, host: str = "127.0.0.1", port: int = 8765):
        """Initialize MCP client.
        
        Args:
            host: Server host (default: 127.0.0.1)
            port: Server port (default: 8765)
        """
        self.base_url = f"http://{host}:{port}"
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def start(self) -> None:
        """Start the HTTP client session."""
        self._session = aiohttp.ClientSession()
        
        # Check if server is running
        try:
            async with self._session.get(f"{self.base_url}/health") as resp:
                if resp.status != 200:
                    raise RuntimeError(f"Server health check failed: {resp.status}")
                data = await resp.json()
                if data.get("status") != "ok":
                    raise RuntimeError(f"Server not healthy: {data}")
        except aiohttp.ClientConnectorError:
            raise RuntimeError(
                f"Cannot connect to server at {self.base_url}. "
                "Start it with: uv run python -m linkedin_mcp.http_server"
            )
    
    async def stop(self) -> None:
        """Close the HTTP client session."""
        if self._session:
            await self._session.close()
            self._session = None
    
    async def list_tools(self) -> list:
        """List available tools."""
        async with self._session.get(f"{self.base_url}/tools") as resp:
            data = await resp.json()
            return data.get("tools", [])
    
    async def call_tool(self, name: str, arguments: dict) -> dict:
        """Call a tool with arguments.
        
        Args:
            name: Tool name
            arguments: Tool arguments
        
        Returns:
            Tool result as dict
        """
        async with self._session.post(
            f"{self.base_url}/call",
            json={"tool": name, "arguments": arguments}
        ) as resp:
            return await resp.json()
    
    # Convenience methods for each tool
    
    async def set_cookies(
        self,
        profile_id: str,
        li_at: str,
        jsessionid: Optional[str] = None,
    ) -> dict:
        """Set LinkedIn authentication cookies."""
        args = {"profile_id": profile_id, "li_at": li_at}
        if jsessionid:
            args["jsessionid"] = jsessionid
        return await self.call_tool("set_cookies", args)
    
    async def login(
        self,
        profile_id: str,
        email: Optional[str] = None,
        password: Optional[str] = None,
        totp_code: Optional[str] = None,
    ) -> dict:
        """Login to LinkedIn."""
        args = {"profile_id": profile_id}
        if email:
            args["email"] = email
        if password:
            args["password"] = password
        if totp_code:
            args["totp_code"] = totp_code
        return await self.call_tool("login", args)
    
    async def get_session_status(self, profile_id: str) -> dict:
        """Get session status."""
        return await self.call_tool("get_session_status", {"profile_id": profile_id})

    async def open_manual_browser(self, profile_id: str, url: Optional[str] = None) -> dict:
        """Open and pin a persistent browser window for manual actions."""
        args = {"profile_id": profile_id}
        if url:
            args["url"] = url
        return await self.call_tool("open_manual_browser", args)

    async def save_session_cookies(self, profile_id: str) -> dict:
        """Save cookies from active browser session into profile storage."""
        return await self.call_tool("save_session_cookies", {"profile_id": profile_id})

    async def close_session(self, profile_id: str) -> dict:
        """Close browser session."""
        return await self.call_tool("close_session", {"profile_id": profile_id})
    
    async def read_feed(
        self,
        profile_id: str,
        max_posts: int = 10,
        scroll_count: int = 3,
    ) -> dict:
        """Read LinkedIn feed."""
        return await self.call_tool("read_feed", {
            "profile_id": profile_id,
            "max_posts": max_posts,
            "scroll_count": scroll_count,
        })
    
    async def get_profile(
        self,
        profile_id: str,
        linkedin_url: str,
        include_activity: bool = False,
        max_posts: int = 5,
    ) -> dict:
        """Get LinkedIn profile details.
        
        Args:
            profile_id: Profile UUID (your account)
            linkedin_url: URL of the LinkedIn profile to view
            include_activity: Whether to fetch recent posts and comments
            max_posts: Maximum number of recent posts to fetch
        """
        args = {
            "profile_id": profile_id,
            "linkedin_url": linkedin_url,
        }
        if include_activity:
            args["include_activity"] = include_activity
            args["max_posts"] = max_posts
        return await self.call_tool("get_profile", args)
    
    async def get_company(self, profile_id: str, company_url: str) -> dict:
        """Get LinkedIn company details."""
        return await self.call_tool("get_company", {
            "profile_id": profile_id,
            "company_url": company_url,
        })
    
    async def search_people(
        self,
        profile_id: str,
        keywords: str,
        country: Optional[str] = None,
        connection_degree: Optional[list] = None,
        page: int = 1,
        max_results: int = 10,
    ) -> dict:
        """Search for people on LinkedIn."""
        args = {
            "profile_id": profile_id,
            "keywords": keywords,
            "page": page,
            "max_results": max_results,
        }
        if country:
            args["country"] = country
        if connection_degree:
            args["connection_degree"] = connection_degree
        return await self.call_tool("search_people", args)
    
    async def read_messages(
        self,
        profile_id: str,
        max_conversations: int = 0,
        max_messages_per_conversation: int = 20,
    ) -> dict:
        """Read LinkedIn messages."""
        return await self.call_tool("read_messages", {
            "profile_id": profile_id,
            "max_conversations": max_conversations,
            "max_messages_per_conversation": max_messages_per_conversation,
        })
    
    async def send_message(
        self,
        profile_id: str,
        recipient_url: str,
        message: str,
    ) -> dict:
        """Send a direct message."""
        return await self.call_tool("send_message", {
            "profile_id": profile_id,
            "recipient_url": recipient_url,
            "message": message,
        })

    async def send_inbox_message(
        self,
        profile_id: str,
        message: str,
        conversation_id: Optional[str] = None,
        participant_profile_url: Optional[str] = None,
        existing_thread_only: bool = True,
    ) -> dict:
        """Send a message in LinkedIn inbox thread flow (not profile-direct)."""
        args = {
            "profile_id": profile_id,
            "message": message,
            "existing_thread_only": existing_thread_only,
        }
        if conversation_id:
            args["conversation_id"] = conversation_id
        if participant_profile_url:
            args["participant_profile_url"] = participant_profile_url
        return await self.call_tool("send_inbox_message", args)
    
    async def send_connection_request(
        self,
        profile_id: str,
        recipient_url: str,
        note: Optional[str] = None,
    ) -> dict:
        """Send a connection request."""
        args = {
            "profile_id": profile_id,
            "recipient_url": recipient_url,
        }
        if note:
            args["note"] = note
        return await self.call_tool("send_connection_request", args)
    
    async def search_posts(
        self,
        profile_id: str,
        keywords: list,
        max_posts: int = 10,
        scroll_count: int = 3,
    ) -> dict:
        """Search for LinkedIn posts by keywords using desktop browser."""
        return await self.call_tool("search_posts", {
            "profile_id": profile_id,
            "keywords": keywords,
            "max_posts": max_posts,
            "scroll_count": scroll_count,
        })
    
    async def get_post(
        self,
        profile_id: str,
        post_url: str,
    ) -> dict:
        """Get a LinkedIn post by URL."""
        return await self.call_tool("get_post", {
            "profile_id": profile_id,
            "post_url": post_url,
        })
    
    async def like_post(
        self,
        profile_id: str,
        post_url: str,
    ) -> dict:
        """Like a LinkedIn post."""
        return await self.call_tool("like_post", {
            "profile_id": profile_id,
            "post_url": post_url,
        })
    
    async def comment_post(
        self,
        profile_id: str,
        post_url: str,
        comment_text: str,
    ) -> dict:
        """Comment on a LinkedIn post."""
        return await self.call_tool("comment_post", {
            "profile_id": profile_id,
            "post_url": post_url,
            "comment_text": comment_text,
        })

    async def like_and_comment_post(
        self,
        profile_id: str,
        post_url: str,
        comment_text: str,
    ) -> dict:
        """Like and comment on a LinkedIn post in one operation."""
        return await self.call_tool("like_and_comment_post", {
            "profile_id": profile_id,
            "post_url": post_url,
            "comment_text": comment_text,
        })

    async def create_post(
        self,
        profile_id: str,
        content: str,
        image_path: Optional[str] = None,
    ) -> dict:
        """Create a post from the personal account.
        
        Args:
            profile_id: Profile UUID
            content: Post text content
            image_path: Optional path to image file to attach
        """
        args = {
            "profile_id": profile_id,
            "content": content,
        }
        if image_path:
            args["image_path"] = image_path
        return await self.call_tool("create_post", args)
    
    async def create_company_post(
        self,
        profile_id: str,
        company_url: str,
        content: str,
        image_path: Optional[str] = None,
    ) -> dict:
        """Create a post on behalf of a company page.
        
        Args:
            profile_id: Profile UUID (must have admin access to the company)
            company_url: LinkedIn company page URL
            content: Post text content
            image_path: Optional path to image file to attach
        """
        args = {
            "profile_id": profile_id,
            "company_url": company_url,
            "content": content,
        }
        if image_path:
            args["image_path"] = image_path
        return await self.call_tool("create_company_post", args)


async def main():
    """Test the MCP client."""
    client = MCPClient()
    
    try:
        print("Connecting to server...")
        await client.start()
        print(f"Connected to {client.base_url}")
        
        print("Listing tools...")
        tools = await client.list_tools()
        print(f"Available tools: {tools}")
        
    finally:
        await client.stop()


if __name__ == "__main__":
    asyncio.run(main())
