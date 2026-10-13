"""M5 acceptance criteria (IMPLEMENTATION_PLAN.md, M5). One test per AC id.

Parts that need a human or external system are gate human-checks, not tests: the LLM
evaluation table (needs an API key) and the TestPyPI install on three OSes (needs CI).
"""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path

import pytest
from mcp import Client

from simplymz_mcp.config import Config
from simplymz_mcp.report.builder import narrative_numbers, numbers_in, traceable
from simplymz_mcp.server import build_server
from tests.conftest import FIXTURES, REPO

pytestmark = pytest.mark.acceptance


async def _call(client: Client, tool: str, **args: object) -> dict:
    return (await client.call_tool(tool, args)).structured_content


@pytest.mark.anyio
async def test_M5_AC1_untraceable_numbers_rejected_valid_report_traces(tmp_path: Path) -> None:
    shutil.copytree(FIXTURES / "batch_qc", tmp_path / "batch_qc")
    server, _ = build_server(Config(root=tmp_path))
    ledger = server.app.ledger  # type: ignore[attr-defined]
    async with Client(server) as client:
        b = await _call(client, "load_batch", sample_sheet="batch_qc/sample_sheet.csv")
        qc = await _call(client, "qc_batch", batch_handle=b["data"]["batch_handle"])
        ev = qc["provenance_id"]
        body = (
            f"Overall verdict {{{ev}:data.overall}}; RT drift "
            f"{{{ev}:data.metrics.rt_drift_min.value}} min (fail above "
            f"{{{ev}:data.metrics.rt_drift_min.fail}}), mass error "
            f"{{{ev}:data.metrics.mass_error_ppm.value}} ppm across 11 runs."
        )
        good = await _call(
            client,
            "export_report",
            title="QC",
            filename="qc",
            sections=[{"heading": "QC", "body": body}],
        )
        bad = await _call(
            client,
            "export_report",
            title="QC",
            filename="qc_bad",
            sections=[{"heading": "QC", "body": body + " Recovery was 98.4%."}],
        )
    assert good["status"] == "ok" and bad["status"] == "error" and "98.4" in bad["verdict"]
    md = (tmp_path / "simplymz_reports" / "qc.md").read_text()
    narrative = md.split("## Limits and disclosures")[0].split("## QC", 1)[1]
    pool = numbers_in(ledger.get(ev)["result"])
    toks = narrative_numbers(narrative)
    assert toks and all(traceable(t, pool) for t in toks)


@pytest.mark.network
@pytest.mark.anyio
async def test_M5_AC2_pipeline_runs_end_to_end_on_real_public_mzml(tmp_path: Path) -> None:
    from tests.integration.test_real_data import test_pipeline_on_openms_lcms_excerpt

    await test_pipeline_on_openms_lcms_excerpt(tmp_path)


def test_M5_AC3_deterministic_evals_meet_thresholds() -> None:
    import sys

    sys.path.insert(0, str(REPO))
    from eval.deterministic import evaluate

    with tempfile.TemporaryDirectory() as tmp:
        res = evaluate(Path(tmp))
    assert res["all_pass"], res["checks"]
    assert "## LLM evaluation" in (REPO / "eval" / "results.md").read_text()
    # The LLM table itself is a human check in verify.py (needs ANTHROPIC_API_KEY).


def test_M5_AC4_package_builds_and_installs_cleanly(tmp_path: Path) -> None:
    import subprocess
    import sys

    dist = tmp_path / "dist"
    subprocess.run(
        ["uv", "build", "--out-dir", str(dist)],
        cwd=REPO,
        check=True,
        capture_output=True,
        timeout=300,
    )
    wheel = next(dist.glob("*.whl"))
    venv = tmp_path / "venv"
    subprocess.run(["uv", "venv", "-q", str(venv)], check=True, timeout=120)
    py = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    subprocess.run(
        ["uv", "pip", "install", "-q", "--python", str(py), str(wheel)],
        check=True,
        capture_output=True,
        timeout=600,
    )
    exe = venv / ("Scripts/simplymz-mcp.exe" if sys.platform == "win32" else "bin/simplymz-mcp")
    r = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "smoke_installed.py"),
            str(exe),
            str(REPO / "tests" / "fixtures" / "runs" / "clean_pos.mzML"),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "load_run: Loaded 201 spectra" in r.stdout  # a clean install parses mzML
    # Installing from TestPyPI on Linux/macOS/Windows is a gate human-check (release CI).


def test_M5_AC5_readme_has_install_config_workflows_benchmarks_limitations() -> None:
    text = (REPO / "README.md").read_text()
    for heading in ("## Install", "## Three workflows", "## Benchmarks", "## Limitations"):
        assert heading in text, heading
    assert '"mcpServers"' in text and "claude mcp add" in text
    assert all(p in text for p in ("/qc_batch", "/compare_groups", "/identify_peak"))
    assert re.search(r"\| .* \| .* \| .* \|", text.split("## Benchmarks")[1])
