"""Contract tests: every registered tool, called with its example input over MCP."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
from mcp import Client

from simplymz_mcp.config import Config
from simplymz_mcp.core.budget import estimate_tokens
from simplymz_mcp.core.envelope import is_valid_envelope
from simplymz_mcp.server import build_server
from tests.conftest import FIXTURES

LAST = ("release_handle",)  # run after the tools that need the handle


def _fill(example: dict[str, Any], handles: dict[str, str]) -> dict[str, Any]:
    def fill(v: Any) -> Any:
        if isinstance(v, str):
            return handles.get(v, v)
        if isinstance(v, list):
            return [fill(x) for x in v]
        return v

    return {k: fill(v) for k, v in example.items()}


@pytest.mark.anyio
async def test_every_tool_honours_contract(tmp_path: Path) -> None:
    shutil.copytree(FIXTURES / "runs", tmp_path / "runs")
    shutil.copytree(FIXTURES / "batch_qc", tmp_path / "batch_qc")
    shutil.copytree(FIXTURES / "library", tmp_path / "library")
    server, registry = build_server(Config(root=tmp_path))
    async with Client(server) as client:
        listed = {t.name: t for t in (await client.list_tools()).tools}
        assert set(listed) == set(registry.names())
        loaded = await client.call_tool("load_run", {"path": "runs/clean_pos.mzML"})
        run = loaded.structured_content["data"]["run_handle"]
        chrom = await client.call_tool(
            "get_chromatogram", {"run_handle": run, "kind": "EIC", "mz": 195.087652}
        )
        batch = await client.call_tool("load_batch", {"sample_sheet": "batch_qc/sample_sheet.csv"})
        job = server.app.jobs.submit("contract", {}, lambda ctx: {"ok": True})  # type: ignore[attr-defined]
        server.app.jobs.wait(job)  # type: ignore[attr-defined]
        det = await client.call_tool("detect_features", {"run_handle": run})
        det_job = det.structured_content["data"]["job_handle"]
        ftab = server.app.jobs.wait(det_job, 120)["result"]["data"]["ftab_handle"]  # type: ignore[attr-defined]
        bdet = await client.call_tool(
            "detect_features",
            {"batch_handle": batch.structured_content["data"]["batch_handle"]},
        )
        aftab = server.app.jobs.wait(  # type: ignore[attr-defined]
            bdet.structured_content["data"]["job_handle"], 240
        )["result"]["data"]["ftab_handle"]
        handles = {
            "<aftab>": aftab,
            "<ftab>": ftab,
            "<job>": job,
            "<run>": run,
            "<chrom>": chrom.structured_content["data"]["chrom_handle"],
            "<batch>": batch.structured_content["data"]["batch_handle"],
        }
        ms2 = await client.call_tool("load_run", {"path": "runs/ms2_dda.mzML.gz"})
        lib = await client.call_tool("load_library", {"path": "library/synthetic_library.msp"})
        handles["<ms2run>"] = ms2.structured_content["data"]["run_handle"]
        handles["<lib>"] = lib.structured_content["data"]["library_handle"]
        ev = await client.call_tool("propose_formulas", {"mz": 195.087652})
        handles["<ev>"] = ev.structured_content["provenance_id"]
        ordered = sorted(registry.specs(), key=lambda s: s.name in LAST)
        for spec in ordered:
            tool = listed[spec.name]
            assert tool.description and tool.description.strip(), spec.name
            assert tool.input_schema["type"] == "object"
            assert tool.output_schema is not None
            res = await client.call_tool(spec.name, _fill(spec.example_input, handles))
            env = res.structured_content
            assert is_valid_envelope(env), spec.name
            assert env["status"] != "error", (spec.name, env)
            within = estimate_tokens(env) <= spec.budget_tokens
            assert within or env["truncated"], f"{spec.name} over budget without truncation"


def test_every_tool_has_a_positive_budget(tmp_path: Path) -> None:
    _, registry = build_server(Config(root=tmp_path))
    assert registry.specs(), "no tools registered"
    for spec in registry.specs():
        assert 0 < spec.budget_tokens <= 4000, spec.name
