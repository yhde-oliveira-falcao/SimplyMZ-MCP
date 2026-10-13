"""M4.T1-T3: adducts, formula enumeration, isotope prediction and fit vs independent oracles."""

from __future__ import annotations

import numpy as np
import pytest

from simplymz_mcp.annotation.adducts import ADDUCTS, get_adduct, valid_for
from simplymz_mcp.annotation.formulas import enumerate_formulas, hill, passes_rules, rdbe
from simplymz_mcp.annotation.isotopes import fit, observe, predict
from simplymz_mcp.annotation.propose import rank
from simplymz_mcp.core.errors import ErrorCode, SimplyMZError
from simplymz_mcp.synth.elements import (
    ELECTRON_MASS,
    ISOTOPES,
    isotope_pattern,
    monoisotopic_mass,
    parse_formula,
)
from tests.oracle.compounds import ORACLE, elements_for

H = ISOTOPES["H"][0][0]
NA = ISOTOPES["Na"][0][0]
CL = ISOTOPES["Cl"][0][0]


# ---------- T1 adducts ----------


@pytest.mark.parametrize("formula", ["C8H10N4O2", "C6H12O6", "C10H17N3O6S"])
def test_adduct_masses_match_oracle(formula: str) -> None:
    m = monoisotopic_mass(formula)
    e = ELECTRON_MASS
    expected = {
        "[M+H]+": m + H - e,
        "[M+Na]+": m + NA - e,
        "[M-H]-": m - H + e,
        "[M+Cl]-": m + CL + e,
        "[M+2H]2+": (m + 2 * H - 2 * e) / 2,
        "[2M+H]+": 2 * m + H - e,
    }
    for name, mz in expected.items():
        assert ADDUCTS[name].ion_mz(m) == pytest.approx(mz, abs=2e-6), name
        assert ADDUCTS[name].neutral(mz) == pytest.approx(m, abs=2e-6), name


def test_polarity_mismatch_names_valid_adducts() -> None:
    with pytest.raises(SimplyMZError) as ei:
        get_adduct("[M+H]+", "negative")
    assert ei.value.code == ErrorCode.POLARITY_MISMATCH
    assert "[M-H]-" in ei.value.hint and "[M+Cl]-" in ei.value.hint
    assert all(ADDUCTS[a].charge < 0 for a in valid_for("negative"))
    with pytest.raises(SimplyMZError) as ei:
        get_adduct("[M+Xe]+")
    assert ei.value.code == ErrorCode.INVALID_ARGUMENT


# ---------- T2 formulas ----------


def test_hill_order_and_rdbe() -> None:
    assert hill({"C": 12, "H": 7, "Cl": 3, "O": 2}) == "C12H7Cl3O2"
    assert rdbe({"C": 6, "H": 6}) == 4  # benzene
    assert not passes_rules({"C": 2, "H": 7})  # negative RDBE / odd electron
    assert passes_rules({"C": 3, "H": 8, "N": 1, "O": 6, "P": 1})  # phosphoserine


@pytest.mark.parametrize("name", sorted(ORACLE))
def test_true_formula_enumerated_at_5ppm(name: str) -> None:
    f = ORACLE[name]
    m = monoisotopic_mass(f)
    for err_ppm in (-3.0, 0.0, 3.0):
        cands = enumerate_formulas(m * (1 + err_ppm * 1e-6), 5.0, elements_for(f))
        assert f in [c.formula for c in cands], (name, err_ppm)
        assert [abs(c.ppm) for c in cands] == sorted(abs(c.ppm) for c in cands)


def test_element_spec_validation() -> None:
    with pytest.raises(ValueError):
        enumerate_formulas(194.08, 5, "NOPS")
    with pytest.raises(ValueError):
        enumerate_formulas(194.08, 5, "CHXe")


# ---------- T3 isotopes ----------


def test_m_plus_1_matches_exact_analytic_value() -> None:
    a1 = {
        "C": (0.0107, 0.9893),
        "H": (0.000115, 0.999885),
        "N": (0.00364, 0.99636),
        "O": (0.00038, 0.99757),
    }
    n = {"C": 8, "H": 10, "N": 4, "O": 2}
    exact = sum(n[e] * a1[e][0] / a1[e][1] for e in n)
    assert predict(n)[1][1] == pytest.approx(exact, rel=1e-6)


@pytest.mark.parametrize("name", sorted(ORACLE))
def test_prediction_agrees_with_oracle_pattern(name: str) -> None:
    f = ORACLE[name]
    ours = predict(dict(parse_formula(f)), 3)
    ref = isotope_pattern(f, 3)
    for k in (1, 2):
        assert ours[k][1] == pytest.approx(ref[k][1], rel=2e-3, abs=1e-5), (name, k)
        assert ours[k][0] == pytest.approx(ref[k][0] - ref[0][0], abs=2e-4)


def test_fit_rejects_impossible_pattern() -> None:
    obs = [1.0] + [a for _, a in isotope_pattern("C8H10N4O2", 3)[1:]]
    assert not fit({"C": 8, "H": 10, "N": 4, "O": 2}, obs)["rejected"]
    assert fit({"C": 4, "H": 8, "Cl": 2, "N": 2}, obs)["rejected"]  # Cl2 needs a big M+2


def test_observe_on_fixture_apex() -> None:
    from simplymz_mcp.io.mzml import read_mzml
    from tests.conftest import FIXTURES

    run = read_mzml(FIXTURES / "runs" / "clean_pos.mzML")
    mz_c = monoisotopic_mass("C8H10N4O2") + H - ELECTRON_MASS
    ms1 = np.flatnonzero(run.scans.ms_level == 1)
    i = ms1[int(np.argmin(np.abs(run.scans.rt_min[ms1] - 4.40)))]
    obs = observe(*run.peaks(int(i)), mz_c)
    assert obs is not None and obs[1] == pytest.approx(
        predict({"C": 8, "H": 10, "N": 4, "O": 2})[1][1], rel=0.1
    )


def test_isotope_ranking_puts_truth_first_for_90pct_below_400_da() -> None:
    rng = np.random.default_rng(1)
    hits = total = 0
    for f in ORACLE.values():
        m = monoisotopic_mass(f)
        if m >= 400:
            continue
        total += 1
        cands = enumerate_formulas(m * (1 + rng.normal(0, 1e-6)), 5.0, elements_for(f))
        obs = [1.0] + [a * (1 + rng.normal(0, 0.02)) for _, a in isotope_pattern(f, 3)[1:]]
        hits += rank(cands, obs)[0]["formula"] == f
    assert total >= 20 and hits / total >= 0.90
