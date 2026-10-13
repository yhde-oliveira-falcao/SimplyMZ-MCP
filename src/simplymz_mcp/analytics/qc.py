"""Batch QC metrics (plan M2.T2) and verdicts (M2.T3). Pure functions over loaded runs."""

from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

import numpy as np

from simplymz_mcp.analytics.chromatogram import ChromParams, detect_peaks, extract
from simplymz_mcp.analytics.integrate import integrate
from simplymz_mcp.analytics.runcard import _ranges, detect_anomalies
from simplymz_mcp.io.mzml import RunData

ISOTOPE_DELTA = 1.003355
MEASURE_PPM = 50.0  # wide enough to follow mass errors several times the fail threshold
MEASURE_RT_WINDOW = 1.0  # min, wide enough to follow RT drift several times the threshold
ISOLATION_PPM = 50.0
MAX_FEATURES = 10
MISSING_FACTOR = 10.0  # detected if apex >= 10x the run's median centroid intensity
CARRYOVER_ELIGIBLE = 0.5  # features with blank >= 50% of sample level are background


def load_thresholds(overrides: dict[str, dict[str, float]] | None = None) -> dict[str, Any]:
    text = files("simplymz_mcp.analytics").joinpath("qc_defaults.toml").read_text("utf-8")
    th: dict[str, Any] = tomllib.loads(text)
    for name, vals in (overrides or {}).items():
        if name not in th:
            raise KeyError(name)
        th[name] = {**th[name], **{k: float(v) for k, v in vals.items() if k in ("warn", "fail")}}
        if th[name]["warn"] > th[name]["fail"]:
            raise ValueError(f"{name}: warn must be <= fail")
    return th


def verdict(value: float | None, warn: float, fail: float) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "not_applicable"
    if value <= warn:
        return "pass"
    if value <= fail:
        return "warn"
    return "fail"


@dataclass
class BatchRun:
    label: str  # file name
    sample_type: str
    injection_order: int
    run: RunData


Measure = dict[str, float]


def area(m: Measure | None) -> float | None:
    return None if m is None else m["area"]


def cv_pct(x: list[float | None] | list[float] | list[int]) -> float | None:
    a = np.asarray([v for v in x if v is not None], dtype=float)
    if a.size < 2 or a.mean() == 0:
        return None
    return float(a.std(ddof=1) / a.mean() * 100)


def run_noise(run: RunData) -> float:
    ms1 = run.scans.ms_level == 1
    idx = np.flatnonzero(ms1)
    vals = [run.peaks(int(i))[1] for i in idx]
    allv = np.concatenate(vals) if vals else np.empty(0)
    return float(np.median(allv)) if allv.size else 0.0


def measure_feature(
    run: RunData,
    mz: float,
    rt: float,
    noise: float,
    ppm: float = MEASURE_PPM,
    rt_window: float = MEASURE_RT_WINDOW,
) -> dict[str, float] | None:
    """Follow one feature: per MS1 scan in the RT window, the most intense centroid within
    +/- ppm. Returns observed m/z (intensity-weighted around the apex), apex RT, height,
    area; None when the apex is below MISSING_FACTOR x the run's median centroid intensity."""
    s = run.scans
    idx = np.flatnonzero((s.ms_level == 1) & (np.abs(s.rt_min - rt) <= rt_window))
    if idx.size < 3:
        return None
    tol = mz * ppm * 1e-6
    ys, ms = np.zeros(idx.size), np.full(idx.size, np.nan)
    for k, i in enumerate(idx):
        m, it = run.peaks(int(i))
        a = int(np.searchsorted(m, mz - tol))
        b = int(np.searchsorted(m, mz + tol, side="right"))
        if b > a:
            j = a + int(np.argmax(it[a:b]))
            ys[k], ms[k] = float(it[j]), float(m[j])
    apex = int(np.argmax(ys))
    if ys[apex] < MISSING_FACTOR * max(noise, 1.0):
        return None
    lo, hi = max(apex - 1, 0), min(apex + 2, idx.size)
    w = ys[lo:hi]
    mz_obs = float(np.nansum(ms[lo:hi] * w) / w[~np.isnan(ms[lo:hi])].sum())
    rts = s.rt_min[idx]
    area = integrate(rts, ys, apex_rt=float(rts[apex]))["area_counts_min"]
    rt_apex = float(rts[apex])
    if 0 < apex < idx.size - 1:  # parabolic vertex: sub-scan RT resolution
        y0, y1, y2 = ys[apex - 1], ys[apex], ys[apex + 1]
        denom = y0 - 2 * y1 + y2
        if denom < 0:
            rt_apex += 0.5 * (y0 - y2) / denom * float(rts[apex + 1] - rts[apex])
    return {"mz": mz_obs, "rt": rt_apex, "height": float(ys[apex]), "area": float(area)}


def pick_reference_features(
    qcs: list[BatchRun], max_features: int = MAX_FEATURES
) -> list[dict[str, float]]:
    """Stable, isolated, high-intensity features present in every QC injection."""
    if not qcs:
        return []
    tics = [float(q.run.scans.tic[q.run.scans.ms_level == 1].sum()) for q in qcs]
    template = qcs[int(np.argsort(tics)[len(tics) // 2])].run
    rt, bpc = extract(template, ChromParams("BPC"))
    ms1 = np.flatnonzero(template.scans.ms_level == 1)
    peaks = sorted(detect_peaks(rt, bpc, max_peaks=40)["peaks"], key=lambda p: -p["height_counts"])
    rt_lo, rt_hi = float(rt[0]) + 0.3, float(rt[-1]) - 0.3
    noise = {id(q): run_noise(q.run) for q in qcs}
    chosen: list[dict[str, float]] = []
    for p in peaks:
        if not rt_lo <= p["rt_min"] <= rt_hi:
            continue
        i = ms1[int(np.argmin(np.abs(rt - p["rt_min"])))]
        mz = float(template.scans.base_peak_mz[i])
        if any(
            (abs(c["mz"] - mz) / mz * 1e6 < 20 and abs(c["rt"] - p["rt_min"]) < 0.2)
            or (abs(mz - ISOTOPE_DELTA - c["mz"]) < 0.01 and abs(c["rt"] - p["rt_min"]) < 0.1)
            for c in chosen
        ):
            continue
        narrow = measure_feature(template, mz, p["rt_min"], noise[id(qcs[0])], ppm=10)
        wide = measure_feature(template, mz, p["rt_min"], noise[id(qcs[0])], ppm=ISOLATION_PPM)
        if (
            narrow is None
            or wide is None
            or wide["height"] > 1.05 * narrow["height"]
            or abs(wide["rt"] - narrow["rt"]) > 1e-9
        ):
            continue  # another ion within +/-50 ppm would confuse drift measurements
        if all(measure_feature(q.run, mz, p["rt_min"], noise[id(q)]) is not None for q in qcs):
            chosen.append({"mz": round(mz, 6), "rt": round(p["rt_min"], 4)})
        if len(chosen) >= max_features:
            break
    return chosen


def longest_dropout(run: RunData) -> int:
    s = run.scans
    ms1 = s.ms_level == 1
    rt, tic, npk, pol = s.rt_min[ms1], s.tic[ms1], s.n_peaks[ms1], s.polarity[ms1]
    worst = max((b - a + 1 for a, b in _ranges(npk == 0)), default=0)
    for an in detect_anomalies(rt, tic, npk, pol):
        if an["type"] == "tic_dropout":
            worst = max(worst, int(an["n_scans"]))
    return worst


def compute_qc(
    runs: list[BatchRun], thresholds: dict[str, Any], targets: list[dict[str, float]] | None = None
) -> dict[str, Any]:
    runs = sorted(runs, key=lambda r: r.injection_order)
    qcs = [r for r in runs if r.sample_type == "qc"]
    blanks = [r for r in runs if r.sample_type == "blank"]
    nonblank = [r for r in runs if r.sample_type != "blank"]
    samples = [r for r in runs if r.sample_type == "sample"]
    absolute = bool(targets)
    feats = (
        [{"mz": float(t["mz"]), "rt": float(t["rt_min"])} for t in targets]
        if targets
        else pick_reference_features(qcs)
    )
    noise = {r.label: run_noise(r.run) for r in runs}
    table = {
        r.label: [measure_feature(r.run, f["mz"], f["rt"], noise[r.label]) for f in feats]
        for r in runs
    }
    out: dict[str, dict[str, Any]] = {}

    def put(
        name: str,
        value: float | None,
        unit: str,
        offenders: list[str] | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        th = thresholds[name]
        out[name] = {
            "value": None if value is None else round(value, 3),
            "unit": unit,
            "verdict": verdict(value, th["warn"], th["fail"]),
            "warn": th["warn"],
            "fail": th["fail"],
            "offenders": (offenders or [])[:3],
            "detail": detail or {},
        }

    tic = {r.label: float(r.run.scans.tic[r.run.scans.ms_level == 1].sum()) for r in runs}
    put(
        "tic_cv_qc_pct",
        cv_pct([tic[q.label] for q in qcs]) if len(qcs) >= 2 else None,
        "%",
        [max(qcs, key=lambda q: abs(tic[q.label] - np.median([tic[x.label] for x in qcs]))).label]
        if len(qcs) >= 2
        else [],
    )

    ref_rt: list[float | None] = []
    ref_mz: list[float | None] = []
    for j, f in enumerate(feats):
        q = [m for r in qcs if (m := table[r.label][j]) is not None]
        ref_rt.append(float(np.median([m["rt"] for m in q])) if q else None)
        ref_mz.append(
            f["mz"] if absolute else (float(np.median([m["mz"] for m in q])) if q else None)
        )

    worst_rt, worst_rt_run = None, None
    for r in nonblank:
        for j, m in enumerate(table[r.label]):
            rr = ref_rt[j]
            if m is not None and rr is not None:
                d = abs(m["rt"] - rr)
                if worst_rt is None or d > worst_rt:
                    worst_rt, worst_rt_run = d, r.label
    put(
        "rt_drift_min",
        worst_rt if feats and qcs else None,
        "min",
        [worst_rt_run] if worst_rt_run else [],
    )

    worst_ppm, worst_ppm_run = None, None
    for r in nonblank:
        errs = [
            (m["mz"] - rm) / rm * 1e6
            for j, m in enumerate(table[r.label])
            if m is not None and (rm := ref_mz[j])
        ]
        if errs:
            e = abs(float(np.median(errs)))
            if worst_ppm is None or e > worst_ppm:
                worst_ppm, worst_ppm_run = e, r.label
    put(
        "mass_error_ppm",
        worst_ppm,
        "ppm",
        [worst_ppm_run] if worst_ppm_run else [],
        {"reference": "user targets (absolute)" if absolute else "QC median (relative)"},
    )

    cvs = [cv_pct([area(table[q.label][j]) for q in qcs]) for j in range(len(feats))]
    cvs_ok = [c for c in cvs if c is not None]
    put(
        "qc_feature_cv_pct",
        float(np.median(cvs_ok)) if cvs_ok and len(qcs) >= 3 else None,
        "%",
        detail={
            "pct_features_above_30": round(100 * np.mean([c > 30 for c in cvs_ok]), 1)
            if cvs_ok
            else None
        },
    )

    pairs = [(r.label, j) for r in nonblank for j in range(len(feats))]
    miss = [lbl for lbl, j in pairs if table[lbl][j] is None]
    put(
        "missingness_pct",
        100 * len(miss) / len(pairs) if pairs else None,
        "%",
        sorted(set(miss), key=miss.count, reverse=True),
    )

    sample_level = [
        float(
            np.median([v for r in nonblank if (v := area(table[r.label][j])) is not None] or [0.0])
        )
        for j in range(len(feats))
    ]
    # Background (system) features are as high in the cleanest blank as in samples; carryover
    # is judged only on features whose level in the least contaminated blank is < 50%.
    eligible = [
        j
        for j in range(len(feats))
        if sample_level[j] > 0
        and blanks
        and min((area(table[b.label][j]) or 0.0) for b in blanks)
        < CARRYOVER_ELIGIBLE * sample_level[j]
    ]
    worst_co, worst_co_run = None, None
    for b in blanks:
        prev = [r for r in runs if r.injection_order < b.injection_order]
        if not prev or prev[-1].sample_type == "blank":
            continue
        p = prev[-1]
        for j in eligible:
            pm = table[p.label][j]
            if pm is None or pm["area"] <= 0:
                continue
            bm = table[b.label][j]
            ratio = 100 * (bm["area"] if bm else 0.0) / pm["area"]
            if worst_co is None or ratio > worst_co:
                worst_co, worst_co_run = ratio, b.label
    put(
        "blank_carryover_pct",
        worst_co,
        "%",
        [worst_co_run] if worst_co_run else [],
        {"eligible_features": len(eligible)},
    )

    med_sample_tic = (
        float(np.median([tic[r.label] for r in samples or nonblank]))
        if (samples or nonblank)
        else 0.0
    )
    cont = [(100 * tic[b.label] / med_sample_tic, b.label) for b in blanks if med_sample_tic > 0]
    put(
        "blank_contamination_pct",
        max(cont)[0] if cont else None,
        "%",
        [max(cont)[1]] if cont else [],
    )

    ms2 = [int(np.count_nonzero(q.run.scans.ms_level >= 2)) for q in qcs]
    put("ms2_count_cv_pct", cv_pct(ms2) if any(ms2) and len(qcs) >= 2 else None, "%")

    trends = []
    if len(qcs) >= 3:
        x = np.array([q.injection_order for q in qcs], dtype=float)
        for j in range(len(feats)):
            a = [area(table[q.label][j]) for q in qcs]
            if all(v and v > 0 for v in a):
                slope = float(np.polyfit(x, np.log(np.asarray(a, dtype=float)), 1)[0])
                trends.append(abs(math.expm1(slope)) * 100)
    put("intensity_trend_pct_per_injection", max(trends) if trends else None, "%/injection")

    drops = {r.label: longest_dropout(r.run) for r in runs}
    worst_drop = max(drops.values()) if drops else None
    put(
        "scan_dropouts",
        float(worst_drop) if worst_drop is not None else None,
        "scans",
        [k for k, v in sorted(drops.items(), key=lambda kv: -kv[1]) if v > 0],
    )

    order = {"fail": 3, "warn": 2, "pass": 1, "not_applicable": 0}
    overall = max((m["verdict"] for m in out.values()), key=lambda v: order[v], default="pass")
    return {
        "overall": "pass" if overall == "not_applicable" else overall,
        "metrics": out,
        "reference_features": [{"mz": f["mz"], "rt_min": f["rt"]} for f in feats],
        "reference_mode": "user targets" if absolute else "auto from QC injections",
        "n_runs": len(runs),
    }
