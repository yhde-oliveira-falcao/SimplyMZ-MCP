"""Final Verification D16: no network access outside fetch_public_dataset."""

from __future__ import annotations

import shutil
import socket
from pathlib import Path

import pytest
from mcp import Client

from simplymz_mcp.config import Config
from simplymz_mcp.server import build_server
from tests.conftest import FIXTURES


@pytest.mark.anyio
async def test_workflows_run_with_sockets_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for d in ("runs", "batch_qc", "library"):
        shutil.copytree(FIXTURES / d, tmp_path / d)
    server, _ = build_server(Config(root=tmp_path))
    attempts: list[object] = []

    def deny(self: socket.socket, address: object) -> None:
        attempts.append(address)
        raise OSError("network disabled for this test")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: deny(None, a[0]))  # type: ignore[arg-type]
    async with Client(server) as client:

        async def call(tool: str, **args: object) -> dict:
            env = (await client.call_tool(tool, args)).structured_content
            assert env["status"] != "error", (tool, env)
            return env

        b = await call("load_batch", sample_sheet="batch_qc/sample_sheet.csv")
        await call("qc_batch", batch_handle=b["data"]["batch_handle"])
        run = (await call("load_run", path="runs/ms2_dda.mzML.gz"))["data"]["run_handle"]
        lib = (await call("load_library", path="library/synthetic_library.msp"))["data"]
        m = await call(
            "match_spectrum",
            run_handle=run,
            precursor_mz=195.087652,
            library_handle=lib["library_handle"],
            rt_min=4.4,
        )
        f = await call("propose_formulas", mz=195.087652, run_handle=run, rt_min=4.4)
        await call("assign_confidence", evidence=[m["provenance_id"], f["provenance_id"]])
        await call(
            "export_report",
            title="offline",
            filename="offline",
            sections=[{"heading": "x", "body": "No numbers here."}],
        )
        ask = await call("fetch_public_dataset", dataset_id="openms-ffm-1")
        assert ask["status"] == "insufficient_evidence"  # asks for confirmation, no network
    assert attempts == []
