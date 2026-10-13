from __future__ import annotations

import json
import math

import pytest

from simplymz_mcp.analytics.qc import (
    cv_pct,
    load_thresholds,
    longest_dropout,
    measure_feature,
    run_noise,
    verdict,
)
from simplymz_mcp.io.mzml import read_mzml
from simplymz_mcp.synth.fixtures import truth_path
from tests.conftest import FIXTURES


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.0, "pass"),
        (5.0, "pass"),
        (5.000001, "warn"),
        (10.0, "warn"),
        (10.000001, "fail"),
        (None, "not_applicable"),
        (math.nan, "not_applicable"),
    ],
)
def test_verdict_boundaries_are_exact(value: float | None, expected: str) -> None:
    assert verdict(value, 5.0, 10.0) == expected


def test_default_thresholds_complete_and_ordered() -> None:
    th = load_thresholds()
    assert len(th) == 10
    for name, t in th.items():
        assert t["warn"] <= t["fail"], name
        assert t["description"]


def test_threshold_overrides() -> None:
    th = load_thresholds({"rt_drift_min": {"warn": 0.05, "fail": 0.08}})
    assert th["rt_drift_min"]["warn"] == 0.05 and th["mass_error_ppm"]["fail"] == 10.0
    with pytest.raises(KeyError):
        load_thresholds({"nope": {"warn": 1}})
    with pytest.raises(ValueError):
        load_thresholds({"rt_drift_min": {"warn": 1.0, "fail": 0.5}})


def test_cv_pct_hand_computed() -> None:
    # [1, 1, 0.5]: mean 0.8333, sample SD 0.288675 -> 34.641%
    assert cv_pct([1.0, 1.0, 0.5]) == pytest.approx(34.641016, rel=1e-6)
    assert cv_pct([2.0]) is None and cv_pct([None, 3.0]) is None
    assert cv_pct([0.0, 0.0]) is None


def test_measure_feature_matches_truth() -> None:
    p = FIXTURES / "runs" / "clean_pos.mzML"
    truth = json.loads(truth_path(p).read_text())
    run = read_mzml(p)
    noise = run_noise(run)
    for c in truth["compounds"]:
        m = measure_feature(run, c["ion_mz"], c["rt_min"] + 0.4, noise)  # off-centre start
        assert m is not None, c["name"]
        assert abs(m["rt"] - c["rt_min"]) < 0.02
        assert abs(m["mz"] - c["ion_mz"]) / c["ion_mz"] * 1e6 < 2.0
        assert m["area"] == pytest.approx(c["area_counts_min"], rel=0.03)
    assert measure_feature(run, 777.7777, 5.0, noise) is None


def test_mass_error_fault_is_measured() -> None:
    p = FIXTURES / "faults" / "mass_error.mzML.gz"
    truth = json.loads(truth_path(p).read_text())
    run = read_mzml(p)
    c = truth["compounds"][0]
    m = measure_feature(run, c["ion_mz"], c["rt_min"], run_noise(run))
    assert m is not None
    assert (m["mz"] - c["ion_mz"]) / c["ion_mz"] * 1e6 == pytest.approx(8.0, abs=1.0)


def test_longest_dropout() -> None:
    assert longest_dropout(read_mzml(FIXTURES / "faults" / "dropout.mzML.gz")) == 12
    assert longest_dropout(read_mzml(FIXTURES / "runs" / "clean_pos.mzML")) == 0
