"""Pure-numpy rendering of synthetic LC-MS runs with recorded ground truth.

Peak model: each planted compound elutes as a Gaussian in time,
``I(t) = height * exp(-(t - rt)^2 / (2 sigma^2))`` with ``sigma = fwhm / 2.3548``,
for every isotopologue (scaled by its relative abundance). The analytic area of the
monoisotopic EIC is ``height * sigma * sqrt(2*pi)`` (counts x min).
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import numpy as np

from simplymz_mcp.synth.compounds import ADDUCTS, COMPOUNDS
from simplymz_mcp.synth.elements import isotope_pattern

GENERATOR_VERSION = "1"
FWHM_TO_SIGMA = 1.0 / (2.0 * math.sqrt(2.0 * math.log(2.0)))
Polarity = Literal["positive", "negative"]


@dataclass(frozen=True)
class Planted:
    compound: str
    adduct: str
    height: float
    rt_min: float | None = None  # override the compound's default RT


@dataclass(frozen=True)
class Faults:
    rt_shift_min: float = 0.0
    intensity_scale: float = 1.0
    mass_error_ppm: float = 0.0
    contaminant_height: float = 0.0
    carryover_fraction: float = 0.0
    carryover_from: tuple[Planted, ...] = ()
    dropout_start_scan: int | None = None  # 0-based MS1 index
    dropout_scans: int = 0


@dataclass(frozen=True)
class RunSpec:
    name: str
    polarity: Polarity
    planted: tuple[Planted, ...]
    seed: int
    rt_start_min: float = 0.0
    rt_end_min: float = 10.0
    scan_interval_min: float = 0.05
    mz_min: float = 50.0
    mz_max: float = 1000.0
    noise_peaks_per_scan: int = 10
    noise_level: float = 300.0
    intensity_noise_rel: float = 0.02
    mz_noise_ppm: float = 1.0
    min_intensity: float = 50.0
    ms2_compounds: tuple[str, ...] = ()
    faults: Faults = field(default_factory=Faults)


@dataclass
class Scan:
    index: int
    native_id: str
    rt_min: float
    ms_level: int
    mz: np.ndarray
    intensity: np.ndarray
    precursor_mz: float | None = None
    precursor_scan_id: str | None = None
    precursor_charge: int | None = None


def _effective(spec: RunSpec) -> list[dict[str, Any]]:
    """Resolve planted compounds + faults into concrete elution parameters."""
    f = spec.faults
    items: list[tuple[Planted, float, str]] = [
        (p, f.intensity_scale, "planted") for p in spec.planted
    ]
    if f.contaminant_height > 0:
        items.append(
            (
                Planted("dehp_contaminant", _default_adduct(spec.polarity), f.contaminant_height),
                1.0,
                "contaminant",
            )
        )
    for p in f.carryover_from:
        items.append((p, f.carryover_fraction, "carryover"))
    out = []
    for p, scale, role in items:
        c = COMPOUNDS[p.compound]
        delta, sign = ADDUCTS[p.adduct]
        if (sign > 0) != (spec.polarity == "positive"):
            raise ValueError(f"{p.adduct} does not match {spec.polarity} polarity")
        neutral_formula = c.formula
        pattern = isotope_pattern(neutral_formula)
        mono_neutral = pattern[0][0]
        ion_mz = mono_neutral + delta
        sigma = c.fwhm_min * FWHM_TO_SIGMA
        height = p.height * scale
        rt = (p.rt_min if p.rt_min is not None else c.rt_min) + f.rt_shift_min
        out.append(
            {
                "name": c.name,
                "formula": c.formula,
                "adduct": p.adduct,
                "role": role,
                "ion_mz": round(ion_mz, 6),
                "rt_min": round(rt, 6),
                "fwhm_min": c.fwhm_min,
                "sigma_min": round(sigma, 9),
                "height_counts": round(height, 3),
                "area_counts_min": round(height * sigma * math.sqrt(2 * math.pi), 3),
                "isotopes": [{"mz": round(m + delta, 6), "rel": round(a, 6)} for m, a in pattern],
            }
        )
    return out


def _default_adduct(polarity: Polarity) -> str:
    return "[M+H]+" if polarity == "positive" else "[M-H]-"


def render(spec: RunSpec) -> tuple[list[Scan], dict[str, Any]]:
    rng = np.random.default_rng(spec.seed)
    peaks = _effective(spec)
    f = spec.faults
    n_ms1 = round((spec.rt_end_min - spec.rt_start_min) / spec.scan_interval_min) + 1
    times = spec.rt_start_min + np.arange(n_ms1) * spec.scan_interval_min
    dropout = set()
    if f.dropout_start_scan is not None:
        dropout = set(range(f.dropout_start_scan, f.dropout_start_scan + f.dropout_scans))
    ms2_set = set(spec.ms2_compounds)
    # MS2 triggered at the 3 MS1 scans closest to each MS2 compound's apex.
    ms2_triggers: dict[int, list[dict[str, Any]]] = {}
    for p in peaks:
        if p["name"] in ms2_set and p["role"] == "planted":
            apex = int(np.argmin(np.abs(times - p["rt_min"])))
            for i in (apex - 1, apex, apex + 1):
                if 0 <= i < n_ms1 and i not in dropout:
                    ms2_triggers.setdefault(i, []).append(p)

    scans: list[Scan] = []
    ppm_err = f.mass_error_ppm
    for i, t in enumerate(times):
        native = f"scan={len(scans) + 1}"
        if i in dropout:
            mz = np.empty(0)
            inten = np.empty(0, dtype=np.float32)
        else:
            mzs: list[float] = []
            ints: list[float] = []
            for p in peaks:
                g = math.exp(-((t - p["rt_min"]) ** 2) / (2 * p["sigma_min"] ** 2))
                for iso in p["isotopes"]:
                    val = p["height_counts"] * iso["rel"] * g
                    val *= 1.0 + spec.intensity_noise_rel * rng.standard_normal()
                    if val >= spec.min_intensity:
                        jitter = spec.mz_noise_ppm * rng.standard_normal()
                        mzs.append(iso["mz"] * (1 + (ppm_err + jitter) * 1e-6))
                        ints.append(val)
            k = spec.noise_peaks_per_scan
            mzs.extend(rng.uniform(spec.mz_min, spec.mz_max, k).tolist())
            ints.extend((spec.min_intensity + rng.exponential(spec.noise_level, k)).tolist())
            order = np.argsort(mzs)
            mz = np.round(np.asarray(mzs)[order], 6)
            inten = np.round(np.asarray(ints)[order], 1).astype(np.float32)
        scans.append(Scan(len(scans), native, round(float(t), 6), 1, mz, inten))
        for p in ms2_triggers.get(i, []):
            g = math.exp(-((t - p["rt_min"]) ** 2) / (2 * p["sigma_min"] ** 2))
            prec_int = p["height_counts"] * g
            frags = COMPOUNDS[p["name"]].fragments
            fm = [fr.mz for fr in frags] + [p["ion_mz"]]
            fi = [fr.rel_intensity * prec_int * 0.5 for fr in frags] + [prec_int * 0.05]
            fm += rng.uniform(50, p["ion_mz"], 3).tolist()
            fi += (spec.min_intensity + rng.exponential(spec.noise_level, 3)).tolist()
            fi = [v * (1 + spec.intensity_noise_rel * rng.standard_normal()) for v in fi]
            order = np.argsort(fm)
            scans.append(
                Scan(
                    len(scans),
                    f"scan={len(scans) + 1}",
                    round(float(t) + 0.005, 6),
                    2,
                    np.round(np.asarray(fm)[order], 6),
                    np.round(np.asarray(fi)[order], 1).astype(np.float32),
                    precursor_mz=p["ion_mz"],
                    precursor_scan_id=native,
                    precursor_charge=1,
                )
            )

    truth = {
        "generator_version": GENERATOR_VERSION,
        "name": spec.name,
        "seed": spec.seed,
        "polarity": spec.polarity,
        "n_ms1": n_ms1,
        "n_ms2": sum(1 for s in scans if s.ms_level == 2),
        "rt_range_min": [float(times[0]), round(float(times[-1]), 6)],
        "scan_interval_min": spec.scan_interval_min,
        "noise_level_counts": spec.noise_level,
        "faults": _faults_dict(f),
        "dropout_ms1_indices": sorted(dropout),
        "compounds": peaks,
        "ms2_compounds": sorted(ms2_set),
        "content_digest": content_digest(scans),
    }
    return scans, truth


def _faults_dict(f: Faults) -> dict[str, Any]:
    d = asdict(f)
    d["carryover_from"] = [p["compound"] for p in d["carryover_from"]]
    return d


def content_digest(scans: list[Scan]) -> str:
    """Platform-independent digest of the decoded content (ids, times, arrays)."""
    h = hashlib.sha256()
    for s in scans:
        h.update(
            json.dumps(
                [
                    s.native_id,
                    s.rt_min,
                    s.ms_level,
                    s.precursor_mz,
                    np.round(s.mz, 6).tolist(),
                    np.round(s.intensity.astype(float), 1).tolist(),
                ]
            ).encode()
        )
    return h.hexdigest()
