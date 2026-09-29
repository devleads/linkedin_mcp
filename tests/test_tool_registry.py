"""Canonical tool registry parity and schema tests."""

import pytest

from linkedin_mcp.dispatcher import get_tool_names
from linkedin_mcp.server import call_tool, list_tools
from linkedin_mcp.tools.registry import get_tool_specs


@pytest.mark.asyncio
async def test_mcp_and_dispatcher_use_same_tool_names():
    mcp_names = [tool.name for tool in await list_tools()]
    assert mcp_names == get_tool_names()


def test_every_tool_declares_effect_and_schema():
    for spec in get_tool_specs().values():
        assert spec.effect in {"read", "write"}
        schema = spec.input_schema()
        assert schema["type"] == "object"
        assert set(schema["required"]) == set(spec.required)
        assert schema["additionalProperties"] is False
        assert schema["properties"]["profile_id"]["description"]


@pytest.mark.asyncio
async def test_mcp_tool_errors_set_protocol_error_flag(monkeypatch):
    async def failed_dispatch(name, arguments):
        return {"status": "error", "code": "INVALID_REQUEST", "message": "bad request"}

    monkeypatch.setattr("linkedin_mcp.server.dispatch_tool", failed_dispatch)
    result = await call_tool("read_feed", {"profile_id": "profile"})
    assert result.isError is True
    assert result.structuredContent["code"] == "INVALID_REQUEST"
