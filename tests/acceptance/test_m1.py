"""M1 acceptance criteria (IMPLEMENTATION_PLAN.md, M1). One test per AC id."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest
from mcp import Client

from simplymz_mcp.config import Config
from simplymz_mcp.core.budget import estimate_tokens
from simplymz_mcp.core.envelope import is_valid_envelope
from simplymz_mcp.server import build_server
from simplymz_mcp.synth.fixtures import truth_path
from tests.conftest import FIXTURES
from tests.helpers import RawStdioSession

pytestmark = pytest.mark.acceptance
MZML = sorted(p for p in FIXTURES.rglob("*") if p.name.endswith((".mzML", ".mzML.gz")))


@pytest.fixture(scope="module")
def root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    r = tmp_path_factory.mktemp("data")
    for p in MZML:
        dest = r / p.relative_to(FIXTURES)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(p, dest)
    data = (FIXTURES / "runs" / "clean_pos.mzML").read_bytes()
    (r / "truncated.mzML").write_bytes(data[: len(data) // 3])
    (r / "secret_outside.mzML").write_text("x")
    return r


async def _call(client: Client, tool: str, **args: object) -> dict:
    env = (await client.call_tool(tool, args)).structured_content
    assert is_valid_envelope(env), env
    return env


def _rel(p: Path) -> str:
    return str(p.relative_to(FIXTURES))


@pytest.mark.anyio
async def test_M1_AC1_all_fixtures_load_and_bad_files_fail_instructively(root: Path) -> None:
    server, _ = build_server(Config(root=root))
    async with Client(server) as client:
        for p in MZML:
            env = await _call(client, "load_run", path=_rel(p))
            assert env["status"] == "ok", (p.name, env)
        for path, code in [
            ("truncated.mzML", "MALFORMED_FILE"),
            ("run.raw", "VENDOR_FORMAT"),
            ("run.d", "VENDOR_FORMAT"),
            ("x.wiff", "VENDOR_FORMAT"),
        ]:
            env = await _call(client, "load_run", path=path)
            assert env["error"]["code"] == code and env["error"]["hint"]
            if code == "VENDOR_FORMAT":
                assert "msconvert" in env["error"]["hint"]


@pytest.mark.anyio
async def test_M1_AC2_run_card_budget_and_dropout_flagging(root: Path) -> None:
    server, registry = build_server(Config(root=root))
    async with Client(server) as client:
        for p in MZML:
            run = (await _call(client, "load_run", path=_rel(p)))["data"]["run_handle"]
            card = await _call(client, "run_card", run_handle=run)
            assert estimate_tokens(card) <= 1500 and not card["truncated"]
            n = card["data"]["n_anomalies"]
            if p.name.startswith("dropout"):
                assert [a["type"] for a in card["data"]["anomalies"]] == ["empty_scans"]
            else:
                assert n == 0, (p.name, card["data"]["anomalies"])
    assert registry.get("run_card").budget_tokens == 1500


def _eic_files() -> list[Path]:
    # dropout.mzML.gz is excluded: its injected 12-scan gap removes caffeine's apex by design.
    return [p for p in MZML if not p.name.startswith("dropout")]


@pytest.mark.anyio
async def test_M1_AC3_eic_apex_within_one_scan_for_every_planted_compound(root: Path) -> None:
    server, _ = build_server(Config(root=root))
    checked = 0
    async with Client(server) as client:
        for p in _eic_files():
            truth = json.loads(truth_path(p).read_text())
            run = (await _call(client, "load_run", path=_rel(p)))["data"]["run_handle"]
            for c in truth["compounds"]:
                env = await _call(
                    client,
                    "get_chromatogram",
                    run_handle=run,
                    kind="EIC",
                    mz=c["ion_mz"],
                    mz_tol_ppm=15,
                )
                top = max(env["data"]["peaks"], key=lambda q: q["height_counts"])
                assert abs(top["rt_min"] - c["rt_min"]) <= truth["scan_interval_min"] + 1e-6, (
                    p.name,
                    c["name"],
                    top["rt_min"],
                    c["rt_min"],
                )
                checked += 1
    assert checked >= 200


@pytest.mark.anyio
async def test_M1_AC4_areas_within_3pct_of_analytic_truth(root: Path) -> None:
    files = [
        FIXTURES / "runs" / "clean_pos.mzML",
        FIXTURES / "runs" / "clean_neg.mzML.gz",
        *sorted((FIXTURES / "batch_qc").glob("qc_*.mzML.gz")),
    ]
    server, _ = build_server(Config(root=root))
    async with Client(server) as client:
        for p in files:
            truth = json.loads(truth_path(p).read_text())
            run = (await _call(client, "load_run", path=_rel(p)))["data"]["run_handle"]
            rt_end = truth["rt_range_min"][1]
            # Oracle condition: the analytic area is the measurable area only if the whole
            # peak (+/- 4 sigma) was acquired. DEHP at 9.8 min is cut by the 10 min run end.
            inside = [
                c
                for c in truth["compounds"]
                if c["role"] == "planted"
                and c["rt_min"] + 4 * c["sigma_min"] <= rt_end
                and c["rt_min"] - 4 * c["sigma_min"] >= truth["rt_range_min"][0]
            ]
            assert len(inside) >= 5
            for c in inside:
                chrom = await _call(
                    client,
                    "get_chromatogram",
                    run_handle=run,
                    kind="EIC",
                    mz=c["ion_mz"],
                    mz_tol_ppm=10,
                )
                env = await _call(
                    client,
                    "integrate_peak",
                    chrom_handle=chrom["data"]["chrom_handle"],
                    apex_rt_min=c["rt_min"],
                )
                d = env["data"]
                # SNR >= 50 condition: synthetic EICs have zero noise (SNR undefined = infinite)
                assert d["snr"] is None or d["snr"] >= 50
                assert d["area_counts_min"] == pytest.approx(c["area_counts_min"], rel=0.03), (
                    p.name,
                    c["name"],
                )


def test_M1_AC5_handles_survive_server_restart(root: Path, tmp_path: Path) -> None:
    cache = ["--cache-dir", str(tmp_path / "cache")]
    s1 = RawStdioSession(root, cache)
    try:
        s1.initialize()
        r = s1.request(
            "tools/call", {"name": "load_run", "arguments": {"path": "runs/ms2_dda.mzML.gz"}}
        )
        run = r["result"]["structuredContent"]["data"]["run_handle"]
        assert r["result"]["structuredContent"]["data"]["cache_hit"] is False
        c = s1.request(
            "tools/call",
            {
                "name": "get_chromatogram",
                "arguments": {"run_handle": run, "kind": "EIC", "mz": 195.087652},
            },
        )
        chrom = c["result"]["structuredContent"]["data"]["chrom_handle"]
    finally:
        s1.close()
    s2 = RawStdioSession(root, cache)  # a brand-new process
    try:
        s2.initialize()
        card = s2.request("tools/call", {"name": "run_card", "arguments": {"run_handle": run}})
        assert card["result"]["structuredContent"]["status"] == "ok"
        integ = s2.request(
            "tools/call", {"name": "integrate_peak", "arguments": {"chrom_handle": chrom}}
        )
        assert integ["result"]["structuredContent"]["status"] == "ok"
        again = s2.request(
            "tools/call", {"name": "load_run", "arguments": {"path": "runs/ms2_dda.mzML.gz"}}
        )
        data = again["result"]["structuredContent"]["data"]
        assert data["run_handle"] == run and data["cache_hit"] is True
    finally:
        s2.close()


@pytest.mark.anyio
async def test_M1_AC6_one_immutable_ledger_entry_per_tool_call(root: Path) -> None:
    server, _ = build_server(Config(root=root, cache_dir=root / "ac6_cache"))
    ledger = server.app.ledger  # type: ignore[attr-defined]
    ids = []
    async with Client(server) as client:
        run = await _call(client, "load_run", path="runs/clean_pos.mzML")
        ids.append(run["provenance_id"])
        h = run["data"]["run_handle"]
        calls = [
            ("server_info", {}),
            ("run_card", {"run_handle": h}),
            ("get_chromatogram", {"run_handle": h, "kind": "TIC"}),
        ]
        for tool, args in calls:
            ids.append((await _call(client, tool, **args))["provenance_id"])
        err = await _call(client, "load_run", path="nope.mzML")
        assert err["provenance_id"] is None  # errors are not evidence
    assert ledger.ids() == ids and len(set(ids)) == len(ids)
    for ev in ids:
        assert ledger.get(ev)["result"]["status"] in ("ok", "insufficient_evidence")
    db = sqlite3.connect(root / "ac6_cache" / "state.sqlite")
    for sql in ("UPDATE ledger SET op = 'forged'", "DELETE FROM ledger"):
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(sql)
    assert ledger.count() == len(ids)


@pytest.mark.anyio
async def test_M1_AC7_path_traversal_and_symlink_escape_blocked(root: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.mzML"
    shutil.copy(FIXTURES / "runs" / "clean_pos.mzML", outside)
    sub = root / "links"
    sub.mkdir(exist_ok=True)
    can_link = sys.platform != "win32"
    if can_link:
        os.symlink(outside, sub / "escape.mzML")
        os.symlink(tmp_path, sub / "escape_dir")
    server, _ = build_server(Config(root=root))
    async with Client(server) as client:
        attempts = ["../outside.mzML", str(outside), "runs/../../outside.mzML"]
        if can_link:
            attempts += ["links/escape.mzML", "links/escape_dir/outside.mzML"]
        for a in attempts:
            env = await _call(client, "load_run", path=a)
            assert env["error"]["code"] == "PATH_OUTSIDE_ROOT", a
