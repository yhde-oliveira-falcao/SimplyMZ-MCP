from __future__ import annotations

import math
from dataclasses import replace

import numpy as np

from simplymz_mcp.analytics.features import DetectorParams, detect_features
from tests.helpers import make_run

RT = np.round(np.arange(0, 6, 0.02), 4)


def _peak(rt0: float, h: float, sigma: float = 0.04) -> np.ndarray:
    return h * np.exp(-((RT - rt0) ** 2) / (2 * sigma**2))


def _build(ions: list[tuple[float, np.ndarray]], drop: dict[float, set[int]] | None = None):  # type: ignore[no-untyped-def]
    spectra = []
    for k, t in enumerate(RT):
        mz, it = [], []
        for m, y in ions:
            if y[k] >= 50 and k not in (drop or {}).get(m, set()):
                mz.append(m)
                it.append(float(y[k]))
        mz.append(60.0 + (k % 7) * 101.3)  # sparse noise, never forms a trace
        it.append(300.0)
        spectra.append((float(t), mz, it))
    return make_run(spectra)


P = DetectorParams(min_intensity=1000.0)


def _mono(res: dict) -> list[dict]:
    return [f for f in res["features"] if f["isotope_of"] is None]


def test_single_peak_area_and_position() -> None:
    res = detect_features(_build([(200.1, _peak(2.0, 1e5))]), P)
    (f,) = _mono(res)
    assert abs(f["mz"] - 200.1) < 1e-6 and abs(f["rt_min"] - 2.0) < 0.011
    assert math.isclose(f["area"], 1e5 * 0.04 * math.sqrt(2 * math.pi), rel_tol=0.02)


def test_one_scan_gap_joins_two_scan_gap_splits() -> None:
    """Gap rule with max_gap=1 pinned (the default became 4 in M5.T3)."""
    p1 = replace(P, max_gap=1, min_points=5)
    k = int(np.argmin(np.abs(RT - 2.0)))
    one = detect_features(_build([(200.1, _peak(2.0, 1e5))], {200.1: {k}}), p1)
    assert len(_mono(one)) == 1
    wide = _peak(2.0, 1e5, sigma=0.15)
    two = detect_features(_build([(200.1, wide)], {200.1: {k, k + 1}}), p1)
    assert len(_mono(two)) == 2


def test_default_tolerates_intermittent_real_data_gaps() -> None:
    """Default max_gap=4: a peak missing 3 of its scans (as in real centroided data) stays
    one feature; two peaks separated by a long silence stay two."""
    k = int(np.argmin(np.abs(RT - 2.0)))
    wide = _peak(2.0, 1e5, sigma=0.15)
    gappy = detect_features(_build([(200.1, wide)], {200.1: {k - 2, k, k + 2}}), DetectorParams())
    assert len(_mono(gappy)) == 1
    apart = detect_features(_build([(300.2, _peak(1.5, 8e4) + _peak(3.5, 5e4))]), DetectorParams())
    assert len(_mono(apart)) == 2


def test_same_mz_eluting_twice_gives_two_features() -> None:
    res = detect_features(_build([(300.2, _peak(1.5, 8e4) + _peak(3.5, 5e4))]), P)
    assert sorted(round(f["rt_min"], 1) for f in _mono(res)) == [1.5, 3.5]


def test_carbon_isotopes_grouped() -> None:
    res = detect_features(
        _build(
            [
                (250.0, _peak(2.0, 1e5)),
                (251.003355, _peak(2.0, 1.2e4)),
                (252.00671, _peak(2.0, 3e3)),
            ]
        ),
        P,
    )
    mono = _mono(res)
    assert len(mono) == 1
    iso = [f for f in res["features"] if f["isotope_of"] == mono[0]["id"]]
    assert sorted(f["isotope_index"] for f in iso) == [1, 2] and mono[0]["charge"] == 1


def test_chlorine_m_plus_2_grouped_despite_being_strong() -> None:
    res = detect_features(
        _build(
            [(286.944, _peak(4.0, 6e4)), (287.947, _peak(4.0, 8e3)), (288.941, _peak(4.0, 5.8e4))]
        ),
        P,
    )
    assert len(_mono(res)) == 1


def test_doubly_charged_isotopes() -> None:
    res = detect_features(_build([(500.0, _peak(3.0, 1e5)), (500.501678, _peak(3.0, 4e4))]), P)
    (m,) = _mono(res)
    assert m["charge"] == 2


def test_non_coeluting_isotope_spacing_not_grouped() -> None:
    res = detect_features(_build([(250.0, _peak(2.0, 1e5)), (251.003355, _peak(3.0, 1e4))]), P)
    assert len(_mono(res)) == 2


def test_sodium_adduct_grouped() -> None:
    res = detect_features(_build([(195.087652, _peak(2.5, 1e5)), (217.069597, _peak(2.5, 3e4))]), P)
    mono = _mono(res)
    assert len(mono) == 2 and mono[0]["adduct_group"] == mono[1]["adduct_group"] is not None


def test_params_echoed() -> None:
    res = detect_features(_build([(200.1, _peak(2.0, 1e5))]), DetectorParams())
    assert res["params"]["engine"] == "masstrace-lite" and res["params"]["min_intensity"] > 0
