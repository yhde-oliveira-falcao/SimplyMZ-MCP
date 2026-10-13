from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import anyio
import pytest
from mcp import Client

from simplymz_mcp.config import Config
from simplymz_mcp.core.budget import estimate_tokens
from simplymz_mcp.server import build_server
from simplymz_mcp.synth.fixtures import truth_path
from simplymz_mcp.tools.features import DETECT_BUDGET
from tests.conftest import FIXTURES


async def _call(client: Client, tool: str, **args: object) -> dict:
    return (await client.call_tool(tool, args)).structured_content


async def _result(client: Client, sub: dict, timeout: float = 240) -> dict:
    job = sub["data"]["job_handle"]
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        st = await _call(client, "job_status", job_handle=job)
        if st["data"]["state"] in ("done", "failed", "cancelled"):
            assert st["data"]["state"] == "done", st
            return st["data"]["result"]
        await anyio.sleep(0.1)
    raise TimeoutError(job)


@pytest.fixture(scope="module")
def root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    r = tmp_path_factory.mktemp("feat")
    shutil.copytree(FIXTURES / "runs", r / "runs")
    shutil.copytree(FIXTURES / "batch_qc", r / "batch_qc")
    return r


@pytest.mark.anyio
async def test_run_features_and_cards(root: Path) -> None:
    server, registry = build_server(Config(root=root, cache_dir=root / "c1"))
    async with Client(server) as client:
        run = (await _call(client, "load_run", path="runs/clean_pos.mzML"))["data"]["run_handle"]
        t0 = time.monotonic()
        sub = await _call(client, "detect_features", run_handle=run)
        assert time.monotonic() - t0 < 1.0 and sub["data"]["job_handle"].startswith("job:")
        res = await _result(client, sub)
        assert res["data"]["n_features"] == 12 and res["provenance_id"].startswith("ev:")
        ftab = res["data"]["ftab_handle"]
        fid = res["data"]["top_features"][0]["id"]
        card = await _call(client, "get_feature", ftab_handle=ftab, feature_id=fid)
        bad = await _call(client, "get_feature", ftab_handle=ftab, feature_id="F99999")
        neither = await _call(client, "detect_features")
    assert card["status"] == "ok" and card["data"]["isotopes"]
    assert estimate_tokens(card) <= registry.get("get_feature").budget_tokens
    assert len(card["data"]["eic"]["rt_min"]) <= 20
    assert bad["error"]["code"] == "INVALID_ARGUMENT" and "F0000" in bad["error"]["hint"]
    assert neither["error"]["code"] == "INVALID_ARGUMENT"


@pytest.mark.anyio
async def test_batch_alignment_and_restart(root: Path) -> None:
    cfg = Config(root=root, cache_dir=root / "c2")
    server, _ = build_server(cfg)
    async with Client(server) as client:
        b = await _call(client, "load_batch", sample_sheet="batch_qc/sample_sheet.csv")
        res = await _result(
            client, await _call(client, "detect_features", batch_handle=b["data"]["batch_handle"])
        )
        ftab = res["data"]["ftab_handle"]
        top = res["data"]["top_consensus"][0]["cid"]
        card = await _call(client, "get_feature", ftab_handle=ftab, feature_id=top)
    assert estimate_tokens(res) <= DETECT_BUDGET  # job result budget
    truth = json.loads(truth_path(FIXTURES / "batch_qc" / "qc_01.mzML.gz").read_text())
    assert res["data"]["n_consensus"] == len(truth["compounds"])  # 12 planted + DEHP
    assert card["data"]["n_present"] >= 9 and estimate_tokens(card) <= 800
    server.app.jobs.shutdown()  # type: ignore[attr-defined]
    server2, _ = build_server(cfg)
    async with Client(server2) as client:
        again = await _call(client, "get_feature", ftab_handle=ftab, feature_id=top)
    assert again["status"] == "ok" and again["data"]["cid"] == top
