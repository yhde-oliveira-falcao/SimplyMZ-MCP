"""Fault-injection batches for QC validation (plan M2.T5).

A case = the committed clean QC batch with one run replaced by a faulty version whose
fault size is chosen so the *expected* metric equals ``multiple`` x the metric's fail
threshold. Mapping from metric to fault parameter is analytic where possible.
"""

from __future__ import annotations

import functools
import math
from dataclasses import dataclass, replace

import numpy as np
from scipy.optimize import brentq

from simplymz_mcp.synth.fixtures import DEFAULT_SEED, batch_specs
from simplymz_mcp.synth.model import Faults, Planted, RunSpec, render

# fault -> (primary metric, run that receives the fault, metrics allowed to leave "pass")
FAULT_CASES: dict[str, tuple[str, str, frozenset[str]]] = {
    "rt_shift": ("rt_drift_min", "qc_02", frozenset({"rt_drift_min"})),
    "mass_error": ("mass_error_ppm", "qc_02", frozenset({"mass_error_ppm"})),
    "intensity_scale": (
        "tic_cv_qc_pct",
        "qc_02",
        frozenset({"tic_cv_qc_pct", "qc_feature_cv_pct", "intensity_trend_pct_per_injection"}),
    ),
    "carryover": (
        "blank_carryover_pct",
        "blank_02",
        frozenset({"blank_carryover_pct", "blank_contamination_pct"}),
    ),
    "contaminant": ("blank_contamination_pct", "blank_02", frozenset({"blank_contamination_pct"})),
    "dropout": (
        "scan_dropouts",
        "qc_02",
        frozenset(
            {
                "scan_dropouts",
                "missingness_pct",
                "tic_cv_qc_pct",
                "qc_feature_cv_pct",
                "intensity_trend_pct_per_injection",
            }
        ),
    ),
}


@dataclass(frozen=True)
class FaultCase:
    fault: str
    multiple: float
    metric: str
    target_value: float
    run_name: str
    spec: RunSpec


def _cv3(f: float) -> float:
    a = np.array([1.0, 1.0, f])
    return float(a.std(ddof=1) / a.mean() * 100)


def scale_for_cv(target_pct: float) -> float:
    """Scale factor f > 1 for one of three QCs so CV([1, 1, f]) = target (%)."""
    if target_pct <= 0:
        return 1.0
    return float(brentq(lambda f: _cv3(f) - target_pct, 1.0, 1e4))


def _tic(spec: RunSpec) -> float:
    scans, _ = render(spec)
    return float(sum(float(s.intensity.sum(dtype=np.float64)) for s in scans if s.ms_level == 1))


@functools.lru_cache(maxsize=4)
def _contaminant_model(seed: int) -> tuple[float, float, float]:
    specs = {k.split("/")[-1].split(".")[0]: v for k, v in batch_specs(seed)[0].items()}
    blank = specs["blank_02"]
    base = _tic(blank)
    per_unit = (_tic(replace(blank, faults=Faults(contaminant_height=1e6))) - base) / 1e6
    samples = [_tic(v) for k, v in specs.items() if k.startswith(("a_", "b_"))]
    return base, per_unit, float(np.median(samples))


def make_case(fault: str, multiple: float, fail: float, seed: int = DEFAULT_SEED) -> FaultCase:
    metric, run_name, _ = FAULT_CASES[fault]
    specs = {k.split("/")[-1].split(".")[0]: v for k, v in batch_specs(seed)[0].items()}
    spec = specs[run_name]
    target = multiple * fail
    if fault == "rt_shift":
        faults = Faults(rt_shift_min=target)
    elif fault == "mass_error":
        faults = Faults(mass_error_ppm=target)
    elif fault == "intensity_scale":
        faults = Faults(intensity_scale=scale_for_cv(target))
    elif fault == "carryover":
        prev = specs["qc_03"]  # blank_02 follows qc_03
        carried = tuple(p for p in prev.planted if p.compound != "dehp_contaminant")
        faults = Faults(carryover_fraction=target / 100, carryover_from=carried)
    elif fault == "contaminant":
        base, per_unit, med = _contaminant_model(seed)
        height = max((target / 100 * med - base) / per_unit, 0.0)
        faults = Faults(contaminant_height=height)
    elif fault == "dropout":
        faults = Faults(dropout_start_scan=80, dropout_scans=math.floor(target))
    else:  # pragma: no cover
        raise KeyError(fault)
    return FaultCase(
        fault,
        multiple,
        metric,
        target,
        run_name,
        replace(spec, name=f"{run_name}_{fault}_{multiple:g}x", faults=faults),
    )


__all__ = ["FAULT_CASES", "FaultCase", "Planted", "make_case", "scale_for_cv"]
