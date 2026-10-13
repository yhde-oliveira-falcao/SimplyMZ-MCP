"""M3 acceptance criteria (IMPLEMENTATION_PLAN.md, M3). One test per AC id."""

from __future__ import annotations

import json
import math
import shutil
import time
from pathlib import Path

import anyio
import pytest
from mcp import Client

from simplymz_mcp.analytics.features import detect_features
from simplymz_mcp.config import Config
from simplymz_mcp.io.mzml import read_mzml
from simplymz_mcp.server import build_server
from simplymz_mcp.synth.fixtures import DIFFERENTIAL, truth_path
from tests.conftest import FIXTURES
from tests.helpers import measurable_truth, score_features

pytestmark = pytest.mark.acceptance


def _ion(name: str) -> float:
    truth = json.loads(truth_path(FIXTURES / "batch_qc" / "a_01.mzML.gz").read_text())
    return next(c["ion_mz"] for c in truth["compounds"] if c["name"] == name)


@pytest.fixture(scope="module")
def comparison(tmp_path_factory: pytest.TempPathFactory) -> dict:
    root = tmp_path_factory.mktemp("m3")
    shutil.copytree(FIXTURES / "batch_qc", root / "batch_qc")

    async def go() -> dict:
        server, _ = build_server(Config(root=root))
        async with Client(server) as client:
            b = await client.call_tool("load_batch", {"sample_sheet": "batch_qc/sample_sheet.csv"})
            sub = await client.call_tool(
                "detect_features", {"batch_handle": b.structured_content["data"]["batch_handle"]}
            )
            rec = await anyio.to_thread.run_sync(
                server.app.jobs.wait, sub.structured_content["data"]["job_handle"], 300
            )  # type: ignore[attr-defined]
            ftab = rec["result"]["data"]["ftab_handle"]
            r = await client.call_tool(
                "compare_groups", {"ftab_handle": ftab, "group_a": "A", "group_b": "B"}
            )
        return r.structured_content

    return anyio.run(go)


def test_M3_AC1_all_planted_differential_compounds_in_top_10(comparison: dict) -> None:
    top = comparison["data"]["ranked"][:10]
    for name, fold in DIFFERENTIAL.items():
        mz = _ion(name)
        hits = [r for r in top if abs(r["mz"] - mz) / mz * 1e6 <= 10]
        assert hits, f"{name} missing from top 10"
        assert math.copysign(1, hits[0]["log2_fc"]) == math.copysign(1, math.log2(fold))


def test_M3_AC2_blank_contaminants_absent_from_ranked_list(comparison: dict) -> None:
    dehp = _ion("dehp_contaminant")  # present in blanks at sample level (system background)
    assert all(abs(r["mz"] - dehp) / dehp * 1e6 > 10 for r in comparison["data"]["ranked"])
    assert comparison["data"]["removed_blank"] >= 1


def test_M3_AC3_feature_detection_recall_and_precision() -> None:
    tp = n_truth = good = n_mono = 0
    for p in sorted(x for x in FIXTURES.rglob("*") if x.name.endswith((".mzML", ".mzML.gz"))):
        truth = measurable_truth(json.loads(truth_path(p).read_text()))
        matched, g, m = score_features(detect_features(read_mzml(p))["features"], truth)
        tp += len(matched)
        n_truth += len(truth["compounds"])
        good += g
        n_mono += m
    recall, precision = tp / n_truth, good / n_mono
    assert recall >= 0.95, recall
    assert precision >= 0.90, precision


def test_M3_AC4_long_jobs_return_fast_complete_and_survive_restart(tmp_path: Path) -> None:
    shutil.copytree(FIXTURES / "batch_qc", tmp_path / "batch_qc")
    cfg = Config(root=tmp_path, cache_dir=tmp_path / "cache")

    async def first() -> tuple[str, float]:
        server, _ = build_server(cfg)
        async with Client(server) as client:
            b = await client.call_tool("load_batch", {"sample_sheet": "batch_qc/sample_sheet.csv"})
            t0 = time.monotonic()
            sub = await client.call_tool(
                "detect_features", {"batch_handle": b.structured_content["data"]["batch_handle"]}
            )
            elapsed = time.monotonic() - t0
            job = sub.structured_content["data"]["job_handle"]
            rec = await anyio.to_thread.run_sync(server.app.jobs.wait, job, 300)  # type: ignore[attr-defined]
            assert rec["state"] == "done"
        server.app.jobs.shutdown()  # type: ignore[attr-defined]
        return job, elapsed

    job, elapsed = anyio.run(first)
    assert elapsed < 1.0

    async def second() -> dict:
        server, _ = build_server(cfg)  # restart
        async with Client(server) as client:
            st = await client.call_tool("job_status", {"job_handle": job})
            ftab = st.structured_content["data"]["result"]["data"]["ftab_handle"]
            r = await client.call_tool(
                "compare_groups", {"ftab_handle": ftab, "group_a": "A", "group_b": "B"}
            )
        return r.structured_content

    assert anyio.run(second)["status"] == "ok"


def test_M3_AC5_small_sample_caveat_with_three_per_group(comparison: dict) -> None:
    assert comparison["data"]["n_a"] == comparison["data"]["n_b"] == 3
    assert any(lim.startswith("Small sample size (n=3 vs n=3)") for lim in comparison["limits"])
