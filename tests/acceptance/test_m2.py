"""M2 acceptance criteria (IMPLEMENTATION_PLAN.md, M2). One test per AC id."""

from __future__ import annotations

import shutil
from pathlib import Path

import anyio
import pytest
from mcp import Client

from simplymz_mcp.config import Config
from simplymz_mcp.core.budget import estimate_tokens
from simplymz_mcp.ledger.ledger import digest
from simplymz_mcp.server import build_server
from simplymz_mcp.synth.faults import FAULT_CASES
from tests.conftest import FIXTURES, MULTIPLES

pytestmark = pytest.mark.acceptance
NOT_FLAGGED = ("pass", "not_applicable")


def _verdicts(env: dict) -> dict[str, str]:
    return {k: m["verdict"] for k, m in env["data"]["metrics"].items()}


def test_M2_AC1_clean_batch_every_metric_passes(fault_matrix: dict) -> None:
    v = _verdicts(fault_matrix["clean"])
    assert fault_matrix["clean"]["data"]["overall"] == "pass"
    # ms2_count_cv_pct is not applicable: the QC fixtures contain no MS2 spectra.
    assert {k: x for k, x in v.items() if x != "pass"} == {"ms2_count_cv_pct": "not_applicable"}


@pytest.mark.parametrize("fault", sorted(FAULT_CASES))
@pytest.mark.parametrize("multiple", [2.0, 4.0])
def test_M2_AC2_fault_at_2x_or_more_fails_only_plausible_metrics(
    fault: str, multiple: float, fault_matrix: dict
) -> None:
    metric, _, allowed = FAULT_CASES[fault]
    v = _verdicts(fault_matrix[(fault, multiple)]["env"])
    assert v[metric] == "fail", (fault, multiple, v)
    unexpected = {k: x for k, x in v.items() if k not in allowed and x not in NOT_FLAGGED}
    assert unexpected == {}, (fault, multiple, unexpected)


@pytest.mark.parametrize("fault", sorted(FAULT_CASES))
def test_M2_AC3_fault_at_half_threshold_does_not_fail(fault: str, fault_matrix: dict) -> None:
    metric, _, allowed = FAULT_CASES[fault]
    v = _verdicts(fault_matrix[(fault, 0.5)]["env"])
    assert v[metric] != "fail", (fault, v)
    unexpected = {k: x for k, x in v.items() if k not in allowed and x not in NOT_FLAGGED}
    assert unexpected == {}, (fault, unexpected)


def test_M2_AC4_identical_inputs_give_identical_output(tmp_path: Path) -> None:
    shutil.copytree(FIXTURES / "batch_qc", tmp_path / "batch_qc")

    async def once(cache: str) -> dict:
        server, _ = build_server(Config(root=tmp_path, cache_dir=tmp_path / cache))
        async with Client(server) as client:
            b = await client.call_tool("load_batch", {"sample_sheet": "batch_qc/sample_sheet.csv"})
            r = await client.call_tool(
                "qc_batch", {"batch_handle": b.structured_content["data"]["batch_handle"]}
            )
        env = r.structured_content
        return {k: env[k] for k in ("status", "verdict", "data", "limits", "next_steps")}

    a = anyio.run(once, "cache_a")
    b = anyio.run(once, "cache_b")  # fresh cache: re-parsed from mzML
    assert digest(a) == digest(b)


def test_M2_AC5_qc_output_within_budget_on_largest_batch(
    fault_matrix: dict, tmp_path: Path
) -> None:
    server, registry = build_server(Config(root=tmp_path))
    budget = registry.get("qc_batch").budget_tokens
    server.app.store.close()  # type: ignore[attr-defined]
    envs = [fault_matrix["clean"]] + [
        fault_matrix[(f, k)]["env"] for f in FAULT_CASES for k in MULTIPLES
    ]
    assert fault_matrix["clean"]["data"]["n_runs"] == 11  # largest fixture batch
    for env in envs:
        assert estimate_tokens(env) <= budget and not env["truncated"]
