from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from mcp import Client

from simplymz_mcp.config import Config
from simplymz_mcp.core.envelope import is_valid_envelope
from simplymz_mcp.server import build_server
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


async def identify(client: Client, run: str, lib: str, c: dict) -> tuple[dict, dict, dict]:
    form = await _call(
        client,
        "propose_formulas",
        mz=c["ion_mz"],
        adduct="[M+H]+",
        run_handle=run,
        rt_min=c["rt_min"],
    )
    match = await _call(
        client,
        "match_spectrum",
        run_handle=run,
        precursor_mz=c["ion_mz"],
        library_handle=lib,
        rt_min=c["rt_min"],
    )
    conf = await _call(
        client, "assign_confidence", evidence=[form["provenance_id"], match["provenance_id"]]
    )
    return form, match, conf


@pytest.mark.anyio
async def test_identification_ladder_on_ms2_fixture(root: Path) -> None:
    truth = json.loads(truth_path(FIXTURES / MS2).read_text())
    server, _ = build_server(Config(root=root))
    async with Client(server) as client:
        run = (await _call(client, "load_run", path=MS2))["data"]["run_handle"]
        lib = (await _call(client, "load_library", path="library/synthetic_library.msp"))["data"][
            "library_handle"
        ]
        for c in truth["compounds"]:
            form, _, conf = await identify(client, run, lib, c)
            assert form["data"]["isotope_data"]
            consistent = [x["formula"] for x in form["data"]["candidates"] if not x["rejected"]]
            assert c["formula"] in consistent, c["name"]
            assert conf["status"] == "ok"
            if c["name"] in LIBRARY_COMPOUNDS:
                assert conf["data"]["level"] == 2 and conf["data"]["identity"] == c["name"]
            else:  # kynurenine: never a library claim
                assert conf["data"]["level"] >= 3 and conf["data"]["identity"] is None
            assert "Level 1" in conf["limits"][0]


@pytest.mark.anyio
async def test_identification_errors(root: Path) -> None:
    server, _ = build_server(Config(root=root))
    async with Client(server) as client:
        neg = (await _call(client, "load_run", path="runs/clean_neg.mzML.gz"))["data"]
        e1 = await _call(
            client, "propose_formulas", mz=191.0197, adduct="[M+H]+", run_handle=neg["run_handle"]
        )
        assert e1["error"]["code"] == "POLARITY_MISMATCH" and "[M-H]-" in e1["error"]["hint"]
        f1 = await _call(client, "propose_formulas", mz=195.087652)
        f2 = await _call(client, "propose_formulas", mz=166.086255)
        assert f1["status"] == "ok" and not f1["data"]["isotope_data"]
        mixed = await _call(
            client, "assign_confidence", evidence=[f1["provenance_id"], f2["provenance_id"]]
        )
        assert mixed["error"]["code"] == "INVALID_ARGUMENT"
        info = await _call(client, "server_info")
        wrong = await _call(client, "assign_confidence", evidence=[info["provenance_id"]])
        assert wrong["error"]["code"] == "INVALID_ARGUMENT"
        missing = await _call(
            client, "assign_confidence", evidence=["ev:01ARZ3NDEKTSV4RRFFQ69G5FAV"]
        )
        assert missing["error"]["code"] == "UNKNOWN_HANDLE"
        forged = await client.call_tool(
            "assign_confidence", {"evidence": [f1["provenance_id"]], "level": 1}
        )
        assert forged.is_error and "level" in forged.content[0].text
