"""M2.T6: prompts render, and the tool sequence each prompt lists actually runs."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
from mcp import Client

from simplymz_mcp.config import Config
from simplymz_mcp.server import build_server
from tests.conftest import FIXTURES

pytestmark = pytest.mark.e2e


def _steps(text: str) -> list[str]:
    block = text.split("Steps:", 1)[1].split("\n\n", 1)[0]
    return re.findall(r"^\d+\. (\w+)\(", block, flags=re.M)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    shutil.copytree(FIXTURES / "batch_qc", tmp_path / "batch_qc")
    shutil.copytree(FIXTURES / "runs", tmp_path / "runs")
    return tmp_path


async def _text(client: Client, name: str, args: dict[str, str]) -> str:
    res = await client.get_prompt(name, args)
    return "\n".join(m.content.text for m in res.messages)


@pytest.mark.anyio
async def test_prompts_listed_and_reference_real_tools(root: Path) -> None:
    server, registry = build_server(Config(root=root))
    async with Client(server) as client:
        names = {p.name for p in (await client.list_prompts()).prompts}
        assert {"qc_batch", "explain_chromatogram", "compare_groups"} <= names
        cg = await _text(
            client,
            "compare_groups",
            {"sample_sheet": "batch_qc/sample_sheet.csv", "group_a": "A", "group_b": "B"},
        )
        qc = await _text(client, "qc_batch", {"sample_sheet": "batch_qc/sample_sheet.csv"})
        ex = await _text(
            client, "explain_chromatogram", {"path": "runs/clean_pos.mzML", "mz": "195.0877"}
        )
    assert _steps(cg) == [
        "load_batch",
        "qc_batch",
        "detect_features",
        "job_status",
        "compare_groups",
        "get_feature",
    ]
    assert "small-sample caveat" in cg
    for text in (qc, ex, cg):
        assert "insufficient_evidence" in text and "limits" in text
        assert set(_steps(text)) <= set(registry.names())
    assert _steps(qc) == ["load_batch", "qc_batch", "run_card"]
    assert 'kind="EIC", mz=195.0877' in ex


@pytest.mark.anyio
async def test_qc_prompt_sequence_runs(root: Path) -> None:
    server, _ = build_server(Config(root=root))
    async with Client(server) as client:
        text = await _text(client, "qc_batch", {"sample_sheet": "batch_qc/sample_sheet.csv"})
        assert _steps(text)[0] == "load_batch"
        b = (
            await client.call_tool("load_batch", {"sample_sheet": "batch_qc/sample_sheet.csv"})
        ).structured_content
        qc = (
            await client.call_tool("qc_batch", {"batch_handle": b["data"]["batch_handle"]})
        ).structured_content
        assert qc["status"] == "ok"
        entries = server.app.store.get(b["data"]["batch_handle"])["entries"]  # type: ignore[attr-defined]
        card = (
            await client.call_tool("run_card", {"run_handle": entries[0]["run_handle"]})
        ).structured_content
        assert card["status"] == "ok"


@pytest.mark.anyio
async def test_explain_prompt_sequence_runs(root: Path) -> None:
    server, _ = build_server(Config(root=root))
    async with Client(server) as client:
        r = (await client.call_tool("load_run", {"path": "runs/clean_pos.mzML"})).structured_content
        h = r["data"]["run_handle"]
        assert (await client.call_tool("run_card", {"run_handle": h})).structured_content[
            "status"
        ] == "ok"
        c = (
            await client.call_tool("get_chromatogram", {"run_handle": h, "kind": "TIC"})
        ).structured_content
        top = max(c["data"]["peaks"], key=lambda p: p["height_counts"])
        i = (
            await client.call_tool(
                "integrate_peak",
                {"chrom_handle": c["data"]["chrom_handle"], "apex_rt_min": top["rt_min"]},
            )
        ).structured_content
        assert i["status"] == "ok"


@pytest.mark.anyio
async def test_compare_prompt_sequence_runs(root: Path) -> None:
    import anyio

    server, _ = build_server(Config(root=root))
    async with Client(server) as client:
        b = (
            await client.call_tool("load_batch", {"sample_sheet": "batch_qc/sample_sheet.csv"})
        ).structured_content
        h = b["data"]["batch_handle"]
        assert (await client.call_tool("qc_batch", {"batch_handle": h})).structured_content[
            "status"
        ] == "ok"
        sub = (await client.call_tool("detect_features", {"batch_handle": h})).structured_content
        rec = await anyio.to_thread.run_sync(server.app.jobs.wait, sub["data"]["job_handle"], 240)  # type: ignore[attr-defined]
        st = (
            await client.call_tool("job_status", {"job_handle": sub["data"]["job_handle"]})
        ).structured_content
        assert st["data"]["state"] == rec["state"] == "done"
        ftab = st["data"]["result"]["data"]["ftab_handle"]
        cmp = (
            await client.call_tool(
                "compare_groups", {"ftab_handle": ftab, "group_a": "A", "group_b": "B"}
            )
        ).structured_content
        cid = cmp["data"]["ranked"][0]["cid"]
        card = (
            await client.call_tool("get_feature", {"ftab_handle": ftab, "feature_id": cid})
        ).structured_content
        assert card["status"] == "ok"


@pytest.mark.anyio
async def test_identify_prompt_references_real_tools(root: Path) -> None:
    server, registry = build_server(Config(root=root))
    async with Client(server) as client:
        text = await _text(
            client,
            "identify_peak",
            {
                "path": "runs/ms2_dda.mzML.gz",
                "mz": "195.0877",
                "rt_min": "4.4",
                "library": "library/x.msp",
            },
        )
        bare = await _text(
            client,
            "identify_peak",
            {"path": "runs/ms2_dda.mzML.gz", "mz": "195.0877", "rt_min": "4.4"},
        )
    assert _steps(text) == [
        "load_run",
        "run_card",
        "propose_formulas",
        "load_library",
        "match_spectrum",
        "assign_confidence",
    ]
    assert _steps(bare)[-1] == "assign_confidence" and "load_library" not in _steps(bare)
    assert set(_steps(text)) <= set(registry.names())
    assert "never raise the level" in text
