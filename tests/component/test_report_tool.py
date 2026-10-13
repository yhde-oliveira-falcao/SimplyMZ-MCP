from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from mcp import Client

from simplymz_mcp.config import Config
from simplymz_mcp.core.envelope import is_valid_envelope
from simplymz_mcp.server import build_server
from tests.conftest import FIXTURES


async def _call(client: Client, tool: str, **args: object) -> dict:
    env = (await client.call_tool(tool, args)).structured_content
    assert is_valid_envelope(env), env
    return env


@pytest.mark.anyio
async def test_peak_report_carries_precision_note_and_guard(tmp_path: Path) -> None:
    shutil.copytree(FIXTURES / "runs", tmp_path / "runs")
    server, _ = build_server(Config(root=tmp_path))
    async with Client(server) as client:
        run = (await _call(client, "load_run", path="runs/clean_pos.mzML"))["data"]["run_handle"]
        chrom = await _call(client, "get_chromatogram", run_handle=run, kind="EIC", mz=195.087652)
        integ = await _call(
            client, "integrate_peak", chrom_handle=chrom["data"]["chrom_handle"], apex_rt_min=4.4
        )
        ev = integ["provenance_id"]
        body = (
            f"Caffeine [M+H]+ eluted at {{{ev}:data.rt_apex_min}} min with area "
            f"{{{ev}:data.area_counts_min}} counts*min."
        )
        ok = await _call(
            client,
            "export_report",
            title="Caffeine check",
            filename="caffeine",
            sections=[{"heading": "Peak", "body": body}],
        )
        bad = await _call(
            client,
            "export_report",
            title="Caffeine check",
            filename="bad",
            sections=[{"heading": "Peak", "body": body + " Recovery was 97.2%."}],
        )
        dup = await _call(
            client,
            "export_report",
            title="x",
            filename="caffeine",
            sections=[{"heading": "Peak", "body": "No numbers."}],
        )
        slug = await _call(
            client,
            "export_report",
            title="x",
            filename="../escape",
            sections=[{"heading": "Peak", "body": "No numbers."}],
        )
    assert ok["status"] == "ok" and ok["data"]["slots_filled"] == 2
    md = (tmp_path / "simplymz_reports" / "caffeine.md").read_text()
    assert integ["data"]["area_precision"]["note"] in md  # ADR 0008 disclosure in the report
    assert (tmp_path / "simplymz_reports" / "caffeine.html").exists()
    assert bad["error"]["code"] == "INVALID_ARGUMENT" and "97.2" in bad["verdict"]
    assert not (tmp_path / "simplymz_reports" / "bad.md").exists()
    assert dup["error"]["code"] == "INVALID_ARGUMENT" and "overwrite" in dup["error"]["hint"]
    assert slug["error"]["code"] == "INVALID_ARGUMENT"
