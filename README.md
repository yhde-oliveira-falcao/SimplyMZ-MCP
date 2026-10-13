# SimplyMZ

[![CI](https://github.com/yhde-oliveira-falcao/simplymz-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/yhde-oliveira-falcao/simplymz-mcp/actions/workflows/ci.yml)
[![License: GPL v3](https://img.shields.io/badge/license-GPLv3-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)
![MCP](https://img.shields.io/badge/MCP-stdio-0F2A44.svg)

An MCP server that lets an AI assistant work with LC-MS / GC-MS runs (mzML) the way a
careful analytical chemist would: inspect a run, check whether a batch passed QC, compare
sample groups, and attempt peak identification with explicit evidence and honest
confidence levels.

**Design rule:** the AI plans and explains; deterministic tools compute; an append-only
evidence ledger records every result, and reports can only contain numbers from it.

Status: 0.1.0 pre-release. Research use only, not for clinical or regulatory decisions.

## Three workflows

1. **"Did last night's batch pass?"** `load_batch` + `qc_batch`: ten QC metrics (TIC CV,
   RT drift, mass error, QC feature CV, missingness, carryover, blank contamination, MS2
   stability, intensity trend, scan dropouts) with pass/warn/fail against configurable
   thresholds, offending runs named. Prompt: `/qc_batch`.
2. **"What's different between treated and control?"** `detect_features` (async) +
   `compare_groups`: blank filtering, log2 fold change, Welch t-test, Benjamini-Hochberg
   FDR, small-sample caveats. Prompt: `/compare_groups`.
3. **"What is this peak?"** `propose_formulas` (mass + isotope fit), `match_spectrum`
   (library, licence reported), `assign_confidence` (Schymanski levels 2-5 from ledger
   evidence; Level 1 is never claimed). Prompt: `/identify_peak`.

Every workflow ends with `export_report` (Markdown/HTML): numbers come from ledger slots,
and a number guard rejects any figure that cannot be traced to evidence. All 19 tools are
documented in [docs/tools.md](docs/tools.md).

## Install

Needs [uv](https://docs.astral.sh/uv/). Convert vendor files (.raw, .d, .wiff) to mzML
with ProteoWizard `msconvert` first.

Run it straight from GitHub (no PyPI release yet):

```bash
uvx --from git+https://github.com/yhde-oliveira-falcao/simplymz-mcp simplymz-mcp --root /path/to/your/mzml/folder
```

**Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "simplymz-mcp": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/yhde-oliveira-falcao/simplymz-mcp", "simplymz-mcp", "--root", "/path/to/your/mzml/folder"]
    }
  }
}
```

**Claude Code:**

```bash
claude mcp add --transport stdio simplymz-mcp -- uvx --from git+https://github.com/yhde-oliveira-falcao/simplymz-mcp simplymz-mcp --root /path/to/your/mzml/folder
```

After the PyPI release, `--from git+https://github.com/yhde-oliveira-falcao/simplymz-mcp` can be dropped (`uvx simplymz-mcp --root …`).

SimplyMZ only reads files under `--root`; state, cache and the ledger live in
`<root>/.simplymz` (or `--cache-dir`). Reports are written to
`<root>/simplymz_reports/`.

Optional: add `--with "matchms>=0.33,<0.34"` to the `uvx` command to enable
`match_spectrum(engine="matchms")` as an independent cross-check (identical scores to the
built-in engine for the methods used; see ADR 0009).

## Quick start with the sample data

The repository ships synthetic sample files with known ground truth (CC0):

```bash
git clone https://github.com/yhde-oliveira-falcao/simplymz-mcp.git
cp -r simplymz-mcp/tests/fixtures ~/simplymz-demo
claude mcp add --transport stdio simplymz-mcp -- uvx --from git+https://github.com/yhde-oliveira-falcao/simplymz-mcp simplymz-mcp --root ~/simplymz-demo
```

Then ask your assistant, for example:

- `/qc_batch sample_sheet=batch_qc/sample_sheet.csv`: did the batch pass QC?
- `/compare_groups sample_sheet=batch_qc/sample_sheet.csv group_a=A group_b=B`
- `/identify_peak path=runs/ms2_dda.mzML.gz mz=195.0877 rt_min=4.4 library=library/synthetic_library.msp`
- "Show the run card for faults/dropout.mzML.gz": a run with an injected scan dropout

| Folder | Contents |
|---|---|
| `runs/` | clean positive/negative runs; a DDA MS2 run (one compound absent from the library) |
| `batch_qc/` | 11 injections (blanks, pooled QCs, groups A and B) and `sample_sheet.csv` |
| `faults/` | one injected fault each: RT shift, mass error, intensity, contaminant, dropout, carryover |
| `library/` | synthetic MS/MS library (MSP) |

Real public data: ask for `fetch_public_dataset("openms-ffm-1")` (a pinned OpenMS LC-MS file).

## Benchmarks

| Evaluation | Result | Data |
|---|---|---|
| QC: fault at 2x/4x its threshold detected | 100% (6 fault types) | synthetic |
| QC: false fail at 0.5x threshold | 0% | synthetic |
| Formula: true formula among candidates (5 ppm) | 100% of 35 compounds | oracle masses |
| Formula: true formula ranked first with isotopes (< 400 Da) | 97-100% | simulated isotopes |
| Library: out-of-library spectra given no identity | 100% | synthetic |
| Library: decoy false positives | 0% | synthetic |
| Feature detection recall | 100% synthetic; **5 of OpenMS's 10 most intense features** on a real LC-MS file | synthetic + OpenMS test data |
| Peak area at SNR >= 100 / SNR 50 | within 3% always / ~1.5% SD | synthetic |

Full tables: [eval/results.md](eval/results.md). The comparison of Claude with and without
SimplyMZ (`eval/llm_eval.py`) has not been run yet.

## Limitations (read these)

- Validated mainly on synthetic data with known ground truth; one real public file is used
  for integration and a recall benchmark. Real-data performance, especially feature
  detection, is lower than on synthetic data.
- The built-in feature detector (masstrace-lite) is simple; pyOpenMS is planned as an
  optional engine (ADR 0001).
- Peak areas carry a precision note in every result (ADR 0008); SNR is height / RMS noise.
- Identification never exceeds Level 2 (library match); no reference-standard evidence,
  no RT prediction, no in-silico fragmentation. Formulas: C, H, N, O, P, S, Cl, Br only.
- QC thresholds are configurable defaults, not standards.
- mzML only; no vendor formats.

## Data and licences

GPL-3.0-or-later licence (see [LICENSE](LICENSE)). No third-party spectra are bundled; MassBank can be downloaded opt-in with
per-record licences (`scripts/download_library.py`). See [docs/data.md](docs/data.md).

## Documentation

| Document | What it covers |
|---|---|
| [docs/tools.md](docs/tools.md) | All 19 tools: schemas, examples, token budgets; prompts and resources |
| [docs/data.md](docs/data.md) | Sample data, the public dataset, MassBank download, licences |
| [docs/adr/](docs/adr/) | Design decisions (feature engine, storage, budgets, libraries, ledger, precision, matching) |
| [eval/results.md](eval/results.md) | Evaluation results |
| [CHANGELOG.md](CHANGELOG.md) | Release notes |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How to contribute |
| [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md), [docs/progress/](docs/progress/) | Milestones, verification gates and their results |

## Development

`uv sync`, then `uv run pytest -m "not network"`. Milestones, gates and decisions:
[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md), [docs/progress/](docs/progress/),
[docs/adr/](docs/adr/). See [CONTRIBUTING.md](CONTRIBUTING.md).
