"""HTTP control-plane authentication, CORS, and request validation tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp.test_utils import TestClient, TestServer
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from linkedin_mcp.http_server import create_app, validate_http_settings


async def _client():
    manager = MagicMock()
    manager.close_all = AsyncMock()
    patcher = patch("linkedin_mcp.http_server.get_session_manager", return_value=manager)
    patcher.start()
    client = TestClient(TestServer(create_app()))
    await client.start_server()
    return client, patcher


def test_remote_binding_requires_api_key(monkeypatch):
    monkeypatch.setenv("MCP_HOST", "0.0.0.0")
    monkeypatch.setenv("MCP_API_KEY", "")
    with pytest.raises(RuntimeError, match="MCP_API_KEY"):
        validate_http_settings()


def test_loopback_binding_allows_local_operation(monkeypatch):
    monkeypatch.setenv("MCP_HOST", "127.0.0.1")
    monkeypatch.setenv("MCP_API_KEY", "")
    validate_http_settings()


@pytest.mark.asyncio
async def test_tools_requires_configured_api_key(monkeypatch):
    monkeypatch.setenv("MCP_API_KEY", "expected-key")
    client, patcher = await _client()
    try:
        response = await client.get("/tools")
        assert response.status == 401
        authorized = await client.get("/tools", headers={"X-API-Key": "expected-key"})
        assert authorized.status == 200
    finally:
        await client.close()
        patcher.stop()


@pytest.mark.asyncio
async def test_cors_only_echoes_allowlisted_origin(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://allowed.example")
    client, patcher = await _client()
    try:
        allowed = await client.get("/health", headers={"Origin": "https://allowed.example"})
        assert allowed.headers["Access-Control-Allow-Origin"] == "https://allowed.example"
        denied = await client.get("/health", headers={"Origin": "https://denied.example"})
        assert "Access-Control-Allow-Origin" not in denied.headers
    finally:
        await client.close()
        patcher.stop()


@pytest.mark.asyncio
async def test_request_size_is_bounded(monkeypatch):
    monkeypatch.setenv("HTTP_MAX_REQUEST_BYTES", "1024")
    client, patcher = await _client()
    try:
        response = await client.post(
            "/call",
            data="x" * 2048,
            headers={"Content-Type": "application/json"},
        )
        assert response.status == 413
        assert (await response.json())["code"] == "REQUEST_TOO_LARGE"
    finally:
        await client.close()
        patcher.stop()


@pytest.mark.asyncio
async def test_per_client_rate_limit(monkeypatch):
    monkeypatch.setenv("HTTP_RATE_LIMIT_PER_MINUTE", "1")
    client, patcher = await _client()
    try:
        assert (await client.get("/tools")).status == 200
        limited = await client.get("/tools")
        assert limited.status == 429
        assert (await limited.json())["code"] == "RATE_LIMITED"
    finally:
        await client.close()
        patcher.stop()


@pytest.mark.asyncio
async def test_standard_mcp_streamable_http_lists_agent_tools(monkeypatch):
    monkeypatch.setenv("HTTP_RATE_LIMIT_PER_MINUTE", "60")
    client, patcher = await _client()
    try:
        url = str(client.make_url("/mcp"))
        async with streamable_http_client(url, terminate_on_close=False) as (read, write, _):
            async with ClientSession(read, write) as session:
                initialized = await session.initialize()
                result = await session.list_tools()
                call_result = await session.call_tool(
                    "get_session_status",
                    {"profile_id": "00000000-0000-0000-0000-000000000001"},
                )
        assert initialized.serverInfo.name == "linkedin-mcp"
        assert initialized.instructions
        assert "read_feed" in {tool.name for tool in result.tools}
        read_feed = next(tool for tool in result.tools if tool.name == "read_feed")
        assert read_feed.inputSchema["additionalProperties"] is False
        assert read_feed.inputSchema["properties"]["profile_id"]["description"]
        assert call_result.isError is False
        assert call_result.structuredContent["status"] == "no_session"
    finally:
        await client.close()
        patcher.stop()
