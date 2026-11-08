from __future__ import annotations

import json
import shutil
from pathlib import Path

import anyio
import pytest
from mcp import Client

from simplymz_mcp.config import Config
from simplymz_mcp.core.budget import estimate_tokens
from simplymz_mcp.server import build_server
from simplymz_mcp.state.ftab import FeatureTables
from simplymz_mcp.synth.fixtures import DIFFERENTIAL, truth_path
from tests.conftest import FIXTURES


async def _call(client: Client, tool: str, **args: object) -> dict:
    return (await client.call_tool(tool, args)).structured_content


async def _aligned(client: Client, server: object) -> str:
    b = await _call(client, "load_batch", sample_sheet="batch_qc/sample_sheet.csv")
    sub = await _call(client, "detect_features", batch_handle=b["data"]["batch_handle"])
    job = sub["data"]["job_handle"]
    rec = await anyio.to_thread.run_sync(server.app.jobs.wait, job, 240)  # type: ignore[attr-defined]
    return rec["result"]["data"]["ftab_handle"]


def _ion(name: str) -> float:
    truth = json.loads(truth_path(FIXTURES / "batch_qc" / "a_01.mzML.gz").read_text())
    return next(c["ion_mz"] for c in truth["compounds"] if c["name"] == name)


@pytest.mark.anyio
async def test_planted_differences_ranked_and_blank_contaminant_removed(tmp_path: Path) -> None:
    shutil.copytree(FIXTURES / "batch_qc", tmp_path / "batch_qc")
    server, registry = build_server(Config(root=tmp_path))
    async with Client(server) as client:
        ftab = await _aligned(client, server)
        env = await _call(client, "compare_groups", ftab_handle=ftab, group_a="A", group_b="B")
        bad = await _call(client, "compare_groups", ftab_handle=ftab, group_a="A", group_b="Z")
    assert env["status"] == "ok", env
    top = env["data"]["ranked"]
    top_mz = [r["mz"] for r in top]
    for name, fold in DIFFERENTIAL.items():
        mz = _ion(name)
        hit = [r for r in top if abs(r["mz"] - mz) / mz * 1e6 <= 10]
        assert hit, f"{name} not in top 10"
        assert hit[0]["log2_fc"] == pytest.approx(__import__("math").log2(fold), abs=0.5)
    dehp = _ion("dehp_contaminant")
    assert all(abs(m - dehp) / dehp * 1e6 > 10 for m in top_mz)
    assert env["data"]["removed_blank"] >= 1
    assert "Small sample size (n=3 vs n=3)" in env["limits"][0]
    assert estimate_tokens(env) <= registry.get("compare_groups").budget_tokens
    assert bad["error"]["code"] == "INVALID_ARGUMENT" and "A, B" in bad["error"]["hint"]


@pytest.mark.anyio
@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("all_empty", [False, True])
async def test_empty_samples_survive_persisted_table_and_mcp(
    tmp_path: Path, legacy: bool, all_empty: bool
) -> None:
    server, _ = build_server(Config(root=tmp_path))
    app = server.app
    roster = [
        {"run": run, "sample_type": "sample", "group": group}
        for run, group in [("a1", "A"), ("a2", "A"), ("b1", "B"), ("b2", "B")]
    ]
    batch = app.store.create("batch", {"entries": [{**e, "file": e["run"]} for e in roster]})
    ftab = app.store.create("ftab", {"kind": "aligned", "batch_handle": batch})
    members = (
        []
        if all_empty
        else [
            {**e, "cid": "C1", "area": area}
            for e, area in zip(roster[:2], [100.0, 90.0], strict=True)
        ]
    )
    consensus = [] if all_empty else [{"cid": "C1", "mz": 100.0, "rt_min": 1.0}]
    meta = {"runs": [e["run"] for e in roster]}
    if not legacy:
        meta["sample_roster"] = roster
    FeatureTables(app.config.resolved_cache_dir()).save_aligned(
        ftab.replace(":", "_"), consensus, members, meta
    )
    async with Client(server) as client:
        result = await _call(client, "compare_groups", ftab_handle=ftab, group_a="A", group_b="B")
    assert result["status"] == "ok", result
    data = result["data"]
    assert data["n_a"] == data["n_b"] == 2
    assert data["empty_sample_runs"] == (["a1", "a2", "b1", "b2"] if all_empty else ["b1", "b2"])
    assert any("no detected features" in limit for limit in result["limits"])
    if not all_empty:
        assert data["ranked"][0]["imputed"] == 2
