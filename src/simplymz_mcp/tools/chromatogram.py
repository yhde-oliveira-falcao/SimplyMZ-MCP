"""get_chromatogram and integrate_peak (plan M1.T6, M1.T7).

A chrom: handle stores only the extraction parameters; traces are recomputed from the
cached run, so handles stay valid across restarts without extra storage.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any, Literal

from simplymz_mcp.analytics import integrate as integ
from simplymz_mcp.analytics.chromatogram import ChromParams, detect_peaks, extract
from simplymz_mcp.analytics.runcard import downsample_max
from simplymz_mcp.core import envelope
from simplymz_mcp.core.errors import ErrorCode, SimplyMZError
from simplymz_mcp.core.registry import Registry, ToolSpec

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from simplymz_mcp.server import App

TRACE_POINTS = 50


def _sig(v: float) -> float:
    return float(f"{v:.3g}")


def register(server: MCPServer, registry: Registry, app: App) -> None:
    def _trace(chrom_handle: str) -> tuple[Any, Any, ChromParams, dict[str, Any], str]:
        meta = app.store.get(chrom_handle, "chrom")
        run = app.runs.get(meta["run_handle"])
        params = ChromParams(**meta["params"])
        rt, y = extract(run, params)
        return rt, y, params, meta, run.sha256

    def get_chromatogram(
        run_handle: str,
        kind: Literal["TIC", "BPC", "EIC"] = "EIC",
        mz: float | None = None,
        mz_tol_ppm: float = 10.0,
        rt_start_min: float | None = None,
        rt_end_min: float | None = None,
        ms_level: int = 1,
    ) -> dict[str, Any]:
        """Extract a TIC, BPC or EIC (needs mz; window = mz +/- mz_tol_ppm) and detect peaks.

        Returns a downsampled trace, detected peaks and a chrom: handle for integrate_peak."""
        if kind == "EIC" and (mz is None or mz <= 0):
            raise SimplyMZError(
                ErrorCode.INVALID_ARGUMENT,
                "EIC needs a positive mz.",
                "Pass mz (the ion m/z, e.g. 195.0877 for caffeine [M+H]+).",
            )
        if not 0 < mz_tol_ppm <= 1000:
            raise SimplyMZError(
                ErrorCode.INVALID_ARGUMENT,
                "mz_tol_ppm must be in (0, 1000].",
                "Typical values: 5-10 ppm (Orbitrap/TOF), 20-50 ppm (older TOF).",
            )
        if rt_start_min is not None and rt_end_min is not None and rt_end_min <= rt_start_min:
            raise SimplyMZError(
                ErrorCode.INVALID_ARGUMENT,
                "rt_end_min must exceed rt_start_min.",
                "Give an RT range in minutes, start < end.",
            )
        run = app.runs.get(run_handle)
        params = ChromParams(
            kind, mz if kind == "EIC" else None, mz_tol_ppm, rt_start_min, rt_end_min, ms_level
        )
        rt, y = extract(run, params)
        if rt.size == 0:
            raise SimplyMZError(
                ErrorCode.INVALID_ARGUMENT,
                f"No MS{ms_level} scans in the requested RT range.",
                "Check rt_start_min/rt_end_min against the run card.",
            )
        handle = app.store.create("chrom", {"run_handle": run_handle, "params": asdict(params)})
        picked = detect_peaks(rt, y)
        xs, ys = downsample_max(rt, y, TRACE_POINTS)
        label = kind if kind != "EIC" else f"EIC m/z {mz:.4f} +/- {mz_tol_ppm:g} ppm"
        data = {
            "chrom_handle": handle,
            "label": label,
            "n_points": int(rt.size),
            "trace": {"rt_min": [round(v, 3) for v in xs], "intensity": [_sig(v) for v in ys]},
            "peaks": picked["peaks"],
            "n_peaks_found": picked["n_found"],
            "peak_picking": picked["params"],
        }
        limits = [
            f"Trace downsampled to <= {TRACE_POINTS} points (binned maximum).",
            "Peaks are detected on the full-resolution trace; integrate_peak gives areas.",
        ]
        steps = [f"integrate_peak(chrom_handle='{handle}', apex_rt_min=<peak rt>)"]
        prov = {"input_hashes": [run.sha256], "parents": [run_handle]}
        if float(y.max()) <= 0:
            env = envelope.insufficient(
                f"No signal for {label} in this run.",
                data,
                limits=[
                    *limits,
                    "Absence of signal can mean the ion is absent, below the "
                    "detection limit, in the other polarity, or outside the ppm window.",
                ],
                next_steps=["Check polarity and adduct, or widen mz_tol_ppm."],
            )
        else:
            n = len(picked["peaks"])
            tail = "."
            if n:
                top = max(picked["peaks"], key=lambda p: p["height_counts"])
                tail = f", largest at {top['rt_min']} min."
            env = envelope.ok(
                f"{label}: {n} peak{'s' if n != 1 else ''} detected{tail}",
                data,
                limits=limits,
                next_steps=steps,
            )
        env["_provenance"] = prov
        return env

    def integrate_peak(
        chrom_handle: str,
        apex_rt_min: float | None = None,
        rt_start_min: float | None = None,
        rt_end_min: float | None = None,
    ) -> dict[str, Any]:
        """Integrate one peak of a chromatogram: area, height, FWHM, asymmetry, SNR.

        Give rt_start_min and rt_end_min for fixed bounds, or apex_rt_min (or nothing: the
        largest peak) for automatic bounds.

        Precision disclosure: SNR is height / RMS noise (not USP peak-to-peak). At SNR 50-100
        single-trace areas have ~1.5% relative SD, so about 1 in 20 deviates by more than 3%;
        at SNR >= 100 validation traces were all within 3%. Every result repeats the
        disclosure that applies to it in `limits` and `data.area_precision`; pass it on to the
        user when reporting areas."""
        if (rt_start_min is None) != (rt_end_min is None):
            raise SimplyMZError(
                ErrorCode.INVALID_ARGUMENT,
                "Give both rt_start_min and rt_end_min, or neither.",
                "Omit both to use automatic bounds around apex_rt_min.",
            )
        rt, y, _params, meta, sha = _trace(chrom_handle)
        try:
            res = integ.integrate(rt, y, rt_start_min, rt_end_min, apex_rt_min)
        except ValueError as exc:
            raise SimplyMZError(
                ErrorCode.INVALID_ARGUMENT,
                f"Cannot integrate: {exc}.",
                "Widen the RT window or check the chromatogram.",
            ) from exc
        prov = {"input_hashes": [sha], "parents": [chrom_handle, meta["run_handle"]]}
        method = res.pop("method")
        warnings = res.pop("warnings")
        limits = [
            res["area_precision"]["note"],
            *warnings,
            f"Area method: {method['area']}.",
        ]
        if res["height_counts"] <= 0:
            env = envelope.insufficient(
                "No peak above baseline in the chosen window.",
                res,
                limits=limits,
                next_steps=["Check the window with get_chromatogram."],
            )
        else:
            snr = "undefined SNR" if res["snr"] is None else f"SNR {res['snr']:g} (RMS)"
            precision = {
                "within_3pct": "area expected within +/-3%",
                "approx_3pct": "area ~1.5% SD; 1 in 20 traces exceeds +/-3%",
                "not_validated": "area precision not validated at this SNR",
                "unknown": "area precision not estimable (no measurable noise)",
            }[res["area_precision"]["tier"]]
            env = envelope.ok(
                f"Peak at {res['rt_apex_min']} min: area {res['area_counts_min']:g} counts*min, "
                f"height {res['height_counts']:g} counts, {snr}; {precision}.",
                res,
                limits=limits,
                next_steps=["Record this area; compare across runs once batches exist (M2)."],
            )
        env["_provenance"] = prov
        return env

    for spec in [
        ToolSpec(
            "get_chromatogram",
            get_chromatogram.__doc__ or "",
            get_chromatogram,
            1500,
            {"run_handle": "<run>", "kind": "EIC", "mz": 195.087652, "mz_tol_ppm": 10},
        ),
        ToolSpec(
            "integrate_peak",
            integrate_peak.__doc__ or "",
            integrate_peak,
            900,
            {"chrom_handle": "<chrom>", "apex_rt_min": 4.4},
        ),
    ]:
        server.add_tool(registry.register(spec), name=spec.name, description=spec.description)
