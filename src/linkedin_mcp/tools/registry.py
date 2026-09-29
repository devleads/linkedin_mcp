"""Typed view of the canonical dispatcher tool definitions."""

from dataclasses import dataclass
from typing import Any, Literal

from mcp.types import Tool


WRITE_TOOLS = {
    "set_cookies",
    "login",
    "like_post",
    "comment_post",
    "like_and_comment_post",
    "send_message",
    "send_inbox_message",
    "send_connection_request",
    "create_post",
    "create_company_post",
}

LEDGER_TOOLS = WRITE_TOOLS - {"set_cookies", "login"}

DESCRIPTIONS = {
    "set_cookies": "Set LinkedIn authentication cookies for a profile.",
    "login": "Log in to LinkedIn with stored state or profile credentials.",
    "get_session_status": "Get the active browser session status.",
    "open_manual_browser": "Open and pin a browser window for manual profile actions.",
    "save_session_cookies": "Save active legacy browser state.",
    "close_session": "Close a browser session safely.",
    "read_feed": "Read LinkedIn feed posts.",
    "get_profile": "Read a LinkedIn member profile.",
    "get_company": "Read a LinkedIn company page.",
    "search_people": "Search for people on LinkedIn.",
    "search_posts": "Search for LinkedIn posts.",
    "get_post": "Read one LinkedIn post.",
    "like_post": "Like one verified LinkedIn post.",
    "comment_post": "Comment on one verified LinkedIn post.",
    "like_and_comment_post": "Like and comment on one verified LinkedIn post.",
    "read_messages": "Read LinkedIn conversations.",
    "send_message": "Send a message to one verified recipient.",
    "send_inbox_message": "Send a message in one verified existing conversation.",
    "send_connection_request": "Send a connection request to one verified recipient.",
    "create_post": "Create a post from the personal profile.",
    "create_company_post": "Create a post from a verified company identity.",
}

ARRAY_ARGUMENTS = {
    ("set_cookies", "cookies"),
    ("search_people", "connection_degree"),
    ("search_posts", "keywords"),
}
BOOLEAN_ARGUMENTS = {"include_activity", "existing_thread_only"}
INTEGER_ARGUMENTS = {
    "max_posts",
    "scroll_count",
    "page",
    "max_results",
    "max_conversations",
    "max_messages_per_conversation",
}

ARGUMENT_DESCRIPTIONS = {
    "profile_id": "UUID of the LinkedIn account profile that will perform the action.",
    "li_at": "LinkedIn li_at authentication cookie value.",
    "jsessionid": "Optional LinkedIn JSESSIONID cookie value.",
    "cookies": "Optional browser cookies as objects containing at least name and value.",
    "email": "LinkedIn login email; omit to use the stored profile email.",
    "password": "LinkedIn login password; omit to use the stored profile password.",
    "totp_code": "Current two-factor authentication code when LinkedIn requests one.",
    "url": "Absolute URL to open; defaults to the LinkedIn home page.",
    "max_posts": "Maximum number of posts to return.",
    "scroll_count": "Maximum number of feed or search result scrolls.",
    "linkedin_url": "Absolute LinkedIn member profile URL.",
    "include_activity": "Include recent activity in the member profile response.",
    "company_url": "Absolute LinkedIn company page URL.",
    "keywords": "Search terms. Post search accepts an array of individual terms.",
    "country": "Optional ISO 3166-1 alpha-2 country filter for people search.",
    "connection_degree": "Optional LinkedIn connection-degree filters such as ['1', '2', '3'].",
    "page": "One-based search result page number.",
    "max_results": "Maximum number of search results to return.",
    "post_url": "Absolute LinkedIn post URL.",
    "comment_text": "Comment text to publish.",
    "max_conversations": "Maximum conversations to return; zero uses the tool default range.",
    "max_messages_per_conversation": "Maximum recent messages returned for each conversation.",
    "recipient_url": "Absolute LinkedIn member profile URL for the recipient.",
    "message": "Message text to send.",
    "conversation_id": "Existing LinkedIn inbox conversation identifier.",
    "participant_profile_url": "LinkedIn member URL used to locate or compose the conversation.",
    "existing_thread_only": "Require an existing conversation instead of creating a new thread.",
    "note": "Optional connection-request note, limited by LinkedIn to 300 characters.",
    "content": "Text content to publish in the post.",
    "image_path": "Optional absolute path to an image available on the MCP server filesystem.",
}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    handler: Any
    required: tuple[str, ...]
    optional: dict[str, Any]
    effect: Literal["read", "write"]
    auth_recovery: bool

    def input_schema(self) -> dict[str, Any]:
        properties: dict[str, Any] = {}
        for argument in (*self.required, *self.optional.keys()):
            if (self.name, argument) in ARRAY_ARGUMENTS:
                schema: dict[str, Any] = {"type": "array"}
                schema["items"] = {"type": "object" if argument == "cookies" else "string"}
            elif argument in BOOLEAN_ARGUMENTS:
                schema = {"type": "boolean"}
            elif argument in INTEGER_ARGUMENTS:
                schema = {"type": "integer"}
            else:
                schema = {"type": "string"}
            description = ARGUMENT_DESCRIPTIONS.get(argument)
            if description:
                schema["description"] = description
            if argument in self.optional and self.optional[argument] is not None:
                schema["default"] = self.optional[argument]
            properties[argument] = schema
        if self.name in LEDGER_TOOLS:
            properties["idempotency_key"] = {
                "type": "string",
                "description": "Stable caller key used to prevent duplicate writes",
            }
        schema = {
            "type": "object",
            "properties": properties,
            "required": list(self.required),
            "additionalProperties": False,
        }
        if self.name == "send_inbox_message":
            schema["anyOf"] = [
                {"required": ["conversation_id"]},
                {"required": ["participant_profile_url"]},
            ]
        return schema

    def as_mcp_tool(self) -> Tool:
        return Tool(name=self.name, description=self.description, inputSchema=self.input_schema())


def get_tool_specs() -> dict[str, ToolSpec]:
    # Import lazily to avoid a dispatcher/registry import cycle.
    from linkedin_mcp.dispatcher import TOOLS

    return {
        name: ToolSpec(
            name=name,
            description=DESCRIPTIONS[name],
            handler=definition["handler"],
            required=tuple(definition["required"]),
            optional=dict(definition["optional"]),
            effect="write" if name in WRITE_TOOLS else "read",
            auth_recovery=definition["auth_recovery"],
        )
        for name, definition in TOOLS.items()
    }
