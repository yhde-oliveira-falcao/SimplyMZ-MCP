"""MCP prompts: guided workflows with honesty rules (plan M2.T6).

Each prompt names its tools in a numbered ``Steps`` list; tests execute that sequence, so a
prompt can never refer to a tool that does not exist.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

HONESTY = """Rules:
- Cite the numbers the tools returned (value, unit, threshold) and keep each provenance_id.
- Repeat every item in `limits` that affects your conclusion; never drop a precision note.
- Do not speculate on causes beyond the possibilities listed below; say what would confirm
  each one.
- If a tool returns status "insufficient_evidence", say so plainly; it is a valid answer.
- Never change a verdict or threshold yourself; if the user wants different thresholds,
  re-run the tool with `thresholds`."""

QC_CAUSES = """Possible causes to mention only when the matching metric is not "pass":
- rt_drift_min: column temperature/equilibration, mobile-phase composition, pump issues.
- mass_error_ppm: calibration drift; recalibrate and re-check with targets.
- tic_cv_qc_pct / qc_feature_cv_pct / intensity_trend: spray instability, source fouling,
  sample degradation, injection volume.
- blank_carryover_pct: autosampler/needle carryover; add wash or blank injections.
- blank_contamination_pct: solvent, vial or system contamination.
- scan_dropouts / missingness_pct: spray failure, acquisition errors, empty scans."""


def register(server: MCPServer) -> None:
    @server.prompt(
        name="qc_batch",
        title="Did this batch pass QC?",
        description="Check a batch of LC-MS runs against QC thresholds and explain the result.",
    )
    def qc_batch_prompt(sample_sheet: str) -> str:
        return f"""Assess the quality of the LC-MS batch described by `{sample_sheet}`.

Steps:
1. load_batch(sample_sheet="{sample_sheet}")
2. qc_batch(batch_handle=<batch_handle from step 1>)
3. run_card(run_handle=<handle of the first offender of each failed or warned metric>)

Then answer in this order: the overall verdict in one sentence; a short table of metrics
that are warn or fail (value, unit, threshold, offender); what each finding means; what to
check next. If everything passes, say so in one sentence and list the metrics checked.

{HONESTY}

{QC_CAUSES}"""

    @server.prompt(
        name="explain_chromatogram",
        title="Explain a chromatogram",
        description="Summarise a run and one chromatogram (TIC or an ion) in plain language.",
    )
    def explain_chromatogram_prompt(path: str, mz: str = "") -> str:
        target = (
            f'get_chromatogram(run_handle=<run_handle>, kind="EIC", mz={mz})'
            if mz
            else 'get_chromatogram(run_handle=<run_handle>, kind="TIC")'
        )
        return f"""Explain the LC-MS run `{path}` to a chemist.

Steps:
1. load_run(path="{path}")
2. run_card(run_handle=<run_handle from step 1>)
3. {target}
4. integrate_peak(chrom_handle=<chrom_handle from step 3>, apex_rt_min=<largest peak rt>)

Describe acquisition (polarity, RT range, MS levels), any anomalies, the main peaks (RT,
height, area) and what cannot be concluded from one run.

{HONESTY}"""

    @server.prompt(
        name="compare_groups",
        title="What's different between two groups?",
        description="Find features that differ between two sample groups of a batch.",
    )
    def compare_groups_prompt(sample_sheet: str, group_a: str, group_b: str) -> str:
        return f"""Compare sample group {group_b} against group {group_a} in `{sample_sheet}`.

Steps:
1. load_batch(sample_sheet="{sample_sheet}")
2. qc_batch(batch_handle=<batch_handle from step 1>)
3. detect_features(batch_handle=<batch_handle from step 1>)
4. job_status(job_handle=<job_handle from step 3>)
5. compare_groups(ftab_handle=<ftab_handle from step 4>, group_a="{group_a}", group_b="{group_b}")
6. get_feature(ftab_handle=<ftab_handle>, feature_id=<top ranked cid>)

Report: the QC verdict first (a failing batch weakens every comparison); then the ranked
features (m/z, RT, log2 fold change, q-value) and how many were removed as blank or
low-presence; then what would make the result stronger.

{HONESTY}
- Repeat the small-sample caveat whenever it is in `limits`.
- Do not name compounds or biological effects: features here are m/z and RT only.
- A q-value is not a probability that the feature is real; do not describe it as one."""


def register_identify(server: MCPServer) -> None:
    @server.prompt(
        name="identify_peak",
        title="What is this peak?",
        description="Formula candidates, library match and a rule-assigned confidence level.",
    )
    def identify_peak_prompt(
        path: str, mz: str, rt_min: str, adduct: str = "[M+H]+", library: str = ""
    ) -> str:
        lib_steps = (
            f"""4. load_library(path="{library}")
5. match_spectrum(run_handle=<run_handle>, precursor_mz={mz}, library_handle=<lib>, rt_min={rt_min})
6. assign_confidence(evidence=[<provenance_id from step 3>, <provenance_id from step 5>])"""
            if library
            else "4. assign_confidence(evidence=[<provenance_id from step 3>])"
        )
        return f"""Identify the peak at m/z {mz}, RT {rt_min} min in `{path}`.

Steps:
1. load_run(path="{path}")
2. run_card(run_handle=<run_handle from step 1>)
3. propose_formulas(mz={mz}, adduct="{adduct}", run_handle=<run_handle>, rt_min={rt_min})
{lib_steps}

Report: the confidence level and its rule, the evidence behind it (formula candidates with
ppm and isotope fit; library hit with score, matched fragments and licence), and what would
raise the level (for Level 1: a reference standard measured under the same conditions).

{HONESTY}
- You may discuss the evidence but you must never raise the level assign_confidence
  returned, and never call a compound "identified" below Level 1.
- If the result is insufficient_evidence or Level 5, say plainly that the peak is not
  identified."""
