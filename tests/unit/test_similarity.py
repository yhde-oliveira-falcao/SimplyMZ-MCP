from __future__ import annotations

import math

import numpy as np
import pytest

from simplymz_mcp.annotation.similarity import cosine


def _a(*x: float) -> np.ndarray:
    return np.asarray(x, dtype=float)


def test_identical_and_disjoint() -> None:
    mz, it = _a(100, 150, 200), _a(10, 50, 100)
    assert cosine(mz, it, mz, it)[0] == pytest.approx(1.0)
    assert cosine(mz, it, _a(300, 400), _a(1, 1)) == (0.0, [])
    assert cosine(_a(), _a(), mz, it) == (0.0, [])


def test_hand_computed_partial_match() -> None:
    # a: (100,3) (200,4); b: (100.005,3) (300,4) -> 9 / (5*5) = 0.36
    score, pairs = cosine(_a(100, 200), _a(3, 4), _a(100.005, 300), _a(3, 4), tolerance=0.01)
    assert score == pytest.approx(0.36) and pairs == [(0, 0)]


def test_greedy_uses_each_peak_once() -> None:
    # one peak in a sits between two in b: only the larger product is used
    score, pairs = cosine(_a(100.0), _a(1.0), _a(99.995, 100.005), _a(1.0, 2.0), tolerance=0.01)
    assert pairs == [(0, 1)]
    assert score == pytest.approx(2 / (1 * math.sqrt(5)))


def test_modified_cosine_pairs_shifted_fragments() -> None:
    a_mz, b_mz = _a(100, 250), _a(100, 236)  # second fragment carries the 14 Da shift
    it = _a(1, 1)
    plain = cosine(a_mz, it, b_mz, it, 0.01)[0]
    mod, pairs = cosine(
        a_mz, it, b_mz, it, 0.01, precursor_a=300.0, precursor_b=286.0, modified=True
    )
    assert plain == pytest.approx(0.5) and mod == pytest.approx(1.0) and len(pairs) == 2
    with pytest.raises(ValueError):
        cosine(a_mz, it, b_mz, it, modified=True)


def test_agrees_with_matchms_when_available() -> None:
    matchms = pytest.importorskip("matchms")
    from matchms.similarity import CosineGreedy

    rng = np.random.default_rng(0)
    for _ in range(50):
        a = np.sort(rng.uniform(50, 500, 15))
        b = np.sort(np.concatenate([a[:7] + rng.normal(0, 0.003, 7), rng.uniform(50, 500, 8)]))
        ia, ib = rng.uniform(1, 100, 15), rng.uniform(1, 100, 15)
        ref = CosineGreedy(tolerance=0.01).pair(
            matchms.Spectrum(mz=a, intensities=ia, metadata={"precursor_mz": 600.0}),
            matchms.Spectrum(mz=b, intensities=ib, metadata={"precursor_mz": 600.0}),
        )
        assert cosine(a, ia, b, ib, 0.01)[0] == pytest.approx(float(ref["score"]), abs=1e-12)
