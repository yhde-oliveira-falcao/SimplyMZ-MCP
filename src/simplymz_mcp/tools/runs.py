"""load_run, run_card, release_handle and the run-card resource (plan M1.T5)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from simplymz_mcp.analytics import runcard
from simplymz_mcp.core import envelope
from simplymz_mcp.core.registry import Registry, ToolSpec

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from simplymz_mcp.server import App

CARD_LIMITS = [
    f"TIC trace is downsampled (binned maximum, {40} bins); narrow features may be hidden.",
    f"Anomaly rules: RT gap > {runcard.GAP_FACTOR:g}x median MS1 interval; TIC dropout < "
    f"{runcard.DROPOUT_FRACTION:.0%} of the rolling {runcard.BACKGROUND_PERCENTILE}th-percentile "
    f"background ({runcard.ROLLING_WINDOW} scans); "
    "empty scans; polarity switching.",
    "A run card describes acquisition, not data quality across a batch (see qc_batch).",
]


def register(server: MCPServer, registry: Registry, app: App) -> None:
    def load_run(path: str) -> dict[str, Any]:
        """Load an mzML/mzML.gz file under the data root and return a run: handle.

        Loading the same unchanged file again returns the same handle (cached)."""
        loaded = app.runs.load(path)
        meta = loaded.run.meta
        env = envelope.ok(
            f"Loaded {meta['n_spectra']} spectra ({meta['polarity']} mode, RT "
            f"{meta['rt_range_min'][0]} to {meta['rt_range_min'][1]} min) as {loaded.handle}.",
            {
                "run_handle": loaded.handle,
                "file": app.store.get(loaded.handle)["path"],
                "sha256": loaded.run.sha256,
                "cache_hit": loaded.cache_hit,
                "reused_handle": loaded.reused_handle,
                "n_spectra": meta["n_spectra"],
                "ms_level_counts": meta["ms_level_counts"],
                "polarity": meta["polarity"],
                "rt_range_min": meta["rt_range_min"],
                "file_warnings": meta["warnings"],
            },
            limits=["Loading validates structure only; call run_card for a summary."],
            next_steps=[f"run_card(run_handle='{loaded.handle}')"],
        )
        env["_provenance"] = {"input_hashes": [loaded.run.sha256], "parents": []}
        return env

    def run_card(run_handle: str) -> dict[str, Any]:
        """Compact run summary: metadata, downsampled TIC, MS2 counts and anomalies."""
        run = app.runs.get(run_handle)
        rel = app.store.get(run_handle, "run")["path"]
        card = runcard.run_card(run, rel)
        n = card["n_anomalies"]
        verdict = f"{rel}: {card['n_spectra']} spectra, {card['polarity']} mode, " + (
            "no acquisition anomalies detected."
            if n == 0
            else f"{n} acquisition anomal{'y' if n == 1 else 'ies'} detected."
        )
        steps = [f"get_chromatogram(run_handle='{run_handle}', kind='TIC')"]
        if n:
            steps.insert(
                0,
                "Inspect the anomaly RT ranges with get_chromatogram before "
                "integrating peaks there.",
            )
        env = envelope.ok(verdict, card, limits=CARD_LIMITS, next_steps=steps)
        env["_provenance"] = {"input_hashes": [run.sha256], "parents": [run_handle]}
        return env

    def release_handle(handle: str) -> dict[str, Any]:
        """Release a handle you no longer need. Cached data stays until evicted."""
        app.store.get(handle)  # raises an instructive error if unknown
        app.store.release(handle)
        return envelope.ok(f"Released {handle}.", {"handle": handle})

    specs = [
        ToolSpec(
            "load_run", load_run.__doc__ or "", load_run, 700, {"path": "runs/clean_pos.mzML"}
        ),
        ToolSpec("run_card", run_card.__doc__ or "", run_card, 1500, {"run_handle": "<run>"}),
        ToolSpec(
            "release_handle", release_handle.__doc__ or "", release_handle, 300, {"handle": "<run>"}
        ),
    ]
    guarded = {}
    for spec in specs:
        guarded[spec.name] = registry.register(spec)
        server.add_tool(guarded[spec.name], name=spec.name, description=spec.description)

    @server.resource(
        "simplymz://run/{run_id}/card",
        name="run_card",
        description="Run card for run:<run_id> (same content as the run_card tool).",
        mime_type="application/json",
    )
    def run_card_resource(run_id: str) -> str:
        return json.dumps(guarded["run_card"](run_handle=f"run:{run_id}"))
