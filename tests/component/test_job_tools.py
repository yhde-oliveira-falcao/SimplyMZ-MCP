from __future__ import annotations

import shutil
import time
from pathlib import Path

import anyio
import pytest
from mcp import Client

import simplymz_mcp.tools.batch as batch_mod
from simplymz_mcp.config import Config
from simplymz_mcp.server import build_server
from tests.conftest import FIXTURES


async def _call(client: Client, tool: str, **args: object) -> dict:
    return (await client.call_tool(tool, args)).structured_content


async def _wait(client: Client, job: str, timeout: float = 120) -> dict:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        st = await _call(client, "job_status", job_handle=job)
        if st["data"]["state"] in ("done", "failed", "cancelled"):
            return st
        await anyio.sleep(0.1)
    raise TimeoutError(job)


@pytest.mark.anyio
async def test_large_batch_qc_runs_as_job_and_survives_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shutil.copytree(FIXTURES / "batch_qc", tmp_path / "batch_qc")
    monkeypatch.setattr(batch_mod, "MAX_SYNC_RUNS", 5)
    cfg = Config(root=tmp_path, cache_dir=tmp_path / "cache")
    server, _ = build_server(cfg)
    async with Client(server) as client:
        b = await _call(client, "load_batch", sample_sheet="batch_qc/sample_sheet.csv")
        t0 = time.monotonic()
        sub = await _call(client, "qc_batch", batch_handle=b["data"]["batch_handle"])
        assert time.monotonic() - t0 < 1.0  # handle returned immediately
        job = sub["data"]["job_handle"]
        assert job.startswith("job:") and "job_status" in sub["next_steps"][0]
        st = await _wait(client, job)
        assert st["data"]["state"] == "done", st
        result = st["data"]["result"]
        assert result["data"]["overall"] == "pass"
        ev = result["provenance_id"]
        rec = server.app.ledger.get(ev)  # type: ignore[attr-defined]
        assert (
            rec["op"] == "qc_batch" and rec["params"]["batch_handle"] == b["data"]["batch_handle"]
        )
        again = await _call(client, "cancel_job", job_handle=job)
        assert again["data"]["cancel_requested"] is False
    server.app.jobs.shutdown()  # type: ignore[attr-defined]
    server2, _ = build_server(cfg)  # restart
    async with Client(server2) as client:
        st2 = await _call(client, "job_status", job_handle=job)
    assert st2["data"]["state"] == "done" and st2["data"]["result"]["provenance_id"] == ev


@pytest.mark.anyio
async def test_unknown_job_is_instructive(tmp_path: Path) -> None:
    server, _ = build_server(Config(root=tmp_path))
    async with Client(server) as client:
        st = await _call(client, "job_status", job_handle="job:01ARZ3NDEKTSV4RRFFQ69G5FAV")
    assert st["error"]["code"] == "UNKNOWN_HANDLE"
