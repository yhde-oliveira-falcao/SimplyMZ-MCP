"""M0 acceptance criteria (IMPLEMENTATION_PLAN.md, M0). One test per AC id."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from simplymz_mcp.core.envelope import is_valid_envelope
from tests.conftest import FIXTURES, REPO
from tests.helpers import RawStdioSession

pytestmark = pytest.mark.acceptance


def test_M0_AC1_ci_workflow_defines_six_matrix_jobs() -> None:
    """Structural half of AC1. The real evidence is a green CI run URL recorded in
    STATUS.md, which scripts/verify.py checks as a human/external item."""
    text = (REPO / ".github" / "workflows" / "ci.yml").read_text()
    os_line = re.search(r"os:\s*\[([^\]]+)\]", text)
    py_line = re.search(r"python:\s*\[([^\]]+)\]", text)
    assert os_line and py_line
    oses = {s.strip() for s in os_line.group(1).split(",")}
    pys = {s.strip().strip('"') for s in py_line.group(1).split(",")}
    assert oses == {"ubuntu-latest", "macos-latest", "windows-latest"}
    assert pys == {"3.11", "3.12"}
    assert "gitleaks" in text and "upload-artifact" in text


@pytest.mark.skipif(shutil.which("uvx") is None, reason="uvx not installed")
def test_M0_AC2_uvx_help_and_server_info_over_stdio(tmp_path: Path) -> None:
    p = subprocess.run(
        ["uvx", "--from", str(REPO), "simplymz-mcp", "--help"],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert p.returncode == 0, p.stderr[-2000:]
    assert "usage: simplymz-mcp" in p.stdout
    s = RawStdioSession(tmp_path)
    try:
        s.initialize()
        res = s.request("tools/call", {"name": "server_info", "arguments": {}})
    finally:
        s.close()
    env = res["result"]["structuredContent"]
    assert is_valid_envelope(env) and env["status"] == "ok"


def test_M0_AC3_only_json_rpc_on_stdout_for_full_session(tmp_path: Path) -> None:
    s = RawStdioSession(tmp_path, ["--log-level", "DEBUG"])
    try:
        s.initialize()
        s.request("ping", {})
        s.request("tools/list", {})
        s.request("tools/call", {"name": "server_info", "arguments": {}})
        s.request("tools/call", {"name": "does_not_exist", "arguments": {}})
        s.request("resources/list", {})
        s.request("prompts/list", {})
    finally:
        s.close()
    assert len(s.stdout_lines) >= 7
    for line in s.stdout_lines:
        assert json.loads(line).get("jsonrpc") == "2.0", line


def test_M0_AC4_fixtures_deterministic_parse_and_have_truth() -> None:
    p = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "generate_fixtures.py"), "--check"],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert p.returncode == 0, p.stdout + p.stderr
    manifest = json.loads((FIXTURES / "MANIFEST.json").read_text())
    runs = [rel for rel in manifest["files"] if ".mzML" in rel]
    assert len(runs) >= 20
    from simplymz_mcp.synth.fixtures import truth_path

    for rel in runs:
        assert truth_path(FIXTURES / rel).exists(), rel
    # parsing every file is covered by tests/unit/test_synth.py::test_fixture_parses_*


def test_M0_AC5_gate_has_all_nine_steps_and_summary_covers_criteria() -> None:
    """The gate passing is itself the evidence for AC5; this checks its shape."""
    sys.path.insert(0, str(REPO / "scripts"))
    import verify

    assert len(verify.STEPS) == 9 and len(verify.STEP_NAMES) == 9
    assert verify.acceptance_ids("M0") == [f"M0-AC{i}" for i in range(1, 6)]
    summary = REPO / "docs" / "progress" / "M0_SUMMARY.md"
    assert summary.exists(), "write docs/progress/M0_SUMMARY.md"
    text = summary.read_text(encoding="utf-8")
    for ac in verify.acceptance_ids("M0"):
        assert ac in text
