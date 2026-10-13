"""M2.T5 detection matrix: every fault at 0.5x, 1x, 2x, 4x its metric's fail threshold."""

from __future__ import annotations

import pytest

from simplymz_mcp.synth.faults import FAULT_CASES
from tests.conftest import MULTIPLES

pytestmark = pytest.mark.slow


def _verdicts(env: dict) -> dict[str, str]:
    return {k: m["verdict"] for k, m in env["data"]["metrics"].items()}


def test_matrix_is_complete_and_valid(fault_matrix: dict) -> None:
    assert fault_matrix["clean"]["status"] == "ok"
    for fault in FAULT_CASES:
        for k in MULTIPLES:
            env = fault_matrix[(fault, k)]["env"]
            assert env["status"] == "ok", (fault, k, env)


@pytest.mark.parametrize("fault", sorted(FAULT_CASES))
def test_primary_metric_tracks_injected_size(fault: str, fault_matrix: dict) -> None:
    metric = FAULT_CASES[fault][0]
    values = []
    for k in MULTIPLES:
        entry = fault_matrix[(fault, k)]
        m = entry["env"]["data"]["metrics"][metric]
        values.append(m["value"])
        # measured value close to the injected target (within 25% or one threshold step)
        assert m["value"] == pytest.approx(
            entry["case"].target_value, rel=0.25, abs=0.1 * m["fail"]
        ), (fault, k, m)
    assert values == sorted(values), (fault, values)  # monotonic in fault size


@pytest.mark.parametrize("fault", sorted(FAULT_CASES))
def test_at_threshold_primary_is_warn_or_fail(fault: str, fault_matrix: dict) -> None:
    metric = FAULT_CASES[fault][0]
    assert _verdicts(fault_matrix[(fault, 1.0)]["env"])[metric] in ("warn", "fail")
