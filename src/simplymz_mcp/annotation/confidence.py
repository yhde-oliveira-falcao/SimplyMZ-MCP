"""Rule-based identification confidence (plan M4.T6).

Levels follow Schymanski et al., Environ. Sci. Technol. 2014, 48, 2097-2098:
1 confirmed structure (reference standard) · 2 probable structure (library match) ·
3 tentative candidate(s) · 4 unequivocal molecular formula · 5 exact mass of interest.
Input is evidence (ledger records) only; nothing can set a level directly. Level 1 is
never assigned in v0.1 because there is no reference-standard evidence type yet.
"""

from __future__ import annotations

from typing import Any

RULESET_VERSION = "simplymz-confidence-1"
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
