"""M4.T6: every rule in the confidence table is exercised; Level 1 is unreachable."""

from __future__ import annotations

from typing import Any

import pytest

from simplymz_mcp.annotation.confidence import RULES, RULESET_VERSION, evaluate, validate_feature
from simplymz_mcp.core.errors import SimplyMZError


def _formula(cands: list[tuple[str, bool]], iso: bool = True, uneq: bool = False) -> dict:
    return {
        "op": "propose_formulas",
        "result": {
            "data": {
                "mz": 195.0877,
                "isotope_data": iso,
                "unequivocal": uneq,
                "candidates": [{"formula": f, "rejected": r} for f, r in cands],
            }
        },
    }


def _match(hits: list[dict[str, Any]]) -> dict:
    return {
        "op": "match_spectrum",
        "result": {"data": {"query": {"precursor_mz": 195.0877}, "hits": hits}},
    }


def _hit(score: float, passes: bool, formula: str = "C8H10N4O2") -> dict:
    return {
        "name": "caffeine",
        "formula": formula,
        "score": score,
        "passes": passes,
        "n_matched": 2,
        "licence": "CC0",
    }


def test_each_rule_fires() -> None:
    cases = {
        "L2-library": [_formula([("C8H10N4O2", False)]), _match([_hit(0.95, True)])],
        "L3-library-conflict": [
            _formula([("C7H6N8O", False), ("C8H10N4O2", True)]),
            _match([_hit(0.95, True)]),
        ],
        "L3-near-miss": [_match([_hit(0.6, False)])],
        "L4-formula": [_formula([("C8H10N4O2", False)], uneq=True)],
        "L5-mass": [_formula([("A", False), ("B", False)])],
    }
    for rule, records in cases.items():
        assert evaluate(records)["rule"] == rule
    assert {r[0] for r in RULES} == set(cases)


def test_best_level_wins_and_identity_only_at_level_2() -> None:
    both = evaluate([_formula([("C8H10N4O2", False)], uneq=True), _match([_hit(0.95, True)])])
    assert both["level"] == 2 and both["identity"] == "caffeine"
    assert both["ruleset_version"] == RULESET_VERSION
    four = evaluate([_formula([("C8H10N4O2", False)], uneq=True)])
    assert four["level"] == 4 and four["identity"] is None


def test_library_match_without_formula_evidence_is_level_2() -> None:
    assert evaluate([_match([_hit(0.9, True)])])["level"] == 2


def test_weak_hit_is_only_mass_level() -> None:
    assert evaluate([_match([_hit(0.3, False)])])["level"] == 5


def test_level_1_is_never_assigned() -> None:
    assert min(r[1] for r in RULES) == 2


def _bound_records() -> list[dict]:
    formula = _formula([("C8H10N4O2", False)])
    formula["result"]["data"]["adduct"] = "[M+H]+"
    match = _match([{**_hit(0.95, True), "adduct": "[M+H]+"}])
    for rec in (formula, match):
        rec["result"]["data"]["feature_context"] = {
            "run_sha256": "same-run",
            "rt_min": 4.4,
            "polarity": 1,
        }
    return [formula, match]


def test_matching_feature_context_is_accepted() -> None:
    records = _bound_records()
    records[1]["result"]["data"]["feature_context"]["rt_min"] = 4.45
    validate_feature(records)


@pytest.mark.parametrize(
    ("field", "value"),
    [("run_sha256", "other-run"), ("rt_min", 7.0), ("polarity", -1)],
)
def test_same_mz_does_not_allow_other_features(field: str, value: object) -> None:
    records = _bound_records()
    records[1]["result"]["data"]["feature_context"][field] = value
    with pytest.raises(SimplyMZError):
        validate_feature(records)


def test_mass_only_or_legacy_evidence_cannot_be_combined() -> None:
    records = _bound_records()
    del records[0]["result"]["data"]["feature_context"]
    with pytest.raises(SimplyMZError):
        validate_feature(records)
    validate_feature([records[0]])  # standalone mass/formula evidence remains supported


@pytest.mark.parametrize("adduct", ["[M+Na]+", "", None])
def test_library_adduct_must_match_formula(adduct: str | None) -> None:
    records = _bound_records()
    records[1]["result"]["data"]["hits"][0]["adduct"] = adduct
    with pytest.raises(SimplyMZError):
        validate_feature(records)


def test_library_only_hit_cannot_conflict_with_scan_polarity() -> None:
    records = _bound_records()
    records[1]["result"]["data"]["hits"][0]["adduct"] = "[M-H]-"
    with pytest.raises(SimplyMZError):
        validate_feature([records[1]])
