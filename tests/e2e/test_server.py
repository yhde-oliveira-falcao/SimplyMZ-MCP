from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from mcp import Client

from simplymz_mcp.config import Config
from simplymz_mcp.core.envelope import is_valid_envelope
from simplymz_mcp.server import build_server
from tests.helpers import RawStdioSession

pytestmark = pytest.mark.e2e


@pytest.mark.anyio
async def test_in_process_client_lists_tools_and_calls_server_info(tmp_path: Path) -> None:
    server, registry = build_server(Config(root=tmp_path))
    async with Client(server) as client:
        tools = await client.list_tools()
        assert "server_info" in [t.name for t in tools.tools]
        res = await client.call_tool("server_info", {})
    assert not res.is_error
    env = res.structured_content
    assert is_valid_envelope(env)
    assert env["status"] == "ok"
    assert env["data"]["root"] == str(tmp_path)
    assert env["data"]["tools"] == registry.names()
    assert {"server_info", "load_run", "run_card", "get_chromatogram"} <= set(registry.names())


def test_stdio_session_emits_only_json_rpc_on_stdout(tmp_path: Path) -> None:
    s = RawStdioSession(tmp_path, ["--log-level", "DEBUG"])
    try:
        init = s.initialize()
        assert init["result"]["serverInfo"]["name"] == "simplymz-mcp"
        listed = s.request("tools/list", {})
        assert "server_info" in [t["name"] for t in listed["result"]["tools"]]
        called = s.request("tools/call", {"name": "server_info", "arguments": {}})
        assert is_valid_envelope(called["result"]["structuredContent"])
        # An unknown tool must still be answered in JSON-RPC, never a traceback on stdout.
        s.request("tools/call", {"name": "nope", "arguments": {}})
    finally:
        stderr = s.close()
    assert s.stdout_lines, "server produced no output"
    for line in s.stdout_lines:
        msg = json.loads(line)  # every stdout line must be JSON
        assert msg.get("jsonrpc") == "2.0", line
    assert "starting simplymz-mcp" in stderr  # logs went to stderr instead


def test_cli_rejects_missing_root(tmp_path: Path) -> None:
    p = subprocess.run(
        [sys.executable, "-m", "simplymz_mcp.server", "--root", str(tmp_path / "missing")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert p.returncode == 2
    assert p.stdout == ""
    assert "not a directory" in p.stderr


@pytest.mark.anyio
async def test_each_mcp_tool_call_writes_one_matching_ledger_entry(tmp_path: Path) -> None:
    server, _ = build_server(Config(root=tmp_path))
    ledger = server.app.ledger  # type: ignore[attr-defined]
    ids = []
    async with Client(server) as client:
        for _ in range(3):
            res = await client.call_tool("server_info", {})
            ids.append(res.structured_content["provenance_id"])
    assert ledger.ids() == ids
    for ev in ids:
        rec = ledger.get(ev)
        assert rec is not None and rec["op"] == "server_info"
