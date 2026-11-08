"""Rule-based identification confidence (plan M4.T6).

Levels follow Schymanski et al., Environ. Sci. Technol. 2014, 48, 2097-2098:
1 confirmed structure (reference standard) · 2 probable structure (library match) ·
3 tentative candidate(s) · 4 unequivocal molecular formula · 5 exact mass of interest.
Input is evidence (ledger records) only; nothing can set a level directly. Level 1 is
never assigned in v0.1 because there is no reference-standard evidence type yet.
"""

from __future__ import annotations

from typing import Any

from simplymz_mcp.annotation.adducts import get_adduct
from simplymz_mcp.core.errors import ErrorCode, SimplyMZError

RULESET_VERSION = "simplymz-confidence-2"
NEAR_MISS_SCORE = 0.5
SAME_FEATURE_PPM = 10.0
LABELS = {
    2: "probable structure (library spectrum match)",
    3: "tentative candidate",
    4: "unequivocal molecular formula",
    5: "exact mass of interest",
}
RULES = [
    (
        "L2-library",
        2,
        "match_spectrum passed (score and matched-peak thresholds, precursor "
        "gate) and the hit formula is consistent with any isotope-filtered formula evidence",
    ),
    (
        "L3-library-conflict",
        3,
        "match_spectrum passed but its formula conflicts with the "
        "isotope-filtered formula evidence",
    ),
    (
        "L3-near-miss",
        3,
        f"best library candidate scored >= {NEAR_MISS_SCORE} but below the pass thresholds",
    ),
    ("L4-formula", 4, "propose_formulas with isotope data left exactly one consistent formula"),
    ("L5-mass", 5, "an exact mass was measured"),
]
SUPPORTED_OPS = ("propose_formulas", "match_spectrum")


def evidence_mz(rec: dict[str, Any]) -> float:
    data = rec["result"]["data"]
    if rec["op"] == "propose_formulas":
        return float(data["mz"])
    return float(data["query"]["precursor_mz"])


SAME_FEATURE_RT_MIN = 0.15


def validate_feature(records: list[dict[str, Any]]) -> None:
    """Fail closed when evidence cannot be attributed to one chromatographic feature.

    Single mass-only formula calls remain useful, but cannot be combined with other
    evidence without a run and selected scan. Old ledger records must be recomputed.
    """
    contexts = [r["result"]["data"].get("feature_context") for r in records]

    def reject(message: str) -> None:
        raise SimplyMZError(
            ErrorCode.INVALID_ARGUMENT,
            message,
            "Recompute evidence for one run and peak (give run_handle and rt_min); "
            "use compatible polarity and adducts.",
        )

    if len(records) > 1:
        if any(not c for c in contexts):
            reject("Combined evidence needs run and retention-time context on every record.")
        bound = [c for c in contexts if c]
        if len({c["run_sha256"] for c in bound}) != 1:
            reject("Evidence refers to different runs.")
        rts = [c["rt_min"] for c in bound]
        if max(rts) - min(rts) > SAME_FEATURE_RT_MIN:
            reject("Evidence refers to different retention-time peaks.")
        if len({c["polarity"] for c in bound if c["polarity"]}) > 1:
            reject("Evidence has conflicting scan polarities.")

    adducts = {r["result"]["data"]["adduct"] for r in records if r["op"] == "propose_formulas"}
    if len(adducts) > 1:
        reject("Formula evidence uses different adducts.")
    for r, context in zip(records, contexts, strict=True):
        if r["op"] != "match_spectrum":
            continue
        passing = [h for h in r["result"]["data"].get("hits", []) if h["passes"]]
        if not passing:
            continue
        hit_adduct = passing[0].get("adduct")
        if adducts and (not hit_adduct or hit_adduct not in adducts):
            reject("Library and formula evidence have incompatible or unknown adducts.")
        if hit_adduct:
            adducts.add(hit_adduct)
        elif len(records) > 1:
            reject("Combined evidence includes a library hit with an unknown adduct.")
        if len(adducts) > 1:
            reject("Library and formula evidence use different adducts.")
        if (
            hit_adduct
            and context
            and context["polarity"]
            and get_adduct(hit_adduct).charge * context["polarity"] < 0
        ):
            reject("Library hit conflicts with the selected scan polarity.")


def evaluate(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply the rule table to ledger records (all for the same feature). Pure."""
    formulas = [r for r in records if r["op"] == "propose_formulas"]
    matches = [r for r in records if r["op"] == "match_spectrum"]
    consistent: set[str] | None = None
    for f in formulas:
        d = f["result"]["data"]
        if d.get("isotope_data"):
            ok = {c["formula"] for c in d["candidates"] if not c["rejected"]}
            consistent = ok if consistent is None else consistent & ok
    fired: list[tuple[str, int, str]] = []
    best_hit: dict[str, Any] | None = None
    for m in matches:
        hits = m["result"]["data"].get("hits", [])
        passing = [h for h in hits if h["passes"]]
        if passing:
            h = passing[0]
            conflict = (
                consistent is not None and h.get("formula") and h["formula"] not in consistent
            )
            if conflict:
                fired.append(
                    (
                        "L3-library-conflict",
                        3,
                        f"{h['name']} ({h['formula']}) is not "
                        "among the isotope-consistent formulas",
                    )
                )
            else:
                fired.append(
                    (
                        "L2-library",
                        2,
                        f"{h['name']}: score {h['score']}, "
                        f"{h['n_matched']} matched fragments, licence {h['licence']}",
                    )
                )
                best_hit = h
        elif hits and hits[0]["score"] >= NEAR_MISS_SCORE:
            fired.append(("L3-near-miss", 3, f"{hits[0]['name']} scored {hits[0]['score']}"))
    for f in formulas:
        d = f["result"]["data"]
        if d.get("unequivocal"):
            fired.append(
                ("L4-formula", 4, f"only {d['candidates'][0]['formula']} fits mass and isotopes")
            )
    if records:
        fired.append(("L5-mass", 5, f"m/z {evidence_mz(records[0]):.4f}"))
    rule_id, level, reason = min(fired, key=lambda t: t[1])
    return {
        "level": level,
        "label": LABELS[level],
        "rule": rule_id,
        "reason": reason,
        "all_rules_fired": [{"rule": r, "level": lv, "reason": why} for r, lv, why in fired],
        "identity": best_hit["name"] if level == 2 and best_hit else None,
        "ruleset_version": RULESET_VERSION,
    }
