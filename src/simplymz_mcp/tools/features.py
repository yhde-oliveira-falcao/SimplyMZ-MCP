"""detect_features (async) and get_feature (plan M3.T4), with batch alignment (M3.T5)."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

import numpy as np

from simplymz_mcp.analytics import features as fx
from simplymz_mcp.analytics.align import align
from simplymz_mcp.analytics.chromatogram import ChromParams, extract
from simplymz_mcp.analytics.runcard import downsample_max
from simplymz_mcp.core import envelope
from simplymz_mcp.core.errors import ErrorCode, SimplyMZError
from simplymz_mcp.core.registry import Registry, ToolSpec
from simplymz_mcp.jobs.executor import JobContext
from simplymz_mcp.state.ftab import FeatureTables
from simplymz_mcp.tools.jobs import submit_tool_job

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from simplymz_mcp.server import App

DETECT_BUDGET = 1500
CARD_BUDGET = 800


def _key(handle: str) -> str:
    return handle.replace(":", "_")


def _sig(v: float | None) -> float | None:
    return None if v is None else float(f"{v:.4g}")


def register(server: MCPServer, registry: Registry, app: App) -> None:
    tables = FeatureTables(app.config.resolved_cache_dir())

    def _detect_one(
        run_handle: str, params: fx.DetectorParams, ctx: JobContext | None, lo: float, hi: float
    ) -> dict[str, Any]:
        run = app.runs.get(run_handle)

        def check(frac: float) -> None:
            if ctx is not None:
                ctx.progress(lo + (hi - lo) * frac, f"detecting features in {run.path.name}")

        return fx.detect_features(run, params, check=check)

    def detect_body(
        ctx: JobContext,
        run_handle: str | None = None,
        batch_handle: str | None = None,
        mz_tol_ppm: float = 10.0,
        min_intensity: float | None = None,
        align_rt_tol_min: float = 0.15,
    ) -> dict[str, Any]:
        params = fx.DetectorParams(ppm=mz_tol_ppm, min_intensity=min_intensity)
        if run_handle:
            res = _detect_one(run_handle, params, ctx, 0.0, 0.9)
            feats = res["features"]
            ftab = app.store.create("ftab", {"kind": "run", "run_handle": run_handle})
            tables.save_run(_key(ftab), feats, {"params": res["params"]})
            mono = [f for f in feats if f["isotope_of"] is None]
            n_iso = len(feats) - len(mono)
            groups = {f["adduct_group"] for f in feats if f["adduct_group"]}
            top = sorted(mono, key=lambda f: -f["height"])[:10]
            iso_count = {f["id"]: 0 for f in mono}
            for f in feats:
                if f["isotope_of"] in iso_count:
                    iso_count[f["isotope_of"]] += 1
            env = envelope.ok(
                f"Detected {len(mono)} features ({n_iso} isotope peaks grouped, "
                f"{len(groups)} adduct groups) with masstrace-lite as {ftab}.",
                {
                    "ftab_handle": ftab,
                    "n_features": len(mono),
                    "n_isotope_peaks": n_iso,
                    "n_adduct_groups": len(groups),
                    "params": res["params"],
                    "top_features": [
                        {
                            "id": f["id"],
                            "mz": f["mz"],
                            "rt_min": f["rt_min"],
                            "height": _sig(f["height"]),
                            "area": _sig(f["area"]),
                            "n_isotopes": iso_count[f["id"]],
                        }
                        for f in top
                    ],
                },
                limits=[
                    "masstrace-lite was validated on synthetic data only (recall and "
                    "precision 100% on the fixtures); real data may need parameter tuning.",
                    "Feature counts exclude isotope peaks (grouped under their "
                    "monoisotopic feature).",
                ],
                next_steps=[f"get_feature(ftab_handle='{ftab}', feature_id='{top[0]['id']}')"]
                if top
                else [],
            )
            sha = app.runs.get(run_handle).sha256
            env["_provenance"] = {"input_hashes": [sha], "parents": [run_handle]}
            return env
        assert batch_handle is not None
        entries = app.store.get(batch_handle, "batch")["entries"]
        per_run = []
        counts = {}
        for n, e in enumerate(entries):
            res = _detect_one(
                e["run_handle"], params, ctx, 0.85 * n / len(entries), 0.85 * (n + 1) / len(entries)
            )
            label = PurePosixPath(e["file"]).name
            mono = [f for f in res["features"] if f["isotope_of"] is None]
            per_run.append((label, mono))
            counts[label] = len(mono)
        ctx.progress(0.9, "aligning")
        al = align(per_run, ppm_tol=mz_tol_ppm, rt_tol=align_rt_tol_min)
        info = {PurePosixPath(e["file"]).name: e for e in entries}
        consensus, members = [], []
        for c in al["consensus"]:
            consensus.append(
                {
                    "cid": c.cid,
                    "mz": round(c.mz, 6),
                    "rt_min": round(c.rt, 4),
                    "n_present": len(c.members),
                }
            )
            for label, f in c.members.items():
                e = info[label]
                members.append(
                    {
                        "cid": c.cid,
                        "run": label,
                        "sample_type": e["sample_type"],
                        "group": e["group"],
                        "injection_order": e["injection_order"],
                        "feature_id": f["id"],
                        "mz": f["mz"],
                        "rt_min": f["rt_min"],
                        "area": f["area"],
                        "height": f["height"],
                    }
                )
        ftab = app.store.create("ftab", {"kind": "aligned", "batch_handle": batch_handle})
        tables.save_aligned(
            _key(ftab),
            consensus,
            members,
            {"params": {**params.as_dict(), **al["params"]}, "runs": [lbl for lbl, _ in per_run]},
        )
        area_sum: dict[str, float] = {}
        for m in members:
            area_sum[m["cid"]] = area_sum.get(m["cid"], 0.0) + float(m["area"])
        top_c = sorted(consensus, key=lambda c: -area_sum[c["cid"]])[:10]
        env = envelope.ok(
            f"Detected and aligned features across {len(entries)} runs: {len(consensus)} "
            f"consensus features ({al['conflicts']} alignment conflicts resolved by score) "
            f"as {ftab}.",
            {
                "ftab_handle": ftab,
                "n_consensus": len(consensus),
                "conflicts": al["conflicts"],
                "features_per_run": dict(list(counts.items())[:30]),
                "align_params": al["params"],
                "top_consensus": top_c,
            },
            limits=[
                "Alignment uses m/z and RT tolerances only (no RT warping); large RT "
                "drift splits features (check qc_batch rt_drift_min first).",
                "masstrace-lite was validated on synthetic data only.",
            ],
            next_steps=[f"compare_groups(ftab_handle='{ftab}', group_a=..., group_b=...)"],
        )
        env["_provenance"] = {
            "input_hashes": [e["sha256"] for e in entries],
            "parents": [batch_handle],
        }
        return env

    def detect_features(
        run_handle: str | None = None,
        batch_handle: str | None = None,
        mz_tol_ppm: float = 10.0,
        min_intensity: float | None = None,
        align_rt_tol_min: float = 0.15,
    ) -> dict[str, Any]:
        """Detect features (masstrace-lite) in one run or a whole batch (then aligned).

        Runs as an asynchronous job: returns a job: handle at once; job_status gives the
        ftab: handle. Give exactly one of run_handle or batch_handle."""
        if (run_handle is None) == (batch_handle is None):
            raise SimplyMZError(
                ErrorCode.INVALID_ARGUMENT,
                "Give exactly one of run_handle or batch_handle.",
                "Use run_handle for one file, batch_handle to align a batch.",
            )
        if not 0 < mz_tol_ppm <= 100 or align_rt_tol_min <= 0:
            raise SimplyMZError(
                ErrorCode.INVALID_ARGUMENT,
                "Tolerances out of range.",
                "mz_tol_ppm in (0, 100]; align_rt_tol_min > 0.",
            )
        # validate handles now so the user gets the error immediately, not from the job
        if run_handle:
            app.store.get(run_handle, "run")
        else:
            app.store.get(batch_handle or "", "batch")
        return submit_tool_job(
            app,
            "detect_features",
            detect_body,
            {
                "run_handle": run_handle,
                "batch_handle": batch_handle,
                "mz_tol_ppm": mz_tol_ppm,
                "min_intensity": min_intensity,
                "align_rt_tol_min": align_rt_tol_min,
            },
            DETECT_BUDGET,
        )

    def get_feature(ftab_handle: str, feature_id: str) -> dict[str, Any]:
        """Feature Card: one feature's m/z, RT, area, shape, isotopes and adducts (run
        tables) or its per-run areas (aligned batch tables)."""
        meta = app.store.get(ftab_handle, "ftab")
        if meta["kind"] == "run":
            feats, fmeta = tables.load_run(_key(ftab_handle))
            byid = {f["id"]: f for f in feats}
            if feature_id not in byid:
                raise SimplyMZError(
                    ErrorCode.INVALID_ARGUMENT,
                    f"No feature {feature_id} in {ftab_handle}.",
                    f"Valid ids look like {', '.join(list(byid)[:3])}; see detect_features.",
                )
            f = byid[feature_id]
            mono_id = f["isotope_of"] or f["id"]
            iso = [
                {
                    "id": g["id"],
                    "isotope_index": g["isotope_index"],
                    "mz": g["mz"],
                    "rel_height": round(g["height"] / byid[mono_id]["height"], 4),
                }
                for g in feats
                if g["isotope_of"] == mono_id
            ]
            adducts = (
                [
                    {"id": g["id"], "mz": g["mz"]}
                    for g in feats
                    if g["adduct_group"] == f["adduct_group"] and g["id"] != f["id"]
                ]
                if f["adduct_group"]
                else []
            )
            run = app.runs.get(meta["run_handle"])
            half = max(0.5, 3 * (f["rt_end_min"] - f["rt_start_min"]))
            rt, y = extract(
                run,
                ChromParams(
                    "EIC", f["mz"], fmeta["params"]["ppm"], f["rt_min"] - half, f["rt_min"] + half
                ),
            )
            xs, ys = downsample_max(rt, y, 20)
            card = {
                k: f[k]
                for k in (
                    "id",
                    "mz",
                    "rt_min",
                    "rt_start_min",
                    "rt_end_min",
                    "fwhm_min",
                    "snr",
                    "n_points",
                    "charge",
                    "isotope_of",
                    "adduct_group",
                )
            }
            card.update(
                height=_sig(f["height"]),
                area=_sig(f["area"]),
                isotopes=iso,
                adducts=adducts,
                eic={"rt_min": [round(v, 3) for v in xs], "intensity": [_sig(v) for v in ys]},
            )
            role = (
                f"isotope M+{f['isotope_index']} of {f['isotope_of']}"
                if f["isotope_of"]
                else f"monoisotopic, charge {f['charge']}, {len(iso)} isotope peak(s)"
            )
            env = envelope.ok(
                f"{feature_id}: m/z {f['mz']:.4f} at {f['rt_min']:.2f} min, area "
                f"{f['area']:.4g} counts*min ({role}).",
                card,
                limits=[
                    "Charge and isotope assignment come from co-eluting peak spacing; "
                    "they are not an identification."
                ],
                next_steps=["propose_formulas / match_spectrum (milestone M4) for identity"],
            )
            env["_provenance"] = {
                "input_hashes": [run.sha256],
                "parents": [ftab_handle, meta["run_handle"]],
            }
            return env
        consensus, members, ameta = tables.load_aligned(_key(ftab_handle))
        row = next((c for c in consensus if c["cid"] == feature_id), None)
        if row is None:
            raise SimplyMZError(
                ErrorCode.INVALID_ARGUMENT,
                f"No consensus feature {feature_id}.",
                f"Valid ids look like {', '.join(c['cid'] for c in consensus[:3])}.",
            )
        ms = sorted(
            (m for m in members if m["cid"] == feature_id), key=lambda m: m["injection_order"]
        )
        qc = [m["area"] for m in ms if m["sample_type"] == "qc"]
        qc_cv = float(np.std(qc, ddof=1) / np.mean(qc) * 100) if len(qc) >= 2 else None
        card = {
            **row,
            "n_runs": len(ameta["runs"]),
            "qc_area_cv_pct": round(qc_cv, 2) if qc_cv is not None else None,
            "per_run": [
                {
                    "run": m["run"],
                    "type": m["sample_type"],
                    "group": m["group"],
                    "area": _sig(m["area"]),
                    "rt_min": m["rt_min"],
                }
                for m in ms[:30]
            ],
        }
        env = envelope.ok(
            f"{feature_id}: m/z {row['mz']:.4f} at {row['rt_min']:.2f} min, present in "
            f"{row['n_present']}/{len(ameta['runs'])} runs.",
            card,
            limits=["Runs where the feature was not detected are absent from per_run."],
        )
        env["_provenance"] = {"input_hashes": [], "parents": [ftab_handle]}
        return env

    def compare_groups(
        ftab_handle: str,
        group_a: str,
        group_b: str,
        blank_fold: float = 3.0,
        min_presence: float = 0.5,
        top_n: int = 10,
    ) -> dict[str, Any]:
        """Rank features that differ between two sample groups of an aligned batch.

        Blank subtraction, presence filter, documented imputation, log2 fold change
        (group_b vs group_a), Welch t-test on log2 areas and Benjamini-Hochberg FDR."""
        from simplymz_mcp.analytics.stats import SMALL_N
        from simplymz_mcp.analytics.stats import compare_groups as compare

        meta = app.store.get(ftab_handle, "ftab")
        if meta["kind"] != "aligned":
            raise SimplyMZError(
                ErrorCode.INVALID_ARGUMENT,
                "compare_groups needs an aligned batch feature table.",
                "Run detect_features(batch_handle=...) first.",
            )
        if not 1 <= top_n <= 25 or blank_fold < 1 or not 0 < min_presence <= 1:
            raise SimplyMZError(
                ErrorCode.INVALID_ARGUMENT,
                "Argument out of range.",
                "top_n 1-25, blank_fold >= 1, min_presence in (0, 1].",
            )
        consensus, members, _ = tables.load_aligned(_key(ftab_handle))
        groups = sorted({m["group"] for m in members if m["sample_type"] == "sample"})
        for g in (group_a, group_b):
            if g not in groups:
                raise SimplyMZError(
                    ErrorCode.INVALID_ARGUMENT,
                    f"No sample group {g!r}.",
                    f"Groups in this batch: {', '.join(groups)}.",
                )
        if group_a == group_b:
            raise SimplyMZError(
                ErrorCode.INVALID_ARGUMENT,
                "Pick two different groups.",
                f"Groups in this batch: {', '.join(groups)}.",
            )
        res = compare(members, consensus, group_a, group_b, blank_fold, min_presence)
        n_a, n_b = res["n_a"], res["n_b"]
        sig = [r for r in res["ranked"] if r["q_value"] is not None and r["q_value"] < 0.05]
        limits = [
            f"Rules: {res['rules']['test']}, {res['rules']['fdr']} FDR, imputation = "
            f"{res['rules']['imputation']}, blank fold {blank_fold:g}.",
            "Statistical differences are not biological conclusions; identities are not "
            "assigned here (see milestone M4 tools).",
            "Features are aligned monoisotopic peaks; isotopes were grouped before testing.",
        ]
        if min(n_a, n_b) < SMALL_N:
            limits.insert(
                0,
                f"Small sample size (n={n_a} vs n={n_b}): p-values are unstable "
                "and FDR control is weak; treat the ranking as hypotheses to "
                "confirm with more replicates.",
            )
        data = {
            "group_a": group_a,
            "group_b": group_b,
            "n_a": n_a,
            "n_b": n_b,
            "n_tested": res["n_tested"],
            "n_significant_q05": len(sig),
            "removed_blank": res["removed_blank"],
            "removed_presence": res["removed_presence"],
            "ranked": res["ranked"][:top_n],
            "rules": res["rules"],
        }
        steps = [
            f"get_feature(ftab_handle='{ftab_handle}', feature_id='{r['cid']}')"
            for r in res["ranked"][:2]
        ]
        if n_a < 2 or n_b < 2:
            env = envelope.insufficient(
                f"Need at least 2 samples per group for a test (have {n_a} and {n_b}).",
                data,
                limits=limits,
                next_steps=["Add replicate samples to the batch."],
            )
        else:
            top = res["ranked"][0] if res["ranked"] else None
            tail = (
                f"; top {top['cid']} m/z {top['mz']:.4f} at {top['rt_min']:.2f} min, "
                f"log2 FC {top['log2_fc']:+.2f}."
                if top
                else "."
            )
            env = envelope.ok(
                f"{group_b} vs {group_a} (n={n_b} vs {n_a}): {len(sig)} of {res['n_tested']} "
                f"features differ at q < 0.05{tail}",
                data,
                limits=limits,
                next_steps=steps,
            )
        env["_provenance"] = {"input_hashes": [], "parents": [ftab_handle]}
        return env

    for spec in [
        ToolSpec(
            "compare_groups",
            compare_groups.__doc__ or "",
            compare_groups,
            2000,
            {"ftab_handle": "<aftab>", "group_a": "A", "group_b": "B"},
        ),
        ToolSpec(
            "detect_features",
            detect_features.__doc__ or "",
            detect_features,
            400,
            {"run_handle": "<run>"},
        ),
        ToolSpec(
            "get_feature",
            get_feature.__doc__ or "",
            get_feature,
            CARD_BUDGET,
            {"ftab_handle": "<ftab>", "feature_id": "F00001"},
        ),
    ]:
        server.add_tool(registry.register(spec), name=spec.name, description=spec.description)
