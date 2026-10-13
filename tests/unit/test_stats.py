from __future__ import annotations

import numpy as np
import pytest
from scipy import stats

from simplymz_mcp.analytics.stats import bh_fdr, compare_groups


@pytest.mark.parametrize("seed", range(5))
def test_bh_matches_scipy_reference(seed: int) -> None:
    p = np.random.default_rng(seed).uniform(0, 1, 40)
    p[:5] = [1e-6, 1e-4, 0.003, 0.02, 0.04]
    assert np.allclose(bh_fdr(p), stats.false_discovery_control(p, method="bh"))
    assert bh_fdr([]).size == 0


def _members(areas: dict[str, dict[str, float]]) -> tuple[list[dict], list[dict]]:
    types = {
        "a1": ("sample", "A"),
        "a2": ("sample", "A"),
        "a3": ("sample", "A"),
        "b1": ("sample", "B"),
        "b2": ("sample", "B"),
        "b3": ("sample", "B"),
        "bl": ("blank", ""),
    }
    members, consensus = [], []
    for k, (cid, per) in enumerate(areas.items()):
        consensus.append({"cid": cid, "mz": 100.0 + k, "rt_min": 1.0 + k})
        for run, area in per.items():
            t, g = types[run]
            members.append({"cid": cid, "run": run, "sample_type": t, "group": g, "area": area})
    return members, consensus


def test_welch_and_fold_change_match_scipy() -> None:
    a, b = [100.0, 120.0, 90.0], [410.0, 380.0, 450.0]
    m, c = _members({"C1": dict(zip(["a1", "a2", "a3", "b1", "b2", "b3"], a + b, strict=True))})
    r = compare_groups(m, c, "A", "B")["ranked"][0]
    ref = stats.ttest_ind(np.log2(b), np.log2(a), equal_var=False).pvalue
    assert r["p_value"] == pytest.approx(ref, rel=1e-2)
    assert r["log2_fc"] == pytest.approx(np.log2(np.mean(b) / np.mean(a)), abs=1e-3)


def test_blank_filter_presence_filter_and_imputation() -> None:
    base = {"a1": 100.0, "a2": 110.0, "a3": 95.0, "b1": 105.0, "b2": 98.0, "b3": 101.0}
    m, c = _members(
        {
            "BLANKY": {**base, "bl": 60.0},  # sample/blank = ~1.7 < 3 -> removed
            "RARE": {"a1": 50.0},  # 1/3 present in A, 0/3 in B -> removed
            "GAPPY": {"a1": 100.0, "a2": 90.0, "b1": 400.0, "b2": 420.0, "b3": 410.0},
        }
    )
    res = compare_groups(m, c, "A", "B")
    assert res["removed_blank"] == 1 and res["removed_presence"] == 1
    (row,) = res["ranked"]
    assert row["cid"] == "GAPPY" and row["imputed"] == 1  # a3 filled with 45 (half of 90)
    assert row["mean_a"] == pytest.approx((100 + 90 + 45) / 3, rel=1e-3)
    assert res["n_a"] == 3 and res["n_b"] == 3
