from __future__ import annotations

import math

import numpy as np
import pytest

from simplymz_mcp.analytics.chromatogram import (
    ChromParams,
    detect_peaks,
    extract,
    noise_level,
)
from simplymz_mcp.analytics.integrate import integrate
from simplymz_mcp.io.mzml import RunData, ScanTable


def _run(spectra: list[tuple[float, int, list[float], list[float]]]) -> RunData:
    n = len(spectra)
    mz = [np.asarray(s[2], float) for s in spectra]
    it = [np.asarray(s[3], np.float32) for s in spectra]
    npk = np.array([len(m) for m in mz], dtype=np.int32)
    offsets = np.zeros(n + 1, dtype=np.int64)
    offsets[1:] = np.cumsum(npk)
    st = ScanTable(
        native_id=[f"scan={i + 1}" for i in range(n)],
        rt_min=np.array([s[0] for s in spectra]),
        ms_level=np.array([s[1] for s in spectra], dtype=np.int8),
        polarity=np.ones(n, dtype=np.int8),
        centroided=np.ones(n, dtype=np.int8),
        tic=np.array([float(x.sum()) for x in it]),
        base_peak_mz=np.array(
            [m[np.argmax(i)] if len(m) else np.nan for m, i in zip(mz, it, strict=True)]
        ),
        base_peak_intensity=np.array([float(i.max()) if len(i) else 0.0 for i in it]),
        n_peaks=npk,
        precursor_mz=np.full(n, np.nan),
    )
    return RunData(None, "x", st, offsets, np.concatenate(mz), np.concatenate(it))  # type: ignore[arg-type]


def test_eic_window_boundary_is_inclusive() -> None:
    target, ppm = 200.0, 10.0
    tol = target * ppm * 1e-6
    run = _run(
        [
            (0.1, 1, [target - tol, target + tol], [5.0, 7.0]),  # exactly on both edges: in
            (0.2, 1, [target - tol * 1.0001, target + tol * 1.0001], [5.0, 7.0]),  # just out
            (0.3, 2, [target], [99.0]),  # MS2 scan excluded
        ]
    )
    rt, y = extract(run, ChromParams("EIC", target, ppm))
    assert rt.tolist() == [0.1, 0.2] and y.tolist() == [12.0, 0.0]


def test_tic_bpc_and_rt_range() -> None:
    run = _run([(t, 1, [100.0, 150.0], [1.0, float(k)]) for k, t in enumerate([0.1, 0.2, 0.3])])
    rt, tic = extract(run, ChromParams("TIC", rt_start_min=0.15))
    assert rt.tolist() == [0.2, 0.3] and tic.tolist() == [2.0, 3.0]
    _, bpc = extract(run, ChromParams("BPC"))
    assert bpc.tolist() == [1.0, 1.0, 2.0]


def test_noise_level_estimates_white_noise_sigma() -> None:
    rng = np.random.default_rng(0)
    y = 1000 + 0.5 * np.arange(5000) + rng.normal(0, 40, 5000)  # drift must not matter
    assert noise_level(y) == pytest.approx(40, rel=0.08)


def test_detect_peaks_finds_two_and_echoes_params() -> None:
    rt = np.arange(0, 5, 0.01)
    y = 1e5 * np.exp(-((rt - 1.7) ** 2) / 0.002) + 4e4 * np.exp(-((rt - 3.2) ** 2) / 0.002)
    out = detect_peaks(rt, y)
    assert [p["rt_min"] for p in out["peaks"]] == [1.7, 3.2]
    assert out["params"]["method"] == "scipy.signal.find_peaks"
    assert detect_peaks(rt, np.zeros_like(rt))["peaks"] == []


def _gauss(
    seed: int, snr: float, dt: float = 0.01, sigma: float = 0.05, h: float = 1e5
) -> tuple[np.ndarray, np.ndarray, float]:
    rng = np.random.default_rng(seed)
    rt = np.arange(0, 3, dt)
    c = 1.503 + rng.uniform(-0.005, 0.005)  # off-grid apex
    y = 2000 + 500 * rt + h * np.exp(-((rt - c) ** 2) / (2 * sigma**2))
    if snr:
        y = y + rng.normal(0, h / snr, rt.size)
    return rt, y, h * sigma * math.sqrt(2 * math.pi)


def test_noiseless_gaussian_area_height_fwhm() -> None:
    rt, y, truth = _gauss(0, 0)
    r = integrate(rt, y)
    assert r["area_counts_min"] == pytest.approx(truth, rel=0.003)
    assert r["height_counts"] == pytest.approx(1e5, rel=0.01)
    assert r["fwhm_min"] == pytest.approx(2.3548 * 0.05, rel=0.02)
    assert r["asymmetry_10pct"] == pytest.approx(1.0, abs=0.05)


def test_area_at_snr_50_is_unbiased_and_mostly_within_3pct() -> None:
    """M1.T7 criterion, tested statistically (see M1.md deviations): at RMS-SNR 50 the
    noise alone spreads single-trace areas by ~1.5%, so ~4% of realisations exceed 3%."""
    errs = np.array(
        [
            integrate(*_gauss(s, 50)[:2])["area_counts_min"] / _gauss(s, 50)[2] - 1
            for s in range(200)
        ]
    )
    assert abs(errs.mean()) < 0.005
    assert np.mean(np.abs(errs) <= 0.03) >= 0.95


@pytest.mark.parametrize("snr", [100, 200, 1000])
def test_area_within_3pct_every_time_at_higher_snr(snr: int) -> None:
    for s in range(60):
        rt, y, truth = _gauss(s, snr)
        assert integrate(rt, y)["area_counts_min"] == pytest.approx(truth, rel=0.03)


def test_snr_reported_close_to_true_value() -> None:
    snrs = [integrate(*_gauss(s, 100)[:2])["snr"] for s in range(30)]
    assert 80 < float(np.median(snrs)) < 125


def test_tailing_peak_asymmetry() -> None:
    rt = np.arange(0, 3, 0.005)
    sig = np.where(rt < 1.5, 0.04, 0.08)  # trailing side twice as wide
    y = 1e5 * np.exp(-((rt - 1.5) ** 2) / (2 * sig**2))
    assert integrate(rt, y)["asymmetry_10pct"] == pytest.approx(2.0, rel=0.05)


def test_overlapping_peaks_flagged() -> None:
    rt = np.arange(0, 3, 0.01)
    y = 1e5 * np.exp(-((rt - 1.4) ** 2) / 0.005) + 8e4 * np.exp(-((rt - 1.62) ** 2) / 0.005)
    r = integrate(rt, y, apex_rt=1.4)
    assert r["overlap"] and any("Overlapping" in w for w in r["warnings"])


def test_user_bounds_and_errors() -> None:
    rt, y, truth = _gauss(1, 0)
    r = integrate(rt, y, rt_start=1.2, rt_end=1.8)
    assert r["bounds_mode"] == "user" and r["area_counts_min"] == pytest.approx(truth, rel=0.01)
    with pytest.raises(ValueError):
        integrate(rt, y, rt_start=1.5, rt_end=1.505)
    with pytest.raises(ValueError):
        integrate(rt[:2], y[:2])


def test_coarse_sampling_warns() -> None:
    rt = np.arange(0, 3, 0.05)
    y = 1e5 * np.exp(-((rt - 1.5) ** 2) / (2 * 0.04**2))
    r = integrate(rt, y)
    assert r["points_across_peak"] < 7 and any("points across" in w for w in r["warnings"])


def test_peak_cut_by_end_of_trace_warns() -> None:
    rt = np.arange(0, 3, 0.01)
    y = 1e5 * np.exp(-((rt - 2.9) ** 2) / (2 * 0.05**2))
    r = integrate(rt, y)
    assert any("edge of the trace" in w for w in r["warnings"])
    assert not any("edge" in w for w in integrate(*_gauss(0, 0)[:2])["warnings"])


@pytest.mark.parametrize(
    ("snr", "points", "tier", "phrase"),
    [
        (None, 20, "unknown", "cannot be estimated"),
        (30.0, 20, "not_validated", "not validated"),
        (60.0, 20, "approx_3pct", "1 trace in 20"),
        (150.0, 20, "within_3pct", "every validation trace"),
        (60.0, 5, "approx_3pct", "half as good"),
    ],
)
def test_area_precision_disclosure(snr: float | None, points: int, tier: str, phrase: str) -> None:
    from simplymz_mcp.analytics.integrate import area_precision

    d = area_precision(snr, points)
    assert d["tier"] == tier and phrase in d["note"]
    assert "RMS noise" in d["note"] and "USP" in d["note"]  # SNR definition always disclosed


def test_integration_result_carries_disclosure() -> None:
    rt, y, _ = _gauss(3, 60)
    r = integrate(rt, y)
    assert r["area_precision"]["tier"] in ("approx_3pct", "within_3pct")
    assert "Validated on synthetic Gaussian peaks" in r["area_precision"]["note"]


def test_noisy_short_trace_never_crashes_and_bounds_contain_apex() -> None:
    """Regression (M5.T3 real data): a smoothed apex away from the raw maximum used to
    leave the raw apex outside the integration bounds -> IndexError."""
    rng = np.random.default_rng(3)
    for _ in range(300):
        n = int(rng.integers(5, 15))
        rt = np.arange(n) * 0.03
        y = rng.uniform(0, 1, n) * 1e4
        y[int(rng.integers(0, n))] *= rng.uniform(1, 3)
        r = integrate(rt, y)
        assert r["rt_start_min"] <= r["rt_apex_min"] <= r["rt_end_min"]
