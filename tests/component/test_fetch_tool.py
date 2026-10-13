from __future__ import annotations

from pathlib import Path

import pytest
from mcp import Client

from simplymz_mcp.config import Config
from simplymz_mcp.server import build_server


@pytest.mark.anyio
async def test_fetch_needs_confirmation_and_known_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import simplymz_mcp.datasets as ds

    def no_network(*a: object, **k: object) -> None:
        raise AssertionError("network used without confirm=true")

    monkeypatch.setattr(ds, "download", no_network)
    server, _ = build_server(Config(root=tmp_path))
    async with Client(server) as client:
        ask = (
            await client.call_tool("fetch_public_dataset", {"dataset_id": "openms-ffm-1"})
        ).structured_content
        bad = (
            await client.call_tool("fetch_public_dataset", {"dataset_id": "nope", "confirm": True})
        ).structured_content
    assert ask["status"] == "insufficient_evidence" and "confirm=true" in ask["verdict"]
    assert ask["data"]["licence"].startswith("BSD-3-Clause")
    assert bad["error"]["code"] == "INVALID_ARGUMENT" and "openms-ffm-1" in bad["error"]["hint"]
