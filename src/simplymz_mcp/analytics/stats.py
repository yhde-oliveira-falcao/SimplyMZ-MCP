"""Group comparison statistics (plan M3.T6)."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy import stats

SMALL_N = 5


def bh_fdr(p: list[float] | np.ndarray) -> np.ndarray:
    """Benjamini-Hochberg adjusted p-values (q-values), monotone, capped at 1."""
    p = np.asarray(p, dtype=float)
    n = p.size
    if n == 0:
        return p
    order = np.argsort(p)
    ranked = p[order] * n / np.arange(1, n + 1)
    q = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(n)
    out[order] = np.minimum(q, 1.0)
    return out


def compare_groups(
    members: list[dict[str, Any]],
    consensus: list[dict[str, Any]],
    group_a: str,
    group_b: str,
    blank_fold: float = 3.0,
    min_presence: float = 0.5,
) -> dict[str, Any]:
    """Per consensus feature: blank filter, presence filter, imputation, Welch t on log2.

    Rules (all reported back):
    * blank filter: removed if max blank area > 0 and the larger group median / max blank
      area < blank_fold;
    * presence filter: kept only if detected in >= min_presence of the samples of at least
      one group;
    * imputation: a missing sample value = half of that feature's smallest observed sample
      area;
    * log2 fold change = log2(mean B / mean A); Welch t-test on log2 areas; BH FDR.
    """
    kinds = {m["run"]: (m["sample_type"], m["group"]) for m in members}
    runs_a = sorted(r for r, (t, g) in kinds.items() if t == "sample" and g == group_a)
    runs_b = sorted(r for r, (t, g) in kinds.items() if t == "sample" and g == group_b)
    by_cid: dict[str, dict[str, float]] = {}
    blank_area: dict[str, float] = {}
    for m in members:
        if m["sample_type"] == "blank":
            blank_area[m["cid"]] = max(blank_area.get(m["cid"], 0.0), float(m["area"]))
        elif m["sample_type"] == "sample":
            by_cid.setdefault(m["cid"], {})[m["run"]] = float(m["area"])
    info = {c["cid"]: c for c in consensus}
    rows, removed_blank, removed_presence = [], 0, 0
    for cid, areas in by_cid.items():
        a_obs = [areas[r] for r in runs_a if r in areas]
        b_obs = [areas[r] for r in runs_b if r in areas]
        if max(len(a_obs) / max(len(runs_a), 1), len(b_obs) / max(len(runs_b), 1)) < min_presence:
            removed_presence += 1
            continue
        level = max(
            float(np.median(a_obs)) if a_obs else 0.0, float(np.median(b_obs)) if b_obs else 0.0
        )
        bl = blank_area.get(cid, 0.0)
        if bl > 0 and level / bl < blank_fold:
            removed_blank += 1
            continue
        fill = 0.5 * min(a_obs + b_obs)
        a = np.array([areas.get(r, fill) for r in runs_a])
        b = np.array([areas.get(r, fill) for r in runs_b])
        la, lb = np.log2(a), np.log2(b)
        if a.size >= 2 and b.size >= 2 and (la.std() > 0 or lb.std() > 0):
            p = float(stats.ttest_ind(lb, la, equal_var=False).pvalue)
        else:
            p = float("nan")
        rows.append(
            {
                "cid": cid,
                "mz": info[cid]["mz"],
                "rt_min": info[cid]["rt_min"],
                "log2_fc": round(math.log2(b.mean() / a.mean()), 3),
                "p_value": p,
                "mean_a": float(f"{a.mean():.4g}"),
                "mean_b": float(f"{b.mean():.4g}"),
                "imputed": int((a.size - len(a_obs)) + (b.size - len(b_obs))),
            }
        )
    tested = [r for r in rows if not math.isnan(r["p_value"])]
    q = bh_fdr([r["p_value"] for r in tested])
    for r, qv in zip(tested, q, strict=True):
        r["q_value"] = float(f"{qv:.3g}")
        r["p_value"] = float(f"{r['p_value']:.3g}")
    for r in rows:
        r.setdefault("q_value", None)
        if isinstance(r["p_value"], float) and math.isnan(r["p_value"]):
            r["p_value"] = None
    rows.sort(key=lambda r: (r["p_value"] is None, r["p_value"] or 1.0, -abs(r["log2_fc"])))
    return {
        "ranked": rows,
        "n_a": len(runs_a),
        "n_b": len(runs_b),
        "n_tested": len(tested),
        "removed_blank": removed_blank,
        "removed_presence": removed_presence,
        "rules": {
            "blank_fold": blank_fold,
            "min_presence": min_presence,
            "imputation": "half of the feature's smallest observed sample area",
            "test": "Welch t-test on log2 areas",
            "fdr": "Benjamini-Hochberg",
            "fold_change": f"log2(mean {group_b} / mean {group_a})",
        },
    }
