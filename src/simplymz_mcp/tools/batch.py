"""load_batch (plan M2.T1), qc_batch and the batch QC resource (plan M2.T4)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from simplymz_mcp.analytics.qc import BatchRun, compute_qc, load_thresholds
from simplymz_mcp.analytics.sheet import parse_sample_sheet
from simplymz_mcp.core import envelope
from simplymz_mcp.core.errors import ErrorCode, SimplyMZError
from simplymz_mcp.core.registry import Registry, ToolSpec
from simplymz_mcp.io.mzml import sha256_file
from simplymz_mcp.io.security import resolve_data_path

MAX_SYNC_RUNS = 60  # larger batches run as an asynchronous job
QC_BUDGET = 2000

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from simplymz_mcp.server import App


def register(server: MCPServer, registry: Registry, app: App) -> dict[str, Any]:
    def load_batch(sample_sheet: str) -> dict[str, Any]:
        """Load a batch from a CSV sample sheet (file, sample_type in sample/blank/qc, group,
        injection_order). File paths are relative to the sheet's folder. Returns batch:."""
        sheet_path = resolve_data_path(app.config.root, sample_sheet, app.config.limits)
        if sheet_path.suffix.lower() != ".csv":
            raise SimplyMZError(
                ErrorCode.UNSUPPORTED_FORMAT,
                "The sample sheet must be CSV.",
                "Save it as .csv with the four required columns.",
            )
        rows = parse_sample_sheet(sheet_path.read_text(encoding="utf-8-sig"))
        root = app.config.root.resolve()
        sheet_dir = PurePosixPath(sheet_path.parent.relative_to(root).as_posix())
        entries, missing = [], []
        for r in rows:
            rel = str(sheet_dir / r.file) if str(sheet_dir) != "." else r.file
            try:
                loaded = app.runs.load(rel)
            except SimplyMZError as exc:
                missing.append(f"{r.file} ({exc.code})")
                continue
            entries.append(
                {
                    "file": rel,
                    "run_handle": loaded.handle,
                    "sha256": loaded.run.sha256,
                    "sample_type": r.sample_type,
                    "group": r.group,
                    "injection_order": r.injection_order,
                    "polarity": loaded.run.meta["polarity"],
                }
            )
        if missing:
            raise SimplyMZError(
                ErrorCode.FILE_NOT_FOUND
                if all("FILE_NOT_FOUND" in m for m in missing)
                else ErrorCode.INVALID_ARGUMENT,
                f"{len(missing)} file(s) in the sheet could not be loaded: "
                + ", ".join(missing[:5])
                + ("..." if len(missing) > 5 else "")
                + ".",
                "Paths are relative to the sample sheet's folder; check names and formats.",
            )
        pols = {e["polarity"] for e in entries}
        if len(pols) > 1:
            raise SimplyMZError(
                ErrorCode.POLARITY_MISMATCH,
                f"Batch mixes polarities: {sorted(pols)}.",
                "Load positive and negative runs as separate batches.",
            )
        handle = app.store.create(
            "batch", {"sheet": sheet_path.relative_to(root).as_posix(), "entries": entries}
        )
        types = Counter(e["sample_type"] for e in entries)
        groups = sorted({e["group"] for e in entries if e["sample_type"] == "sample"})
        warnings = []
        if types["qc"] < 3:
            warnings.append(f"Only {types['qc']} QC injection(s); QC precision metrics need >= 3.")
        if types["blank"] == 0:
            warnings.append("No blanks; carryover and contamination cannot be assessed.")
        env = envelope.ok(
            f"Loaded batch of {len(entries)} runs ({types['sample']} samples in "
            f"{len(groups)} group(s), {types['qc']} QCs, {types['blank']} blanks) as {handle}.",
            {
                "batch_handle": handle,
                "n_runs": len(entries),
                "counts": dict(types),
                "groups": groups,
                "polarity": pols.pop(),
                "runs": [
                    {k: e[k] for k in ("file", "sample_type", "group", "injection_order")}
                    for e in entries[:30]
                ],
                "warnings": warnings,
            },
            limits=["Loading checks files and the sheet only; call qc_batch for quality."],
            next_steps=[f"qc_batch(batch_handle='{handle}')"],
        )
        env["_provenance"] = {
            "input_hashes": [sha256_file(sheet_path), *[e["sha256"] for e in entries]],
            "parents": [],
        }
        return env

    def qc_batch(
        batch_handle: str,
        targets: list[dict[str, float]] | None = None,
        thresholds: dict[str, dict[str, float]] | None = None,
    ) -> dict[str, Any]:
        """Batch QC: per-metric pass/warn/fail and an overall verdict (worst metric wins).

        Metrics: TIC CV over QCs, RT drift, mass error, QC feature CV, missingness, blank
        carryover, blank contamination, MS2 count CV, intensity trend, scan dropouts.
        Optional targets [{"mz": ..., "rt_min": ...}] give absolute mass accuracy; optional
        thresholds {"metric": {"warn": x, "fail": y}} override the defaults."""
        meta = app.store.get(batch_handle, "batch")
        if len(meta["entries"]) > MAX_SYNC_RUNS:
            from simplymz_mcp.tools.jobs import submit_tool_job

            return submit_tool_job(
                app,
                "qc_batch",
                qc_core,
                {"batch_handle": batch_handle, "targets": targets, "thresholds": thresholds},
                QC_BUDGET,
            )
        return qc_core(None, batch_handle, targets, thresholds)

    def qc_core(
        ctx: Any,
        batch_handle: str,
        targets: list[dict[str, float]] | None = None,
        thresholds: dict[str, dict[str, float]] | None = None,
    ) -> dict[str, Any]:
        meta = app.store.get(batch_handle, "batch")
        entries = meta["entries"]
        try:
            th = load_thresholds(thresholds)
        except (KeyError, ValueError) as exc:
            raise SimplyMZError(
                ErrorCode.INVALID_ARGUMENT,
                f"Bad threshold override: {exc}.",
                f"Valid metrics: {', '.join(load_thresholds())}; each needs warn <= fail.",
            ) from exc
        for t in targets or []:
            if not {"mz", "rt_min"} <= t.keys():
                raise SimplyMZError(
                    ErrorCode.INVALID_ARGUMENT,
                    "Each target needs mz and rt_min.",
                    'Example: [{"mz": 195.0877, "rt_min": 4.4}]',
                )
        if ctx is not None:
            ctx.progress(0.1, "loading runs")
        runs = [
            BatchRun(
                PurePosixPath(e["file"]).name,
                e["sample_type"],
                e["injection_order"],
                app.runs.get(e["run_handle"]),
            )
            for e in entries
        ]
        res = compute_qc(runs, th, targets)
        metrics = res["metrics"]
        failed = [k for k, m in metrics.items() if m["verdict"] == "fail"]
        warned = [k for k, m in metrics.items() if m["verdict"] == "warn"]
        n_qc = sum(r.sample_type == "qc" for r in runs)

        def fmt(k: str) -> str:
            m = metrics[k]
            return f"{k} {m['value']:g} {m['unit']} (fail > {m['fail']:g})"

        word = {"pass": "PASSES", "warn": "passes with WARNINGS", "fail": "FAILS"}[res["overall"]]
        verdict_text = f"Batch {word} QC"
        if failed:
            verdict_text += ": " + "; ".join(fmt(k) for k in failed[:3])
        if warned:
            verdict_text += f"; {len(warned)} warning(s): {', '.join(warned[:4])}"
        verdict_text += "."
        steps = [
            f"{k}: inspect {metrics[k]['offenders'][0]} with run_card / get_chromatogram"
            for k in failed + warned
            if metrics[k]["offenders"]
        ]
        limits = [
            "Thresholds are configurable defaults informed by common QA/QC practice, not a "
            "standard; override them for your method.",
            "Reference features were "
            + (
                "user targets."
                if targets
                else "picked automatically from the QC injections "
                "(stable, isolated, high-intensity)."
            ),
            "Mass error is "
            + (
                "absolute against the target m/z."
                if targets
                else "relative to the QC median; give targets for absolute accuracy."
            ),
            "QC verdicts describe data quality, not why a problem happened.",
        ]
        keep = ("value", "unit", "verdict", "warn", "fail", "offenders")
        data = {
            "overall": res["overall"],
            "metrics": {k: {kk: m[kk] for kk in keep} for k, m in metrics.items()},
            "reference_mode": res["reference_mode"],
            "reference_features": res["reference_features"],
            "n_runs": res["n_runs"],
            "n_qc": n_qc,
        }
        if n_qc == 0 and not targets:
            env = envelope.insufficient(
                "Batch has no QC injections, so precision, drift and trend metrics cannot be "
                "assessed; only blank and dropout checks ran.",
                data,
                limits=limits,
                next_steps=["Add pooled QC injections to the sheet, or pass targets."],
            )
        else:
            env = envelope.ok(verdict_text, data, limits=limits, next_steps=steps[:4])
        env["_provenance"] = {
            "input_hashes": [e["sha256"] for e in entries],
            "parents": [batch_handle],
        }
        return env

    guarded = {}
    for spec in [
        ToolSpec(
            "load_batch",
            load_batch.__doc__ or "",
            load_batch,
            1500,
            {"sample_sheet": "batch_qc/sample_sheet.csv"},
        ),
        ToolSpec(
            "qc_batch", qc_batch.__doc__ or "", qc_batch, QC_BUDGET, {"batch_handle": "<batch>"}
        ),
    ]:
        guarded[spec.name] = registry.register(spec)
        server.add_tool(guarded[spec.name], name=spec.name, description=spec.description)

    @server.resource(
        "simplymz://batch/{batch_id}/qc",
        name="batch_qc",
        description="QC report for batch:<batch_id> with default thresholds (same as qc_batch).",
        mime_type="application/json",
    )
    def batch_qc_resource(batch_id: str) -> str:
        return json.dumps(guarded["qc_batch"](batch_handle=f"batch:{batch_id}"))

    return guarded
