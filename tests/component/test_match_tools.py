from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from mcp import Client

from simplymz_mcp.config import Config
from simplymz_mcp.core.envelope import is_valid_envelope
from simplymz_mcp.server import build_server
from simplymz_mcp.synth.compounds import COMPOUNDS
from simplymz_mcp.synth.fixtures import LIBRARY_COMPOUNDS, truth_path
from tests.conftest import FIXTURES

MS2 = "runs/ms2_dda.mzML.gz"


@pytest.fixture(scope="module")
def root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    r = tmp_path_factory.mktemp("data")
    shutil.copytree(FIXTURES / "runs", r / "runs")
    shutil.copytree(FIXTURES / "library", r / "library")
    return r


async def _call(client: Client, tool: str, **args: object) -> dict:
    env = (await client.call_tool(tool, args)).structured_content
    assert is_valid_envelope(env), env
    return env


async def _setup(client: Client) -> tuple[str, str]:
    run = (await _call(client, "load_run", path=MS2))["data"]["run_handle"]
    lib = (await _call(client, "load_library", path="library/synthetic_library.msp"))["data"]
    return run, lib["library_handle"]


@pytest.mark.anyio
async def test_in_library_top1_and_out_of_library_insufficient(root: Path) -> None:
    truth = json.loads(truth_path(FIXTURES / MS2).read_text())
    server, _ = build_server(Config(root=root))
    async with Client(server) as client:
        run, lib = await _setup(client)
        for c in truth["compounds"]:
            env = await _call(
                client,
                "match_spectrum",
                run_handle=run,
                precursor_mz=c["ion_mz"],
                library_handle=lib,
                rt_min=c["rt_min"],
            )
            if c["name"] in LIBRARY_COMPOUNDS:
                assert env["status"] == "ok", (c["name"], env["verdict"])
                top = env["data"]["hits"][0]
                assert top["name"] == c["name"] and top["passes"]
                assert top["licence"].startswith("CC0")
            else:
                assert env["status"] == "insufficient_evidence", c["name"]


@pytest.mark.anyio
async def test_decoy_spectra_never_pass(root: Path, tmp_path: Path) -> None:
    """Library entries with fragments moved by 5-60 Da (same precursor) must never pass."""
    rng = np.random.default_rng(7)
    blocks = []
    for name in LIBRARY_COMPOUNDS:
        c = COMPOUNDS[name]
        peaks = sorted(
            (f.mz + rng.choice([-1, 1]) * rng.uniform(5, 60), f.rel_intensity * 999)
            for f in c.fragments
        )
        blocks.append(
            "\n".join(
                [
                    f"Name: decoy_{name}",
                    f"PrecursorMZ: {c.ion_mz('[M+H]+'):.6f}",
                    "Comments: licence=CC0-1.0 (synthetic decoy)",
                    f"Num Peaks: {len(peaks)}",
                    *[f"{m:.4f} {i:.1f}" for m, i in peaks],
                ]
            )
        )
    (root / "library" / "decoys.msp").write_text("\n\n".join(blocks) + "\n")
    truth = json.loads(truth_path(FIXTURES / MS2).read_text())
    server, _ = build_server(Config(root=root))
    async with Client(server) as client:
        run = (await _call(client, "load_run", path=MS2))["data"]["run_handle"]
        lib = (await _call(client, "load_library", path="library/decoys.msp"))["data"]
        for c in truth["compounds"]:
            for method in ("cosine", "modified_cosine"):
                env = await _call(
                    client,
                    "match_spectrum",
                    run_handle=run,
                    precursor_mz=c["ion_mz"],
                    library_handle=lib["library_handle"],
                    rt_min=c["rt_min"],
                    method=method,
                )
                assert env["status"] == "insufficient_evidence", (c["name"], method, env["data"])
                assert all(not h["passes"] for h in env["data"]["hits"])


@pytest.mark.anyio
async def test_library_and_match_errors(root: Path) -> None:
    (root / "library" / "empty.msp").write_text("nothing here\n")
    server, _ = build_server(Config(root=root))
    async with Client(server) as client:
        run, lib = await _setup(client)
        e1 = await _call(client, "load_library", path="library/empty.msp")
        assert e1["error"]["code"] == "MALFORMED_FILE"
        e2 = await _call(
            client, "match_spectrum", run_handle=run, precursor_mz=999.9, library_handle=lib
        )
        assert e2["error"]["code"] == "INVALID_ARGUMENT" and "MS2" in e2["error"]["hint"]
        e3 = await _call(
            client, "match_spectrum", run_handle=run, precursor_mz=195.0877, library_handle=run
        )
        assert e3["error"]["code"] == "INVALID_ARGUMENT"


@pytest.mark.anyio
async def test_engine_disclosure_and_missing_matchms(root: Path) -> None:
    from simplymz_mcp.annotation.similarity import matchms_available

    server, _ = build_server(Config(root=root))
    async with Client(server) as client:
        run, lib = await _setup(client)
        env = await _call(
            client,
            "match_spectrum",
            run_handle=run,
            precursor_mz=195.087652,
            library_handle=lib,
            rt_min=4.4,
        )
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert "matchms" in tools["match_spectrum"].description
        note = env["limits"][1]
        assert env["data"]["parameters"]["engine"] == "builtin"
        assert "identical to matchms" in note and "not more precision" in note
        if not matchms_available():
            assert "uvx --with" in note
            err = await _call(
                client,
                "match_spectrum",
                run_handle=run,
                precursor_mz=195.087652,
                library_handle=lib,
                engine="matchms",
            )
            assert err["error"]["code"] == "INVALID_ARGUMENT"
            assert "uvx --with" in err["error"]["hint"]


@pytest.mark.anyio
async def test_matchms_engine_agrees_with_builtin(root: Path) -> None:
    pytest.importorskip("matchms")  # optional dependency (ADR 0009 amendment)
    truth = json.loads(truth_path(FIXTURES / MS2).read_text())
    server, _ = build_server(Config(root=root))
    async with Client(server) as client:
        run, lib = await _setup(client)
        for c in truth["compounds"]:
            for method in ("cosine", "modified_cosine"):
                args = dict(
                    run_handle=run,
                    precursor_mz=c["ion_mz"],
                    library_handle=lib,
                    rt_min=c["rt_min"],
                    method=method,
                )
                a = await _call(client, "match_spectrum", **args)
                b = await _call(client, "match_spectrum", engine="matchms", **args)
                assert a["status"] == b["status"]
                for ha, hb in zip(a["data"]["hits"], b["data"]["hits"], strict=True):
                    assert ha["name"] == hb["name"] and ha["score"] == hb["score"]
                    assert ha["n_matched"] == hb["n_matched"] and ha["passes"] == hb["passes"]
