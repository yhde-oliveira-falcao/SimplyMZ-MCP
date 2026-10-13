"""Unknown tool arguments are rejected (not silently ignored), for every tool."""

from __future__ import annotations

from pathlib import Path

import pytest
from mcp import Client

from simplymz_mcp.config import Config
from simplymz_mcp.server import build_server

pytestmark = pytest.mark.e2e


@pytest.mark.anyio
async def test_every_tool_schema_forbids_extra_and_calls_reject_it(tmp_path: Path) -> None:
    server, registry = build_server(Config(root=tmp_path))
    async with Client(server) as client:
        tools = (await client.list_tools()).tools
        assert {t.name for t in tools} == set(registry.names())
        for t in tools:
            assert t.input_schema.get("additionalProperties") is False, t.name
        res = await client.call_tool("server_info", {"surprise": 1})
        ok = await client.call_tool("server_info", {})
    assert res.is_error and "surprise" in res.content[0].text
    assert not ok.is_error
