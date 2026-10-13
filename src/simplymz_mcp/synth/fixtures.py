"""The committed fixture set (plan M0.T5). Deterministic for a given seed."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import zlib
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from simplymz_mcp.synth.model import Faults, Planted, RunSpec, render
from simplymz_mcp.synth.writer import msp_text, write_mzml

DEFAULT_SEED = 20261004

POS_BASE: dict[str, float] = {
    "creatinine": 2.0e6,
    "niacinamide": 6.0e5,
    "carnitine": 1.5e6,
    "adenosine": 8.0e5,
    "theophylline": 4.0e5,
    "tyrosine": 1.2e6,
    "caffeine": 3.0e6,
    "phenylalanine": 2.5e6,
    "kynurenine": 3.5e5,
    "glutathione": 5.0e5,
    "tryptophan": 1.8e6,
    "hippuric_acid": 9.0e5,
}
# Group B / group A fold changes for the 5 planted differential compounds.
DIFFERENTIAL: dict[str, float] = {
    "adenosine": 4.0,
    "tyrosine": 0.25,
    "caffeine": 5.0,
    "kynurenine": 3.0,
    "hippuric_acid": 4.0,
}
NEG_BASE: dict[str, float] = {
    "citric_acid": 1.0e6,
    "uric_acid": 4.0e5,
    "tyrosine": 3.0e5,
    "hippuric_acid": 8.0e5,
    "triclosan": 6.0e5,
}
MS2_COMPOUNDS = (
    "creatinine",
    "adenosine",
    "tyrosine",
    "caffeine",
    "phenylalanine",
    "tryptophan",
    "hippuric_acid",
    "kynurenine",
)
LIBRARY_COMPOUNDS = (
    "creatinine",
    "niacinamide",
    "carnitine",
    "adenosine",
    "theophylline",
    "tyrosine",
    "caffeine",
    "phenylalanine",
    "glutathione",
    "tryptophan",
    "hippuric_acid",
)  # kynurenine deliberately absent
SYSTEM_CONTAMINANT = 4.0e5
FAULTS: dict[str, Faults] = {
    "rt_shift": Faults(rt_shift_min=0.30),
    "intensity_scale": Faults(intensity_scale=0.30),
    "mass_error": Faults(mass_error_ppm=8.0),
    "contaminant": Faults(contaminant_height=2.0e6),
    "dropout": Faults(dropout_start_scan=80, dropout_scans=12),
}


def _seed(base: int, name: str) -> int:
    return (base * 1_000_003 + zlib.crc32(name.encode())) % 2**32


def _pos(heights: dict[str, float]) -> tuple[Planted, ...]:
    return tuple(Planted(n, "[M+H]+", h) for n, h in heights.items())


def run_specs(seed: int = DEFAULT_SEED) -> dict[str, RunSpec]:
    specs: dict[str, RunSpec] = {}
    clean = RunSpec("clean_pos", "positive", _pos(POS_BASE), _seed(seed, "clean_pos"))
    specs["runs/clean_pos.mzML"] = clean
    specs["runs/clean_neg.mzML.gz"] = RunSpec(
        "clean_neg",
        "negative",
        tuple(Planted(n, "[M-H]-", h) for n, h in NEG_BASE.items()),
        _seed(seed, "clean_neg"),
    )
    specs["runs/ms2_dda.mzML.gz"] = RunSpec(
        "ms2_dda",
        "positive",
        _pos({n: POS_BASE[n] for n in MS2_COMPOUNDS}),
        _seed(seed, "ms2_dda"),
        ms2_compounds=MS2_COMPOUNDS,
    )
    for fault, f in FAULTS.items():
        specs[f"faults/{fault}.mzML.gz"] = replace(
            clean, name=f"fault_{fault}", seed=_seed(seed, fault), faults=f
        )
    specs["faults/carryover_blank.mzML.gz"] = RunSpec(
        "fault_carryover_blank",
        "positive",
        (),
        _seed(seed, "carryover"),
        faults=Faults(carryover_fraction=0.05, carryover_from=_pos(POS_BASE)),
    )
    specs.update(batch_specs(seed)[0])
    return specs


def batch_specs(seed: int = DEFAULT_SEED) -> tuple[dict[str, RunSpec], list[dict[str, Any]]]:
    """QC batch: 2 blanks, 3 pooled QCs, 3 x group A, 3 x group B."""
    rng = np.random.default_rng(_seed(seed, "batch"))
    order = [
        "blank_01",
        "qc_01",
        "a_01",
        "b_01",
        "a_02",
        "qc_02",
        "b_02",
        "a_03",
        "b_03",
        "qc_03",
        "blank_02",
    ]
    specs: dict[str, RunSpec] = {}
    sheet: list[dict[str, Any]] = []
    for inj, name in enumerate(order, start=1):
        kind = name.split("_")[0]
        sample_type = {"blank": "blank", "qc": "qc"}.get(kind, "sample")
        group = kind.upper() if sample_type == "sample" else ""
        heights: dict[str, float] = {}
        if sample_type != "blank":
            for comp, base in POS_BASE.items():
                fold = DIFFERENTIAL.get(comp, 1.0)
                if sample_type == "qc":  # pool = mean of the two groups, low technical CV
                    level = base * (1 + fold) / 2 * np.exp(0.03 * rng.standard_normal())
                else:
                    gmult = fold if group == "B" else 1.0
                    level = base * gmult * np.exp(0.10 * rng.standard_normal())
                heights[comp] = round(float(level), 1)
        planted = list(_pos(heights))
        planted.append(Planted("dehp_contaminant", "[M+H]+", SYSTEM_CONTAMINANT))
        jitter = float(round(0.005 * rng.standard_normal(), 4))
        planted = [replace(p, rt_min=_rt(p.compound) + jitter) for p in planted]
        fname = f"batch_qc/{name}.mzML.gz"
        specs[fname] = RunSpec(name, "positive", tuple(planted), _seed(seed, name))
        sheet.append(
            {
                "file": f"{name}.mzML.gz",
                "sample_type": sample_type,
                "group": group,
                "injection_order": inj,
            }
        )
    return specs, sheet


def _rt(name: str) -> float:
    from simplymz_mcp.synth.compounds import COMPOUNDS

    return COMPOUNDS[name].rt_min


def _sheet_csv(sheet: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(
        buf, fieldnames=["file", "sample_type", "group", "injection_order"], lineterminator="\n"
    )
    w.writeheader()
    w.writerows(sheet)
    return buf.getvalue()


def write_all(outdir: Path, seed: int = DEFAULT_SEED) -> dict[str, Any]:
    """Write every fixture + ground truth JSON + manifest. Returns the manifest."""
    manifest: dict[str, Any] = {"seed": seed, "files": {}}
    for rel, spec in run_specs(seed).items():
        scans, truth = render(spec)
        path = outdir / rel
        sha = write_mzml(scans, path, spec.name, spec.polarity)
        truth["file"] = rel
        truth["sha256"] = sha
        _write_text(_truth_path(path), json.dumps(truth, indent=1, sort_keys=True) + "\n")
        manifest["files"][rel] = {"sha256": sha, "content_digest": truth["content_digest"]}
    _, sheet = batch_specs(seed)
    for rel, text in {
        "batch_qc/sample_sheet.csv": _sheet_csv(sheet),
        "library/synthetic_library.msp": msp_text(list(LIBRARY_COMPOUNDS)),
    }.items():
        _write_text(outdir / rel, text)
        manifest["files"][rel] = {"sha256": hashlib.sha256(text.encode()).hexdigest()}
    _write_text(outdir / "MANIFEST.json", json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    return manifest


def _truth_path(path: Path) -> Path:
    name = path.name
    for ext in (".mzML.gz", ".mzML"):
        if name.endswith(ext):
            return path.with_name(name[: -len(ext)] + ".truth.json")
    raise ValueError(path)


def truth_path(path: Path) -> Path:
    return _truth_path(path)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
