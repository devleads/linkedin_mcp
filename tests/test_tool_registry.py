"""Canonical tool registry parity and schema tests."""

import pytest

from linkedin_mcp.dispatcher import get_tool_names
from linkedin_mcp.server import list_tools
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
