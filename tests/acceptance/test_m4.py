"""M4 acceptance criteria (IMPLEMENTATION_PLAN.md, M4). One test per AC id."""

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
from simplymz_mcp.synth.elements import ELECTRON_MASS, ISOTOPES, isotope_pattern, monoisotopic_mass
from simplymz_mcp.synth.fixtures import LIBRARY_COMPOUNDS, truth_path
from simplymz_mcp.synth.writer import msp_text
from tests.conftest import FIXTURES
from tests.oracle.compounds import ORACLE, elements_for

pytestmark = pytest.mark.acceptance
MS2 = "runs/ms2_dda.mzML.gz"
H = ISOTOPES["H"][0][0]


@pytest.fixture(scope="module")
def root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    r = tmp_path_factory.mktemp("data")
    shutil.copytree(FIXTURES / "runs", r / "runs")
    shutil.copytree(FIXTURES / "library", r / "library")
    for name in LIBRARY_COMPOUNDS:  # leave-one-out libraries for AC4
        others = [n for n in LIBRARY_COMPOUNDS if n != name]
        (r / "library" / f"without_{name}.msp").write_text(msp_text(others))
    rng = np.random.default_rng(11)  # decoys for AC5
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
                    "Comments: licence=CC0-1.0",
                    f"Num Peaks: {len(peaks)}",
                    *[f"{m:.4f} {i:.1f}" for m, i in peaks],
                ]
            )
        )
    (r / "library" / "decoys.msp").write_text("\n\n".join(blocks) + "\n")
    return r


async def _call(client: Client, tool: str, **args: object) -> dict:
    env = (await client.call_tool(tool, args)).structured_content
    assert is_valid_envelope(env), env
    return env


def _truth() -> list[dict]:
    return json.loads(truth_path(FIXTURES / MS2).read_text())["compounds"]


@pytest.mark.anyio
async def test_M4_AC1_true_formula_in_candidates_for_all_oracle_compounds(root: Path) -> None:
    from simplymz_mcp.annotation.adducts import ADDUCTS
    from simplymz_mcp.annotation.formulas import enumerate_formulas

    server, _ = build_server(Config(root=root))
    shown_in_tool = 0
    async with Client(server) as client:
        for name, f in ORACLE.items():
            mz = monoisotopic_mass(f) + H - ELECTRON_MASS  # oracle mass, independent table
            full = enumerate_formulas(
                ADDUCTS["[M+H]+"].neutral(mz), 5.0, elements_for(f), max_candidates=10_000
            )
            assert f in [c.formula for c in full], name  # complete candidate list
            env = await _call(
                client,
                "propose_formulas",
                mz=mz,
                adduct="[M+H]+",
                mz_tol_ppm=5,
                elements=elements_for(f),
                max_candidates=20,
            )
            shown_in_tool += f in [c["formula"] for c in env["data"]["candidates"]]
    assert len(ORACLE) >= 20
    assert shown_in_tool == len(ORACLE)  # and the tool's top 20 shows it every time


@pytest.mark.anyio
async def test_M4_AC2_isotopes_rank_truth_first_for_90pct_below_400_da(root: Path) -> None:
    # (a) through the tool, on real fixture spectra
    hits = total = 0
    server, _ = build_server(Config(root=root))
    async with Client(server) as client:
        for rel in ("runs/clean_pos.mzML", "runs/clean_neg.mzML.gz", MS2):
            truth = json.loads(truth_path(FIXTURES / rel).read_text())
            run = (await _call(client, "load_run", path=rel))["data"]["run_handle"]
            for c in truth["compounds"]:
                if monoisotopic_mass(c["formula"]) >= 400:
                    continue
                env = await _call(
                    client,
                    "propose_formulas",
                    mz=c["ion_mz"],
                    adduct=c["adduct"],
                    run_handle=run,
                    rt_min=c["rt_min"],
                    elements=elements_for(c["formula"]),
                )
                total += 1
                hits += env["data"]["candidates"][0]["formula"] == c["formula"]
    assert total >= 20 and hits / total >= 0.90, (hits, total)
    # (b) on the full oracle set with simulated isotope measurements (2% noise, 1 ppm)
    from simplymz_mcp.annotation.formulas import enumerate_formulas
    from simplymz_mcp.annotation.propose import rank

    rng = np.random.default_rng(5)
    hits = total = 0
    for f in ORACLE.values():
        m = monoisotopic_mass(f)
        if m >= 400:
            continue
        total += 1
        obs = [1.0] + [a * (1 + rng.normal(0, 0.02)) for _, a in isotope_pattern(f, 3)[1:]]
        cands = enumerate_formulas(m * (1 + rng.normal(0, 1e-6)), 5.0, elements_for(f))
        hits += rank(cands, obs)[0]["formula"] == f
    assert hits / total >= 0.90, (hits, total)


@pytest.mark.anyio
async def test_M4_AC3_in_library_spectra_give_top1_and_level_2(root: Path) -> None:
    server, _ = build_server(Config(root=root))
    async with Client(server) as client:
        run = (await _call(client, "load_run", path=MS2))["data"]["run_handle"]
        lib = (await _call(client, "load_library", path="library/synthetic_library.msp"))["data"][
            "library_handle"
        ]
        n = 0
        for c in _truth():
            if c["name"] not in LIBRARY_COMPOUNDS:
                continue
            m = await _call(
                client,
                "match_spectrum",
                run_handle=run,
                precursor_mz=c["ion_mz"],
                library_handle=lib,
                rt_min=c["rt_min"],
            )
            assert m["data"]["hits"][0]["name"] == c["name"] and m["data"]["hits"][0]["passes"]
            conf = await _call(client, "assign_confidence", evidence=[m["provenance_id"]])
            assert conf["data"]["level"] == 2 and conf["data"]["identity"] == c["name"]
            n += 1
    assert n == 7


@pytest.mark.anyio
async def test_M4_AC4_out_of_library_never_gets_a_library_claim(root: Path) -> None:
    server, _ = build_server(Config(root=root))
    cases = 0
    async with Client(server) as client:
        run = (await _call(client, "load_run", path=MS2))["data"]["run_handle"]
        full = (await _call(client, "load_library", path="library/synthetic_library.msp"))["data"][
            "library_handle"
        ]
        for c in _truth():
            libs = (
                [full]
                if c["name"] not in LIBRARY_COMPOUNDS
                else [
                    (await _call(client, "load_library", path=f"library/without_{c['name']}.msp"))[
                        "data"
                    ]["library_handle"]
                ]
            )
            for lib in libs:
                form = await _call(
                    client, "propose_formulas", mz=c["ion_mz"], run_handle=run, rt_min=c["rt_min"]
                )
                m = await _call(
                    client,
                    "match_spectrum",
                    run_handle=run,
                    precursor_mz=c["ion_mz"],
                    library_handle=lib,
                    rt_min=c["rt_min"],
                )
                conf = await _call(
                    client,
                    "assign_confidence",
                    evidence=[form["provenance_id"], m["provenance_id"]],
                )
                assert m["status"] == "insufficient_evidence", c["name"]
                assert conf["data"]["level"] >= 3 and conf["data"]["identity"] is None
                cases += 1
    assert cases == 8  # kynurenine + 7 leave-one-out cases


@pytest.mark.anyio
async def test_M4_AC5_decoys_never_exceed_threshold(root: Path) -> None:
    server, _ = build_server(Config(root=root))
    async with Client(server) as client:
        run = (await _call(client, "load_run", path=MS2))["data"]["run_handle"]
        lib = (await _call(client, "load_library", path="library/decoys.msp"))["data"]
        for c in _truth():
            for method in ("cosine", "modified_cosine"):
                m = await _call(
                    client,
                    "match_spectrum",
                    run_handle=run,
                    precursor_mz=c["ion_mz"],
                    library_handle=lib["library_handle"],
                    rt_min=c["rt_min"],
                    method=method,
                )
                thr = m["data"]["parameters"]["score_threshold"]
                assert all(h["score"] < thr or not h["passes"] for h in m["data"]["hits"])
                assert all(not h["passes"] for h in m["data"]["hits"]), (c["name"], method)


@pytest.mark.anyio
async def test_M4_AC6_polarity_mismatch_names_valid_adducts(root: Path) -> None:
    server, _ = build_server(Config(root=root))
    async with Client(server) as client:
        neg = (await _call(client, "load_run", path="runs/clean_neg.mzML.gz"))["data"]
        pos = (await _call(client, "load_run", path="runs/clean_pos.mzML"))["data"]
        e1 = await _call(
            client, "propose_formulas", mz=191.0197, adduct="[M+H]+", run_handle=neg["run_handle"]
        )
        e2 = await _call(
            client, "propose_formulas", mz=195.0877, adduct="[M-H]-", run_handle=pos["run_handle"]
        )
    assert e1["error"]["code"] == e2["error"]["code"] == "POLARITY_MISMATCH"
    assert "[M-H]-" in e1["error"]["hint"] and "[M+Cl]-" in e1["error"]["hint"]
    assert "[M+H]+" in e2["error"]["hint"] and "[M+Na]+" in e2["error"]["hint"]
