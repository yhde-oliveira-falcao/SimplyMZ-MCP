"""Deterministic evaluations (plan M5.T4): gated, reproducible, no network or LLM.

uv run python -m eval.deterministic      # writes eval/results.json and the
                                         # deterministic section of eval/results.md
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

from simplymz_mcp.analytics.qc import BatchRun, compute_qc, load_thresholds
from simplymz_mcp.annotation.formulas import enumerate_formulas
from simplymz_mcp.annotation.library import Library, parse_msp
from simplymz_mcp.annotation.propose import rank
from simplymz_mcp.annotation.similarity import cosine
from simplymz_mcp.io.mzml import read_mzml
from simplymz_mcp.synth.compounds import COMPOUNDS
from simplymz_mcp.synth.elements import isotope_pattern, monoisotopic_mass
from simplymz_mcp.synth.faults import FAULT_CASES, make_case
from simplymz_mcp.synth.fixtures import LIBRARY_COMPOUNDS
from simplymz_mcp.synth.model import render
from simplymz_mcp.synth.writer import msp_text

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"
THRESHOLDS = {
    "qc_detection_at_2x": 1.0,
    "qc_false_fail_at_half": 0.0,
    "formula_presence": 1.0,
    "formula_rank1_below_400": 0.90,
    "abstention_out_of_library": 1.0,
    "decoy_false_positive": 0.0,
}


def _batch_runs(tmp: Path, replace_name: str | None = None, spec: Any = None) -> list[BatchRun]:
    from simplymz_mcp.synth.writer import write_mzml

    sheet = (FIX / "batch_qc" / "sample_sheet.csv").read_text().splitlines()[1:]
    runs = []
    for line in sheet:
        f, st, _, order = line.split(",")
        name = f.split(".")[0]
        path = FIX / "batch_qc" / f
        if name == replace_name:
            path = tmp / f
            scans, _ = render(spec)
            write_mzml(scans, path, spec.name, "positive")
        runs.append(BatchRun(f, st, int(order), read_mzml(path)))
    return runs


def qc_matrix(tmp: Path, multiples: tuple[float, ...] = (0.5, 2.0, 4.0)) -> dict[str, Any]:
    th = load_thresholds()
    rows, detected, n_detect, false_fail, n_half = [], 0, 0, 0, 0
    for fault, (metric, run_name, _) in FAULT_CASES.items():
        for k in multiples:
            case = make_case(fault, k, th[metric]["fail"])
            res = compute_qc(_batch_runs(tmp, run_name, case.spec), th)
            v = res["metrics"][metric]["verdict"]
            rows.append(
                {
                    "fault": fault,
                    "multiple": k,
                    "metric": metric,
                    "verdict": v,
                    "value": res["metrics"][metric]["value"],
                }
            )
            if k >= 2:
                n_detect += 1
                detected += v == "fail"
            if k == 0.5:
                n_half += 1
                false_fail += v == "fail"
    return {
        "rows": rows,
        "qc_detection_at_2x": detected / n_detect,
        "qc_false_fail_at_half": false_fail / n_half,
    }


def formula_eval(seed: int = 5) -> dict[str, Any]:
    from tests.oracle.compounds import ORACLE, elements_for

    rng = np.random.default_rng(seed)
    present = hits = n_iso = 0
    for f in ORACLE.values():
        m = monoisotopic_mass(f)
        cands = enumerate_formulas(
            m * (1 + rng.normal(0, 1e-6)), 5.0, elements_for(f), max_candidates=10_000
        )
        present += f in [c.formula for c in cands]
        if m < 400:
            n_iso += 1
            obs = [1.0] + [a * (1 + rng.normal(0, 0.02)) for _, a in isotope_pattern(f, 3)[1:]]
            hits += rank(cands, obs)[0]["formula"] == f
    return {
        "n_compounds": len(ORACLE),
        "formula_presence": present / len(ORACLE),
        "formula_rank1_below_400": hits / n_iso,
    }


def abstention_eval() -> dict[str, Any]:
    run = read_mzml(FIX / "runs" / "ms2_dda.mzML.gz")
    truth = json.loads((FIX / "runs" / "ms2_dda.truth.json").read_text())["compounds"]
    s = run.scans

    def best(lib: Library, mz: float, rt: float) -> tuple[float, int]:
        idx = np.flatnonzero((s.ms_level == 2) & (np.abs(s.precursor_mz - mz) < mz * 10e-6))
        i = int(idx[np.argmin(np.abs(s.rt_min[idx] - rt))])
        qmz, qi = run.peaks(i)
        scores = [
            cosine(qmz, qi.astype(float), sp.mz, sp.intensity, 0.01)
            for sp in lib.by_precursor(mz, 10)
        ]
        return max(((sc, len(p)) for sc, p in scores), default=(0.0, 0))

    abstained = n_out = 0
    for c in truth:
        names = [n for n in LIBRARY_COMPOUNDS if n != c["name"]]
        sc, nm = best(Library("loo", parse_msp(msp_text(names))), c["ion_mz"], c["rt_min"])
        n_out += 1
        abstained += not (sc >= 0.7 and nm >= 2)
    rng = np.random.default_rng(11)
    decoys = []
    for name in LIBRARY_COMPOUNDS:
        comp = COMPOUNDS[name]
        peaks = sorted(
            (fr.mz + rng.choice([-1, 1]) * rng.uniform(5, 60), fr.rel_intensity)
            for fr in comp.fragments
        )
        decoys.append(
            "\n".join(
                [
                    f"Name: decoy_{name}",
                    f"PrecursorMZ: {comp.ion_mz('[M+H]+'):.6f}",
                    f"Num Peaks: {len(peaks)}",
                    *[f"{m:.4f} {i:.3f}" for m, i in peaks],
                ]
            )
        )
    dlib = Library("decoys", parse_msp("\n\n".join(decoys)))
    fp = sum(
        1
        for c in truth
        if (lambda r: r[0] >= 0.7 and r[1] >= 2)(best(dlib, c["ion_mz"], c["rt_min"]))
    )
    return {
        "abstention_out_of_library": abstained / n_out,
        "n_out_of_library": n_out,
        "decoy_false_positive": fp / len(truth),
    }


def evaluate(tmp: Path) -> dict[str, Any]:
    res = {**qc_matrix(tmp), **formula_eval(), **abstention_eval()}
    checks = {}
    for k, thr in THRESHOLDS.items():
        ok = (
            res[k] <= thr
            if k in ("qc_false_fail_at_half", "decoy_false_positive")
            else res[k] >= thr
        )
        checks[k] = {"value": round(res[k], 4), "threshold": thr, "pass": ok}
    res["checks"] = checks
    res["all_pass"] = all(c["pass"] for c in checks.values())
    return res


def write_results(res: dict[str, Any]) -> None:
    (ROOT / "eval" / "results.json").write_text(json.dumps(res, indent=1) + "\n")
    md = [
        "# Evaluation results",
        "",
        "## Deterministic evaluations (gated)",
        "",
        "| Check | Value | Threshold | Pass |",
        "|---|---|---|---|",
    ]
    for k, c in res["checks"].items():
        md.append(f"| {k} | {c['value']} | {c['threshold']} | {'✅' if c['pass'] else '❌'} |")
    md += [
        "",
        "Synthetic data only (see docs/data.md). QC matrix: 6 faults x 0.5/2/4x the "
        "fail threshold; formulas: 35-compound oracle set; abstention: leave-one-out "
        "libraries and shifted-fragment decoys.",
        "",
    ]
    path = ROOT / "eval" / "results.md"
    old = path.read_text() if path.exists() else ""
    llm = (
        old[old.index("## LLM evaluation") :]
        if "## LLM evaluation" in old
        else (
            "## LLM evaluation (reported, not gated)\n\nNot run yet: needs ANTHROPIC_API_KEY "
            "(run `uv run python -m eval.llm_eval`).\n"
        )
    )
    path.write_text("\n".join(md) + "\n" + llm)


def main() -> int:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        res = evaluate(Path(tmp))
    write_results(res)
    for k, c in res["checks"].items():
        print(f"{'PASS' if c['pass'] else 'FAIL'} {k}: {c['value']} (threshold {c['threshold']})")
    return 0 if res["all_pass"] else 1


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    sys.exit(main())
