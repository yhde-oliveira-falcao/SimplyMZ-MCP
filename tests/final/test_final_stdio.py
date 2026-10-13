"""Final Verification C9-C14: product behaviour over real stdio, scripted MCP client."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

import pytest

from simplymz_mcp.core.envelope import is_valid_envelope
from tests.conftest import FIXTURES
from tests.helpers import RawStdioSession

pytestmark = [pytest.mark.e2e, pytest.mark.slow]


class Client:
    def __init__(self, root: Path, cache: Path) -> None:
        self.s = RawStdioSession(root, ["--cache-dir", str(cache)])
        self.s.initialize()

    def call(self, tool: str, **args: Any) -> dict[str, Any]:
        r = self.s.request("tools/call", {"name": tool, "arguments": args}, timeout=180)
        env = r["result"]["structuredContent"]
        assert is_valid_envelope(env), (tool, env)
        return env

    def close(self) -> None:
        self.s.close()


@pytest.fixture(scope="module")
def root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    r = tmp_path_factory.mktemp("final")
    for d in ("runs", "batch_qc", "faults", "library"):
        shutil.copytree(FIXTURES / d, r / d)
    # Faulty batch: qc_02 replaced by a render with mass error at 2x the fail threshold.
    from simplymz_mcp.analytics.qc import load_thresholds
    from simplymz_mcp.synth.faults import make_case
    from simplymz_mcp.synth.model import render
    from simplymz_mcp.synth.writer import write_mzml

    case = make_case("mass_error", 2.0, load_thresholds()["mass_error_ppm"]["fail"])
    scans, _ = render(case.spec)
    write_mzml(scans, r / "faults" / "qc_02.mzML.gz", case.spec.name, "positive")
    sheet = (FIXTURES / "batch_qc" / "sample_sheet.csv").read_text().splitlines()
    rows = [ln if ln.startswith("qc_02") else f"../batch_qc/{ln}" for ln in sheet[1:]]
    (r / "faults" / "sheet_mass_error.csv").write_text("\n".join([sheet[0], *rows]) + "\n")
    return r


def test_final_c9_to_c14_over_stdio(root: Path, tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    c = Client(root, cache)
    try:
        # C9: catalogue and budgets
        tools = c.s.request("tools/list", {})["result"]["tools"]
        prompts = c.s.request("prompts/list", {})["result"]["prompts"]
        templates = c.s.request("resources/templates/list", {})["result"]["resourceTemplates"]
        assert len(tools) >= 15 and len(prompts) == 4 and len(templates) >= 2
        assert all(t["inputSchema"].get("additionalProperties") is False for t in tools)

        # C10: workflow 1 on clean and faulty batches
        clean = c.call("load_batch", sample_sheet="batch_qc/sample_sheet.csv")
        qc_clean = c.call("qc_batch", batch_handle=clean["data"]["batch_handle"])
        assert qc_clean["data"]["overall"] == "pass"
        bad = c.call("load_batch", sample_sheet="faults/sheet_mass_error.csv")
        qc_bad = c.call("qc_batch", batch_handle=bad["data"]["batch_handle"])
        failing = {k for k, m in qc_bad["data"]["metrics"].items() if m["verdict"] == "fail"}
        assert failing == {"mass_error_ppm"}, failing

        # C11: workflow 2
        job = c.call("detect_features", batch_handle=clean["data"]["batch_handle"])
        h = job["data"]["job_handle"]
        for _ in range(300):
            st = c.call("job_status", job_handle=h)
            if st["data"]["state"] not in ("queued", "running"):
                break
            time.sleep(1)
        ftab = st["data"]["result"]["data"]["ftab_handle"]
        comp = c.call("compare_groups", ftab_handle=ftab, group_a="A", group_b="B")
        assert comp["status"] == "ok"

        # C12: workflow 3
        truth = json.loads((FIXTURES / "runs" / "ms2_dda.truth.json").read_text())
        by = {x["name"]: x for x in truth["compounds"]}
        run = c.call("load_run", path="runs/ms2_dda.mzML.gz")["data"]["run_handle"]
        lib = c.call("load_library", path="library/synthetic_library.msp")["data"]
        levels = {}
        evs = {}
        for name in ("caffeine", "kynurenine"):
            x = by[name]
            m = c.call(
                "match_spectrum",
                run_handle=run,
                precursor_mz=x["ion_mz"],
                library_handle=lib["library_handle"],
                rt_min=x["rt_min"],
            )
            conf = c.call("assign_confidence", evidence=[m["provenance_id"]])
            levels[name] = (conf["data"]["level"], conf["data"]["identity"])
            evs[name] = m["provenance_id"]
        assert levels["caffeine"] == (2, "caffeine")
        assert levels["kynurenine"][1] is None

        # C13: reports for each workflow; tampered narrative rejected
        q, a = qc_clean["provenance_id"], comp["provenance_id"]
        for fname, body in [
            ("w1", f"QC verdict {{{q}:data.overall}}."),
            ("w2", f"Comparison verdict: {{{a}:verdict}}"),
            (
                "w3",
                f"Top hit {{{evs['caffeine']}:data.hits[0].name}} scored "
                f"{{{evs['caffeine']}:data.hits[0].score}}.",
            ),
        ]:
            rep = c.call(
                "export_report",
                title=fname,
                filename=f"final_{fname}",
                sections=[{"heading": "Result", "body": body}],
                overwrite=True,
            )
            assert rep["status"] == "ok", rep
        tampered = c.call(
            "export_report",
            title="x",
            filename="final_tampered",
            sections=[{"heading": "R", "body": f"QC {{{q}:data.overall}}; recovery 99.1%."}],
        )
        assert tampered["status"] == "error" and "99.1" in tampered["verdict"]
        n_ledger = len(json.dumps(c.call("server_info")))  # touch ledger once more
        assert n_ledger > 0
    finally:
        c.close()

    # C14: restart mid-session: handles and ledger survive
    c2 = Client(root, cache)
    try:
        card = c2.call("run_card", run_handle=run)
        assert card["status"] == "ok"
        again = c2.call("assign_confidence", evidence=[evs["caffeine"]])
        assert again["data"]["level"] == 2
    finally:
        c2.close()
