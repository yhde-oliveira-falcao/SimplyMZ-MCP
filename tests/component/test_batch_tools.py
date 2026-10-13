from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from mcp import Client

from simplymz_mcp.config import Config
from simplymz_mcp.core.envelope import is_valid_envelope
from simplymz_mcp.server import build_server
from tests.conftest import FIXTURES


@pytest.fixture
def root(tmp_path: Path) -> Path:
    shutil.copytree(FIXTURES / "batch_qc", tmp_path / "batch_qc")
    shutil.copytree(FIXTURES / "runs", tmp_path / "runs")
    return tmp_path


async def _call(client: Client, tool: str, **args: object) -> dict:
    env = (await client.call_tool(tool, args)).structured_content
    assert is_valid_envelope(env), env
    return env


@pytest.mark.anyio
async def test_load_fixture_batch(root: Path) -> None:
    server, _ = build_server(Config(root=root))
    async with Client(server) as client:
        env = await _call(client, "load_batch", sample_sheet="batch_qc/sample_sheet.csv")
    assert env["status"] == "ok"
    d = env["data"]
    assert d["n_runs"] == 11 and d["counts"] == {"blank": 2, "qc": 3, "sample": 6}
    assert d["groups"] == ["A", "B"] and d["warnings"] == []
    assert [r["injection_order"] for r in d["runs"]] == list(range(1, 12))


@pytest.mark.anyio
async def test_batch_errors_are_instructive(root: Path) -> None:
    (root / "batch_qc" / "bad.csv").write_text(
        "file,sample_type,group,injection_order\nmissing.mzML,sample,A,1\n"
    )
    (root / "batch_qc" / "notes.txt").write_text("x")
    (root / "mixed.csv").write_text(
        "file,sample_type,group,injection_order\nruns/clean_pos.mzML,sample,A,1\n"
        "runs/clean_neg.mzML.gz,sample,A,2\n"
    )
    server, _ = build_server(Config(root=root))
    async with Client(server) as client:
        miss = await _call(client, "load_batch", sample_sheet="batch_qc/bad.csv")
        assert miss["error"]["code"] == "FILE_NOT_FOUND" and "relative" in miss["error"]["hint"]
        txt = await _call(client, "load_batch", sample_sheet="batch_qc/notes.txt")
        assert txt["error"]["code"] == "UNSUPPORTED_FORMAT"
        mixed = await _call(client, "load_batch", sample_sheet="mixed.csv")
        assert mixed["error"]["code"] == "POLARITY_MISMATCH"


@pytest.mark.anyio
async def test_qc_batch_clean_fixture_passes_within_budget(root: Path) -> None:
    from simplymz_mcp.core.budget import estimate_tokens

    server, registry = build_server(Config(root=root))
    async with Client(server) as client:
        b = await _call(client, "load_batch", sample_sheet="batch_qc/sample_sheet.csv")
        h = b["data"]["batch_handle"]
        qc = await _call(client, "qc_batch", batch_handle=h)
        res = await client.read_resource(f"simplymz://batch/{h.split(':')[1]}/qc")
        bad = await _call(
            client,
            "qc_batch",
            batch_handle=h,
            thresholds={"rt_drift_min": {"warn": 1, "fail": 0.5}},
        )
        tgt = await _call(
            client,
            "qc_batch",
            batch_handle=h,
            targets=[{"mz": 195.087652, "rt_min": 4.4}, {"mz": 166.086255, "rt_min": 5.1}],
        )
    assert qc["status"] == "ok" and qc["data"]["overall"] == "pass", qc["data"]["metrics"]
    assert "PASSES" in qc["verdict"]
    assert estimate_tokens(qc) <= registry.get("qc_batch").budget_tokens
    assert json.loads(res.contents[0].text)["data"]["overall"] == "pass"
    assert bad["error"]["code"] == "INVALID_ARGUMENT"
    assert tgt["data"]["reference_mode"] == "user targets"
    assert tgt["data"]["metrics"]["mass_error_ppm"]["value"] < 2.0  # absolute accuracy


@pytest.mark.anyio
async def test_qc_batch_without_qcs_is_insufficient(root: Path) -> None:
    (root / "batch_qc" / "noqc.csv").write_text(
        "file,sample_type,group,injection_order\nblank_01.mzML.gz,blank,,1\n"
        "a_01.mzML.gz,sample,A,2\nb_01.mzML.gz,sample,B,3\n"
    )
    server, _ = build_server(Config(root=root))
    async with Client(server) as client:
        b = await _call(client, "load_batch", sample_sheet="batch_qc/noqc.csv")
        qc = await _call(client, "qc_batch", batch_handle=b["data"]["batch_handle"])
    assert qc["status"] == "insufficient_evidence"
    assert qc["data"]["metrics"]["tic_cv_qc_pct"]["verdict"] == "not_applicable"
