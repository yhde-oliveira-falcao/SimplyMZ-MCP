"""M0.T5: synthetic data generator: determinism, readability, ground-truth validity."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pytest
from jsonschema import Draft202012Validator
from pyteomics import mass, mzml

from simplymz_mcp.synth.compounds import ADDUCTS, COMPOUNDS
from simplymz_mcp.synth.elements import (
    ELECTRON_MASS,
    ISOTOPES,
    isotope_pattern,
    monoisotopic_mass,
    parse_formula,
)
from simplymz_mcp.synth.fixtures import FAULTS, run_specs, truth_path, write_all
from simplymz_mcp.synth.model import render
from tests.conftest import FIXTURES

SCHEMA = json.loads((Path(__file__).parents[1] / "schemas" / "truth.schema.json").read_text())
MZML = sorted(p for p in FIXTURES.rglob("*") if p.name.endswith((".mzML", ".mzML.gz")))


def _open(path: Path):
    return gzip.open(path, "rb") if path.name.endswith(".gz") else open(path, "rb")


# ---------- element table vs an independent source ----------


@pytest.mark.parametrize("element", sorted(ISOTOPES))
def test_element_masses_agree_with_pyteomics_nist_table(element: str) -> None:
    for m, a in ISOTOPES[element]:
        iso = round(m)
        ref_m, ref_a = mass.nist_mass[element][iso]
        assert abs(m - ref_m) < 5e-6  # pyteomics stores some masses to fewer digits
        assert abs(a - ref_a) < 1e-6


def test_known_monoisotopic_masses() -> None:
    # Literature values (monoisotopic, neutral): caffeine 194.080376, glucose 180.063388.
    assert monoisotopic_mass("C8H10N4O2") == pytest.approx(194.080376, abs=2e-6)
    assert monoisotopic_mass("C6H12O6") == pytest.approx(180.063388, abs=2e-6)
    assert pytest.approx(5.48579909e-4) == ELECTRON_MASS


def test_caffeine_protonated_mz() -> None:
    assert COMPOUNDS["caffeine"].ion_mz("[M+H]+") == pytest.approx(195.087652, abs=2e-6)
    assert ADDUCTS["[M-H]-"][1] == -1


@pytest.mark.parametrize("bad", ["", "c8h10", "C8Xx2", "C8H10)"])
def test_bad_formulas_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_formula(bad)


def test_isotope_pattern_carbon_rule_and_chlorine() -> None:
    # M+1/M+0 for C20 is dominated by 13C: 20 * 0.0107/0.9893 = 0.2163
    pat = isotope_pattern("C20")
    assert pat[1][1] == pytest.approx(20 * 0.0107 / 0.9893, rel=1e-3)
    assert pat[1][0] - pat[0][0] == pytest.approx(1.003355, abs=1e-5)
    # One Cl: M+2/M+0 = 0.2424/0.7576
    cl = isotope_pattern("Cl")
    assert cl[1][1] == pytest.approx(0.2424 / 0.7576, rel=1e-6)


def test_m_plus_1_ratio_matches_exact_analytic_formula() -> None:
    # Only single +1 substitutions reach nominal M+1, so the ratio is exactly
    # sum(n_i * a1_i / a0_i). (pyteomics' isotopologues() drops 2H/17O by default
    # via isotope_threshold=5e-4, so it is not used as the oracle here.)
    n = {"C": 11, "H": 12, "N": 2, "O": 2}  # tryptophan
    a1 = {
        "C": (0.0107, 0.9893),
        "H": (0.000115, 0.999885),
        "N": (0.00364, 0.99636),
        "O": (0.00038, 0.99757),
    }
    expected = sum(n[e] * a1[e][0] / a1[e][1] for e in n)
    assert expected == pytest.approx(0.1284216, abs=1e-7)
    assert isotope_pattern("C11H12N2O2")[1][1] == pytest.approx(expected, rel=1e-9)


# ---------- determinism ----------


def test_same_seed_gives_identical_bytes(tmp_path: Path) -> None:
    a = write_all(tmp_path / "a", seed=7)
    b = write_all(tmp_path / "b", seed=7)
    assert a == b
    other = render(run_specs(8)["runs/clean_pos.mzML"])[1]["content_digest"]
    assert other != a["files"]["runs/clean_pos.mzML"]["content_digest"]


def test_committed_fixtures_match_generator() -> None:
    committed = json.loads((FIXTURES / "MANIFEST.json").read_text())
    for rel, spec in run_specs(committed["seed"]).items():
        _, truth = render(spec)
        assert truth["content_digest"] == committed["files"][rel]["content_digest"], rel


def test_fixture_total_size_under_5mb() -> None:
    total = sum(p.stat().st_size for p in FIXTURES.rglob("*") if p.is_file())
    assert total <= 5 * 1024 * 1024


# ---------- files parse and agree with ground truth ----------


@pytest.mark.parametrize("path", MZML, ids=lambda p: p.name)
def test_fixture_parses_and_matches_truth(path: Path) -> None:
    truth = json.loads(truth_path(path).read_text())
    Draft202012Validator(SCHEMA).validate(truth)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == truth["sha256"]
    with _open(path) as fh:
        spectra = list(mzml.read(fh))
    levels = [s["ms level"] for s in spectra]
    assert levels.count(1) == truth["n_ms1"] and levels.count(2) == truth["n_ms2"]
    pol_key = "positive scan" if truth["polarity"] == "positive" else "negative scan"
    assert all(pol_key in s for s in spectra)
    ms1 = [s for s in spectra if s["ms level"] == 1]
    for idx in truth["dropout_ms1_indices"]:
        assert len(ms1[idx]["m/z array"]) == 0
    for s in spectra:
        if s["ms level"] == 2:
            prec = s["precursorList"]["precursor"][0]
            assert prec["spectrumRef"].startswith("scan=")


def test_planted_apex_and_mz_visible_in_clean_run() -> None:
    path = FIXTURES / "runs" / "clean_pos.mzML"
    truth = json.loads(truth_path(path).read_text())
    ms1 = [s for s in mzml.read(str(path)) if s["ms level"] == 1]
    rts = np.array([s["scanList"]["scan"][0]["scan start time"] for s in ms1])
    for c in truth["compounds"]:
        eic = []
        for s in ms1:
            mz = s["m/z array"]
            win = np.abs(mz - c["ion_mz"]) <= c["ion_mz"] * 10e-6
            eic.append(float(s["intensity array"][win].sum()))
        apex = rts[int(np.argmax(eic))]
        assert abs(apex - c["rt_min"]) <= truth["scan_interval_min"] + 1e-9, c["name"]
        assert max(eic) == pytest.approx(c["height_counts"], rel=0.08)


def test_analytic_area_formula() -> None:
    truth = json.loads(truth_path(FIXTURES / "runs" / "clean_pos.mzML").read_text())
    c = truth["compounds"][0]
    assert c["area_counts_min"] == pytest.approx(
        c["height_counts"] * c["sigma_min"] * math.sqrt(2 * math.pi), rel=1e-6
    )


def test_fault_variants_record_their_faults() -> None:
    for fault in FAULTS:
        truth = json.loads(truth_path(FIXTURES / "faults" / f"{fault}.mzML.gz").read_text())
        assert (
            truth["faults"]
            != json.loads(truth_path(FIXTURES / "faults" / "carryover_blank.mzML.gz").read_text())[
                "faults"
            ]
        )
    mass_err = json.loads(truth_path(FIXTURES / "faults" / "mass_error.mzML.gz").read_text())
    assert mass_err["faults"]["mass_error_ppm"] == 8.0


def test_mass_error_fault_shifts_observed_mz() -> None:
    path = FIXTURES / "faults" / "mass_error.mzML.gz"
    truth = json.loads(truth_path(path).read_text())
    c = max(truth["compounds"], key=lambda x: x["height_counts"])
    with _open(path) as fh:
        ms1 = [s for s in mzml.read(fh) if s["ms level"] == 1]
    best = None
    for s in ms1:
        mz, it = s["m/z array"], s["intensity array"]
        win = np.abs(mz - c["ion_mz"]) <= c["ion_mz"] * 30e-6
        if win.any() and (best is None or it[win].max() > best[1]):
            j = np.argmax(np.where(win, it, -1))
            best = (mz[j], it[j])
    assert best is not None
    ppm = (best[0] - c["ion_mz"]) / c["ion_mz"] * 1e6
    assert 5.0 < ppm < 11.0


def test_batch_sheet_and_library() -> None:
    sheet = (FIXTURES / "batch_qc" / "sample_sheet.csv").read_text().splitlines()
    assert sheet[0] == "file,sample_type,group,injection_order"
    assert len(sheet) == 12
    types = [row.split(",")[1] for row in sheet[1:]]
    assert types.count("blank") == 2 and types.count("qc") == 3 and types.count("sample") == 6
    msp = (FIXTURES / "library" / "synthetic_library.msp").read_text()
    assert "Name: kynurenine" not in msp and "Name: caffeine" in msp
    assert msp.count("licence=") == msp.count("Name:")


def test_polarity_mismatch_rejected() -> None:
    from dataclasses import replace

    spec = run_specs()["runs/clean_pos.mzML"]
    with pytest.raises(ValueError):
        render(replace(spec, polarity="negative"))
