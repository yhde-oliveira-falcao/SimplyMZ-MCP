from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from mcp import Client

from simplymz_mcp.config import Config
from simplymz_mcp.core.budget import estimate_tokens
from simplymz_mcp.core.envelope import is_valid_envelope
from simplymz_mcp.server import build_server
from simplymz_mcp.synth.fixtures import truth_path
from tests.conftest import FIXTURES

CLEAN = ["runs/clean_pos.mzML", "runs/clean_neg.mzML.gz"]


@pytest.fixture(scope="module")
def root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    r = tmp_path_factory.mktemp("data")
    shutil.copytree(FIXTURES / "runs", r / "runs")
    return r


async def _call(client: Client, tool: str, **args: object) -> dict:
    env = (await client.call_tool(tool, args)).structured_content
    assert is_valid_envelope(env), env
    return env


@pytest.mark.anyio
@pytest.mark.parametrize("rel", CLEAN)
async def test_eic_and_integration_match_truth(root: Path, rel: str) -> None:
    truth = json.loads(truth_path(FIXTURES / rel).read_text())
    server, registry = build_server(Config(root=root))
    async with Client(server) as client:
        run = (await _call(client, "load_run", path=rel))["data"]["run_handle"]
        for c in truth["compounds"]:
            chrom = await _call(
                client,
                "get_chromatogram",
                run_handle=run,
                kind="EIC",
                mz=c["ion_mz"],
                mz_tol_ppm=10,
            )
            assert chrom["status"] == "ok"
            assert estimate_tokens(chrom) <= registry.get("get_chromatogram").budget_tokens
            top = max(chrom["data"]["peaks"], key=lambda p: p["height_counts"])
            assert abs(top["rt_min"] - c["rt_min"]) <= truth["scan_interval_min"] + 1e-9
            integ = await _call(
                client,
                "integrate_peak",
                chrom_handle=chrom["data"]["chrom_handle"],
                apex_rt_min=top["rt_min"],
            )
            assert integ["status"] == "ok", integ
            area = integ["data"]["area_counts_min"]
            assert area == pytest.approx(c["area_counts_min"], rel=0.03), c["name"]
            assert integ["provenance_id"].startswith("ev:")


@pytest.mark.anyio
async def test_absent_ion_is_insufficient_evidence_and_errors(root: Path) -> None:
    server, _ = build_server(Config(root=root))
    async with Client(server) as client:
        run = (await _call(client, "load_run", path="runs/clean_pos.mzML"))["data"]["run_handle"]
        none = await _call(client, "get_chromatogram", run_handle=run, kind="EIC", mz=777.7777)
        assert none["status"] == "insufficient_evidence"
        assert any("polarity" in lim for lim in none["limits"])
        no_mz = await _call(client, "get_chromatogram", run_handle=run, kind="EIC")
        assert no_mz["error"]["code"] == "INVALID_ARGUMENT"
        bad_tol = await _call(
            client, "get_chromatogram", run_handle=run, kind="EIC", mz=195.08, mz_tol_ppm=0
        )
        assert bad_tol["error"]["code"] == "INVALID_ARGUMENT"
        tic = await _call(client, "get_chromatogram", run_handle=run, kind="TIC")
        assert tic["status"] == "ok" and len(tic["data"]["trace"]["rt_min"]) <= 50
        half = await _call(
            client, "integrate_peak", chrom_handle=tic["data"]["chrom_handle"], rt_start_min=1.0
        )
        assert half["error"]["code"] == "INVALID_ARGUMENT"
        wrong = await _call(client, "integrate_peak", chrom_handle=run)
        assert wrong["error"]["code"] == "INVALID_ARGUMENT"


@pytest.mark.anyio
async def test_integrate_peak_discloses_precision_to_the_client(root: Path) -> None:
    server, _ = build_server(Config(root=root))
    async with Client(server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert "RMS noise" in tools["integrate_peak"].description
        assert "1 in 20" in tools["integrate_peak"].description
        run = (await _call(client, "load_run", path="runs/clean_pos.mzML"))["data"]["run_handle"]
        chrom = await _call(client, "get_chromatogram", run_handle=run, kind="EIC", mz=195.087652)
        env = await _call(client, "integrate_peak", chrom_handle=chrom["data"]["chrom_handle"])
    assert env["limits"][0] == env["data"]["area_precision"]["note"]
    assert "RMS noise" in env["limits"][0]
    assert (
        "area precision" in env["verdict"]
        or "area expected" in env["verdict"]
        or "area ~1.5%" in env["verdict"]
    )
