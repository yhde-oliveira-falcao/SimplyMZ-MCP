from __future__ import annotations

import numpy as np

from simplymz_mcp.analytics.runcard import detect_anomalies, downsample_max, rolling_percentile


def _flat(n: int = 200) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    rt = np.arange(n) * 0.05
    tic = np.full(n, 3500.0)
    tic[50:53] = [1e6, 5e6, 1e6]  # dense peaks must not cause false dropouts
    tic[60:63] = [2e6, 8e6, 2e6]
    return rt, tic, np.full(n, 12), np.ones(n, dtype=np.int8)


def test_downsample_keeps_apex_and_bin_count() -> None:
    x = np.linspace(0, 10, 1000)
    y = np.exp(-((x - 3.3) ** 2) / 0.01)
    xs, ys = downsample_max(x, y, 40)
    assert len(xs) <= 40 and max(ys) == y.max() and xs[int(np.argmax(ys))] == x[np.argmax(y)]
    assert downsample_max(x[:5], y[:5], 40) == (x[:5].tolist(), y[:5].tolist())
    assert downsample_max(np.empty(0), np.empty(0)) == ([], [])


def test_clean_trace_has_no_anomalies() -> None:
    assert detect_anomalies(*_flat()) == []


def test_rt_gap_detected() -> None:
    rt, tic, n, pol = _flat()
    rt[100:] += 1.0
    a = detect_anomalies(rt, tic, n, pol)
    assert [x["type"] for x in a] == ["rt_gap"] and a[0]["rt_start_min"] == round(rt[99], 3)


def test_empty_scans_grouped() -> None:
    rt, tic, n, pol = _flat()
    n[120:130] = 0
    tic[120:130] = 0
    a = detect_anomalies(rt, tic, n, pol)
    assert a == [{"type": "empty_scans", "rt_start_min": 6.0, "rt_end_min": 6.45, "n_scans": 10}]


def test_tic_collapse_with_peaks_is_dropout() -> None:
    rt, tic, n, pol = _flat()
    tic[140:146] = 20.0  # spray failure: a few counts, peaks still listed
    a = detect_anomalies(rt, tic, n, pol)
    assert [x["type"] for x in a] == ["tic_dropout"] and a[0]["n_scans"] == 6


def test_polarity_switching() -> None:
    rt, tic, n, pol = _flat()
    pol[1::2] = -1
    a = detect_anomalies(rt, tic, n, pol)
    assert [x["type"] for x in a] == ["polarity_switching"] and a[0]["n_scans"] == 199


def test_rolling_percentile_shape() -> None:
    y = np.arange(10.0)
    out = rolling_percentile(y, 3, 50)
    assert out.shape == y.shape and out[5] == 5.0


def test_longer_dropout_still_detected() -> None:
    rt, tic, n, pol = _flat()
    tic[100:118] = 30.0  # 18-scan collapse
    a = detect_anomalies(rt, tic, n, pol)
    assert [x["type"] for x in a] == ["tic_dropout"] and a[0]["n_scans"] == 18
