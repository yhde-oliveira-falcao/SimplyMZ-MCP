"""Annotation tools (plan M4): load_library, match_spectrum (T4/T5); propose_formulas and
assign_confidence are added by M4.T6/T7."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any, Literal

import numpy as np

from simplymz_mcp.annotation.library import Library, parse_mgf, parse_msp
from simplymz_mcp.annotation.similarity import (
    MATCHMS_INSTALL,
    cosine,
    cosine_matchms,
    matchms_available,
)
from simplymz_mcp.core import envelope
from simplymz_mcp.core.errors import ErrorCode, SimplyMZError
from simplymz_mcp.core.registry import Registry, ToolSpec
from simplymz_mcp.io.mzml import RunData, sha256_file
from simplymz_mcp.io.security import resolve_data_path

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from simplymz_mcp.server import App

MAX_PAIRS_SHOWN = 6


def find_ms2(run: RunData, precursor_mz: float, ppm: float, rt_min: float | None) -> int | None:
    s = run.scans
    cand = np.flatnonzero(
        (s.ms_level >= 2) & (np.abs(s.precursor_mz - precursor_mz) <= precursor_mz * ppm * 1e-6)
    )
    if cand.size == 0:
        return None
    if rt_min is not None:
        return int(cand[np.argmin(np.abs(s.rt_min[cand] - rt_min))])
    return int(cand[np.argmax(s.tic[cand])])


def engine_note(engine: str) -> str:
    """Disclosure attached to every match result (ADR 0009 amendment)."""
    if engine == "matchms":
        return (
            "Scores computed by the optional matchms package (independent reference "
            "implementation); SimplyMZ's built-in engine gives identical scores for "
            "these methods."
        )
    tail = (
        "matchms is installed: pass engine='matchms' to cross-check."
        if matchms_available()
        else f"Optional: install matchms ({MATCHMS_INSTALL}) to cross-check with engine='matchms'."
    )
    return (
        "Scores computed by SimplyMZ's built-in greedy cosine, verified identical to "
        "matchms 0.33 (max difference 2e-16 over 1,800 comparisons); matchms adds an "
        "independent cross-check and, later, more similarity measures, not more precision "
        "for these methods. " + tail
    )


def register(server: MCPServer, registry: Registry, app: App) -> dict[str, Any]:
    libs: dict[str, Library] = {}
    lock = threading.Lock()

    def _library(handle: str) -> tuple[Library, dict[str, Any]]:
        meta = app.store.get(handle, "lib")
        with lock:
            if meta["sha256"] not in libs:
                path = resolve_data_path(app.config.root, meta["path"], app.config.limits)
                if sha256_file(path) != meta["sha256"]:
                    raise SimplyMZError(
                        ErrorCode.UNKNOWN_HANDLE,
                        f"The library behind {handle} has changed.",
                        "Load it again with load_library.",
                    )
                libs[meta["sha256"]] = _parse(path)
            return libs[meta["sha256"]], meta

    def _parse(path: Any) -> Library:
        text = path.read_text(encoding="utf-8", errors="replace")
        spectra = parse_mgf(text) if path.suffix.lower() == ".mgf" else parse_msp(text)
        return Library(path.name, spectra)

    def load_library(path: str) -> dict[str, Any]:
        """Load an MSP or MGF spectral library under the data root; returns a lib: handle.

        Each spectrum keeps its licence; libraries are never bundled with SimplyMZ."""
        p = resolve_data_path(app.config.root, path, app.config.limits)
        if p.suffix.lower() not in (".msp", ".mgf"):
            raise SimplyMZError(
                ErrorCode.UNSUPPORTED_FORMAT,
                "Libraries must be MSP or MGF.",
                "Export the library as .msp or .mgf.",
            )
        lib = _parse(p)
        if len(lib) == 0:
            raise SimplyMZError(
                ErrorCode.MALFORMED_FILE,
                f"No spectra found in {p.name}.",
                "MSP needs Name, PrecursorMZ and Num Peaks; MGF needs "
                "BEGIN IONS / PEPMASS / END IONS.",
            )
        sha = sha256_file(p)
        with lock:
            libs[sha] = lib
        rel = p.relative_to(app.config.root.resolve()).as_posix()
        handle = app.store.find("lib", "sha256", sha) or app.store.create(
            "lib", {"path": rel, "sha256": sha}
        )
        lic = lib.licences()
        limits = ["Matches are only as good as the library; licences apply per spectrum."]
        if "unknown" in lic:
            limits.append(f"{lic['unknown']} spectra have no stated licence.")
        env = envelope.ok(
            f"Loaded {len(lib)} spectra from {p.name} as {handle}.",
            {"library_handle": handle, "n_spectra": len(lib), "licences": lic},
            limits=limits,
            next_steps=[f"match_spectrum(..., library_handle='{handle}')"],
        )
        env["_provenance"] = {"input_hashes": [sha], "parents": []}
        return env

    def match_spectrum(
        run_handle: str,
        precursor_mz: float,
        library_handle: str,
        rt_min: float | None = None,
        method: Literal["cosine", "modified_cosine"] = "cosine",
        fragment_tol_da: float = 0.01,
        precursor_ppm: float = 10.0,
        min_matched_peaks: int = 2,
        score_threshold: float = 0.7,
        engine: Literal["builtin", "matchms"] = "builtin",
    ) -> dict[str, Any]:
        """Match the run's MS2 spectrum for precursor_mz (nearest rt_min if given) against a
        library. Candidates must have a precursor within precursor_ppm. A hit counts only
        with score >= score_threshold and >= min_matched_peaks matched fragments.

        engine="builtin" (default) uses SimplyMZ's greedy cosine, verified identical to
        matchms; engine="matchms" uses the optional matchms package (install:
        uvx --with "matchms>=0.33,<0.34" simplymz-mcp). Tell the user about this option."""
        if not 0 < fragment_tol_da <= 0.5 or not 0 < precursor_ppm <= 100:
            raise SimplyMZError(
                ErrorCode.INVALID_ARGUMENT,
                "Tolerance out of range.",
                "fragment_tol_da in (0, 0.5]; precursor_ppm in (0, 100].",
            )
        if engine == "matchms" and not matchms_available():
            raise SimplyMZError(
                ErrorCode.INVALID_ARGUMENT,
                "engine='matchms' needs the optional matchms package, which is not installed.",
                f"Install it with: {MATCHMS_INSTALL} (or use engine='builtin', which gives "
                "identical scores for these methods).",
            )
        run = app.runs.get(run_handle)
        lib, meta = _library(library_handle)
        i = find_ms2(run, precursor_mz, precursor_ppm, rt_min)
        if i is None:
            raise SimplyMZError(
                ErrorCode.INVALID_ARGUMENT,
                f"No MS2 spectrum with precursor {precursor_mz:.4f} "
                f"(+/-{precursor_ppm:g} ppm) in this run.",
                "Check the precursor m/z, or acquire MS2 (DDA/DIA) data.",
            )
        qmz, qint = run.peaks(i)
        qint = qint.astype(float)
        hits: list[dict[str, Any]] = []
        for spec in lib.by_precursor(precursor_mz, precursor_ppm):
            score, pairs = cosine(
                qmz,
                qint,
                spec.mz,
                spec.intensity,
                fragment_tol_da,
                precursor_a=precursor_mz,
                precursor_b=spec.precursor_mz,
                modified=method == "modified_cosine",
            )
            n_matched = len(pairs)
            if engine == "matchms":
                score, n_matched = cosine_matchms(
                    qmz,
                    qint,
                    spec.mz,
                    spec.intensity,
                    fragment_tol_da,
                    precursor_a=precursor_mz,
                    precursor_b=spec.precursor_mz,
                    modified=method == "modified_cosine",
                )
            hits.append(
                {
                    "name": spec.name,
                    "formula": spec.formula,
                    "adduct": spec.adduct,
                    "score": round(score, 4),
                    "n_matched": n_matched,
                    "precursor_ppm": round(
                        (spec.precursor_mz - precursor_mz) / precursor_mz * 1e6, 2
                    ),
                    "passes": score >= score_threshold and n_matched >= min_matched_peaks,
                    "licence": spec.licence,
                    "matched_pairs": [
                        [round(float(qmz[a]), 4), round(float(spec.mz[b]), 4)]
                        for a, b in pairs[:MAX_PAIRS_SHOWN]
                    ],
                }
            )
        hits.sort(key=lambda h: (-float(h["score"]), str(h["name"])))
        passing = [h for h in hits if h["passes"]]
        data = {
            "query": {
                "scan": run.scans.native_id[i],
                "rt_min": round(float(run.scans.rt_min[i]), 4),
                "precursor_mz": precursor_mz,
                "n_peaks": int(qmz.size),
            },
            "parameters": {
                "method": method,
                "fragment_tol_da": fragment_tol_da,
                "precursor_ppm": precursor_ppm,
                "min_matched_peaks": min_matched_peaks,
                "score_threshold": score_threshold,
                "engine": engine,
            },
            "library": meta["path"],
            "n_candidates": len(hits),
            "hits": hits[:5],
        }
        limits = [
            "A library match supports a structure only as far as the library spectrum "
            "itself is reliable; it is not a reference-standard confirmation (Level 1).",
            engine_note(engine),
        ]
        prov = {
            "input_hashes": [run.sha256, meta["sha256"]],
            "parents": [run_handle, library_handle],
        }
        if passing:
            top = passing[0]
            env = envelope.ok(
                f"Best library match: {top['name']} (score {top['score']}, "
                f"{top['n_matched']} matched fragments, licence {top['licence']}).",
                data,
                limits=limits,
                next_steps=["assign_confidence(evidence=[<this provenance_id>, ...])"],
            )
        else:
            reason = (
                "no library spectrum has a precursor within the tolerance"
                if not hits
                else "no candidate reached the score and matched-peak thresholds"
            )
            env = envelope.insufficient(
                f"No library match: {reason}.",
                data,
                limits=[*limits, "The compound may be absent from this library."],
                next_steps=["propose_formulas(mz=..., adduct=...) for formula-level evidence"],
            )
        env["_provenance"] = prov
        return env

    guarded = {}
    for spec in [
        ToolSpec(
            "load_library",
            load_library.__doc__ or "",
            load_library,
            600,
            {"path": "library/synthetic_library.msp"},
        ),
        ToolSpec(
            "match_spectrum",
            match_spectrum.__doc__ or "",
            match_spectrum,
            1500,
            {"run_handle": "<ms2run>", "precursor_mz": 195.087652, "library_handle": "<lib>"},
        ),
    ]:
        guarded[spec.name] = registry.register(spec)
        server.add_tool(guarded[spec.name], name=spec.name, description=spec.description)
    return guarded


def register_formula_and_confidence(
    server: MCPServer, registry: Registry, app: App
) -> dict[str, Any]:
    """propose_formulas and assign_confidence (plan M4.T6/T7)."""
    from simplymz_mcp.annotation import confidence
    from simplymz_mcp.annotation.adducts import get_adduct
    from simplymz_mcp.annotation.formulas import enumerate_formulas
    from simplymz_mcp.annotation.isotopes import observe
    from simplymz_mcp.annotation.propose import rank

    def propose_formulas(
        mz: float,
        adduct: str = "[M+H]+",
        mz_tol_ppm: float = 5.0,
        elements: str = "CHNOPS",
        run_handle: str | None = None,
        rt_min: float | None = None,
        max_candidates: int = 8,
    ) -> dict[str, Any]:
        """Candidate molecular formulas for an ion m/z (adduct removed), filtered by a
        documented subset of the Seven Golden Rules and, when run_handle and rt_min are
        given, ranked by the fit of the observed M+1/M+2 isotope peaks in that MS1 scan."""
        if mz <= 0 or not 0 < mz_tol_ppm <= 50 or not 1 <= max_candidates <= 20:
            raise SimplyMZError(
                ErrorCode.INVALID_ARGUMENT,
                "Bad mz, mz_tol_ppm or max_candidates.",
                "mz > 0; mz_tol_ppm in (0, 50]; max_candidates 1-20.",
            )
        polarity = None
        observed = None
        sha: list[str] = []
        parents: list[str] = []
        if run_handle:
            run = app.runs.get(run_handle)
            polarity = run.meta["polarity"]
            sha, parents = [run.sha256], [run_handle]
        add = get_adduct(adduct, polarity)
        if run_handle and rt_min is not None:
            s = run.scans
            ms1 = np.flatnonzero(s.ms_level == 1)
            i = int(ms1[np.argmin(np.abs(s.rt_min[ms1] - rt_min))])
            observed = observe(*run.peaks(i), mz, add.charge)
        try:
            cands = enumerate_formulas(add.neutral(mz), mz_tol_ppm, elements)
        except ValueError as exc:
            raise SimplyMZError(
                ErrorCode.INVALID_ARGUMENT, str(exc), "elements like 'CHNOPS' or 'CHNOPSCl'."
            ) from exc
        ranked = rank(cands, observed)
        consistent = [r for r in ranked if not r["rejected"]]
        rows = []
        for r in ranked[:max_candidates]:
            row = {k: r[k] for k in ("formula", "neutral_mass", "ppm", "rdbe", "score", "rejected")}
            if "isotope" in r:
                row["isotope_predicted_rel"] = r["isotope"]["predicted_rel"]
                row["isotope_z"] = r["isotope"]["z_scores"]
            rows.append(row)
        data = {
            "mz": mz,
            "adduct": adduct,
            "neutral_mass": round(add.neutral(mz), 6),
            "elements": elements,
            "mz_tol_ppm": mz_tol_ppm,
            "isotope_data": observed is not None,
            "observed_isotope_rel": [round(v, 4) for v in observed] if observed else None,
            "n_candidates": len(ranked),
            "n_consistent": len(consistent),
            "unequivocal": observed is not None and len(consistent) == 1,
            "candidates": rows,
        }
        limits = [
            "Formula rules: element limits, integer RDBE >= 0, extended element ratios "
            "(Kind & Fiehn 2007, subset); fluorine, iodine, Si and metals are not "
            "considered."
        ]
        if observed is None:
            limits.append(
                "No isotope data used (give run_handle and rt_min); ranking is by "
                "mass error only, so several formulas may fit equally."
            )
        prov = {"input_hashes": sha, "parents": parents}
        if not ranked:
            env = envelope.insufficient(
                f"No formula within {mz_tol_ppm:g} ppm of the neutral mass for {adduct}.",
                data,
                limits=limits,
                next_steps=["Check the adduct, widen mz_tol_ppm, or add elements (e.g. Cl)."],
            )
        else:
            top = consistent[0]["formula"] if consistent else ranked[0]["formula"]
            env = envelope.ok(
                f"{len(consistent)} of {len(ranked)} formula(s) consistent"
                + (" with mass and isotopes" if observed else " with mass")
                + f"; best: {top}"
                + (" (unequivocal)." if data["unequivocal"] else "."),
                data,
                limits=limits,
                next_steps=["assign_confidence(evidence=[<this provenance_id>, ...])"],
            )
        env["_provenance"] = prov
        return env

    def assign_confidence(evidence: list[str]) -> dict[str, Any]:
        """Identification confidence level (Schymanski 1-5) from evidence: provenance_ids
        of propose_formulas and match_spectrum results for the same feature. The level is
        computed by a versioned rule table and cannot be set by the caller."""
        if not evidence:
            raise SimplyMZError(
                ErrorCode.INVALID_ARGUMENT,
                "No evidence given.",
                "Pass provenance_ids from propose_formulas and/or match_spectrum.",
            )
        records = []
        for ev in evidence:
            rec = app.ledger.get(ev)
            if rec is None:
                raise SimplyMZError(
                    ErrorCode.UNKNOWN_HANDLE,
                    f"{ev} is not in the ledger.",
                    "Use provenance_id values returned by tools.",
                )
            if rec["op"] not in confidence.SUPPORTED_OPS:
                raise SimplyMZError(
                    ErrorCode.INVALID_ARGUMENT,
                    f"{ev} comes from {rec['op']}, which is not evidence for identification.",
                    f"Supported: {', '.join(confidence.SUPPORTED_OPS)}.",
                )
            records.append(rec)
        mzs = [confidence.evidence_mz(r) for r in records]
        ref = mzs[0]
        if any(abs(m - ref) / ref * 1e6 > confidence.SAME_FEATURE_PPM for m in mzs):
            raise SimplyMZError(
                ErrorCode.INVALID_ARGUMENT,
                "Evidence refers to different m/z values.",
                "Give evidence for one feature at a time.",
            )
        res = confidence.evaluate(records)
        what = f": {res['identity']}" if res["identity"] else ""
        env = envelope.ok(
            f"Level {res['level']} ({res['label']}){what}.",
            {**res, "evidence": evidence},
            limits=[
                "Level 1 (confirmed structure) needs comparison with a "
                "reference standard and is never assigned in v0.1.",
                "Levels follow Schymanski et al., Environ. Sci. Technol. "
                "2014, 48, 2097-2098; the rule table is in "
                "simplymz_mcp.annotation.confidence.",
            ],
        )
        env["_provenance"] = {"input_hashes": [], "parents": list(evidence)}
        return env

    guarded = {}
    for spec in [
        ToolSpec(
            "propose_formulas",
            propose_formulas.__doc__ or "",
            propose_formulas,
            1500,
            {"mz": 195.087652, "adduct": "[M+H]+", "run_handle": "<run>", "rt_min": 4.4},
        ),
        ToolSpec(
            "assign_confidence",
            assign_confidence.__doc__ or "",
            assign_confidence,
            900,
            {"evidence": ["<ev>"]},
        ),
    ]:
        guarded[spec.name] = registry.register(spec)
        server.add_tool(guarded[spec.name], name=spec.name, description=spec.description)
    return guarded
