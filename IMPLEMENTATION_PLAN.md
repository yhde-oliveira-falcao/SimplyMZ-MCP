# SimplyMZ MCP — Implementation Plan (v0.1)

*Companion to `PROJECT_BRIEF.md`. Place both at the repo root. This file is written for a coding agent (Claude Code with Opus/Sonnet) and for the human reviewer (Yuri). The agent follows it literally.*

---

## 0. How to use this plan

1. Work milestones in order: **M0 → M1 → M2 → M3 → M4 → M5 → Final Verification**.
2. Inside a milestone, work tasks in order (`M1.T1`, `M1.T2`, …) unless a task says it can run in parallel.
3. A task is done only when it is **verified** (tests written, tests run, tests pass, log entry recorded, commit made).
4. A milestone is done only when its **gate** passes (`uv run python scripts/verify.py M<n>` exits 0) and its **summary** is written and committed with a tag `m<n>-verified`.
5. **Never start milestone N+1 while gate N is red.**
6. At the start of every session, read `docs/progress/STATUS.md` first. It says where work stopped.

Suggested model split: Opus writes ADRs (M0), reviews every gate summary, and handles M3/M4 algorithm design. Sonnet implements tasks. Any model may run gates.

---

## 1. Agent operating rules (copy into `CLAUDE.md` in M0)

**Hard constraints (from brief §4):**
- The LLM plans and explains; tools compute; the ledger remembers.
- No tool ever returns raw peak arrays to the client.
- Every number in a report comes from a ledger entry.
- Tools may return `status: "insufficient_evidence"`; that is a correct result, not a failure.
- Build only from open-source libraries and public or synthetic data. No code, data or formats from past employers.

**Verification rules:**
- Every task adds or updates tests that would fail without the task's code.
- Run the task's tests, then the full fast suite, before marking a task verified.
- Never delete, skip, `xfail`, or loosen a test (tolerances included) to get green. If a test is genuinely wrong, fix it in a separate commit and log why under "Deviations".
- The total test count must not decrease between gates (the gate script checks this).
- If the same failure survives **3 fix attempts**, stop: mark the task `BLOCKED` in `STATUS.md` with the error, what was tried, and a proposed way forward. Wait for the human.
- Do not mark anything verified based on reasoning alone. Paste the actual command and actual output summary.

**Engineering rules:**
- Logs go to **stderr only**. stdout is the MCP stdio transport; any stray `print` corrupts JSON-RPC. (There is a test for this.)
- Pure functions for all science (masses, peaks, QC metrics, stats). Tools are thin wrappers.
- Units in every field name (`mz_tol_ppm`, `rt_min`, `area_counts`).
- No network access except in `fetch_public_dataset` and opt-in tests marked `network`.
- Secrets never enter the repo (gitleaks runs in pre-commit and CI).

---

## 2. Progress recording system (built in M0, used everywhere)

```
docs/
  adr/                       0001-feature-detection.md, 0002-storage.md, …
  progress/
    STATUS.md                current milestone, current task, gate states, blockers
    M0.md … M5.md            task log, one entry per task
    M0_SUMMARY.md …          milestone summary written at gate time
    gates/M0.json …          machine output of verify.py (committed)
    FINAL_VERIFICATION.md    written at the end
```

### 2.1 `STATUS.md` template
```markdown
# Status
Current milestone: M1
Current task: M1.T4 (in progress)
Last verified task: M1.T3 (commit a1b2c3d)
Gates: M0 ✅ (tag m0-verified) | M1 ⏳ | M2 ⬜ | M3 ⬜ | M4 ⬜ | M5 ⬜
Blockers: none
Next action: implement ledger triggers, then tests/unit/test_ledger.py
```

### 2.2 Task log entry template (`docs/progress/M<n>.md`)
```markdown
### M1.T3 — get_chromatogram
Status: VERIFIED            # TODO | IN_PROGRESS | VERIFIED | BLOCKED
Commit: a1b2c3d
What was built: EIC/TIC/BPC extraction with ppm window, RT range, MS level; scipy peak picking.
Files: src/simplymz_mcp/analytics/chromatogram.py, src/simplymz_mcp/tools/chromatogram.py
Tests added: tests/unit/test_chromatogram.py (9), tests/contract/test_get_chromatogram.py (3)
Task verification: `uv run pytest tests/unit/test_chromatogram.py tests/contract/test_get_chromatogram.py -q` → 12 passed
Full fast suite after task: `uv run pytest -m "not network and not slow" -q` → 71 passed, 0 failed
Lint/type: ruff ✅ mypy ✅
Acceptance criteria touched: M1-AC3, M1-AC4
Deviations / notes: none
```

### 2.3 Milestone summary template (`docs/progress/M<n>_SUMMARY.md`)
```markdown
# M1 Summary — Ingestion & run-level tools
Date: … | Tag: m1-verified | Gate file: docs/progress/gates/M1.json
## Delivered
(2–6 sentences: what now works, from a user's point of view)
## Tasks
| Task | Status | Commit | Tests |
## Acceptance criteria
| ID | Criterion | Evidence (test name / command) | Result |
## Gate output
tests: 84 passed / 0 failed / 3 skipped (network) | coverage core: 91% | ruff ✅ | mypy ✅ | budgets ✅
## Deviations from plan, and ADRs added
## Known limitations carried forward
## Reviewer sign-off (Opus review / human where required)
```

### 2.4 `scripts/verify.py M<n>` (the gate)
Runs in order, stops on first failure, writes `docs/progress/gates/M<n>.json`:
1. `ruff check .` and `ruff format --check .`
2. `mypy src/` (strict on `src/simplymz_mcp/core`, `analytics`, `annotation`)
3. `pytest -m "not network"` with coverage; fail if core coverage < 85%
4. Contract tests (schemas valid, examples validate, every tool output within token budget)
5. Milestone acceptance tests: `pytest tests/acceptance/test_m<n>.py` (each test named after its AC id, e.g. `test_M1_AC3_eic_apex_within_one_scan`)
6. All acceptance tests from earlier milestones (regression)
7. Progress checks: every task in `M<n>.md` is `VERIFIED` with a commit hash; `M<n>_SUMMARY.md` exists (allowed to be missing on first run; the script prints a reminder and exits non-zero until it exists)
8. Test count ≥ previous gate's count
9. `gitleaks detect` clean

Gate procedure: run verify → write summary from the JSON → run verify again (now passes step 7) → commit → `git tag m<n>-verified` → update `STATUS.md`.

---

## 3. Fixed decisions (defaults for the brief's open questions)

The agent writes these as ADRs in M0. Opus may change one only with a written reason in the ADR; the human approves ADRs at the M0 gate.

| # | Decision | Default | Why |
|---|---|---|---|
| 1 | Feature detection | `FeatureDetector` interface. Default engine: built-in **masstrace-lite** (numpy/scipy). pyOpenMS `FeatureFinderMetabo` as optional extra `simplymz-mcp[openms]` if the M0 spike shows it installs cleanly on all CI OSes. asari evaluated in the same spike. | Zero heavy deps for `uvx`; fully testable on synthetic ground truth; heavier engines stay pluggable |
| 2 | Storage | **SQLite** (stdlib) for handles, ledger, jobs. **Parquet** (pyarrow) for scan tables, feature tables, cached chromatograms. DuckDB deferred. | Fewest dependencies; Parquet is fast and inspectable |
| 3 | Token budget | Hard cap per tool in the tool registry (default 1,500 tokens, estimated as `len(json)/3.5`, conservative). Over budget → server truncates lists, sets `truncated: true`, returns a paging handle. Contract test fails if any example exceeds budget **without** truncation. | Enforced in code, not by convention |
| 4 | Libraries | Never bundle third-party spectra. Opt-in downloader for **MassBank** (verify current release format and per-record licence field). Every library spectrum keeps its licence; `match_spectrum` reports it. Test library = synthetic MSP generated from fixture compounds. NIST never supported for redistribution. | Licence-safe |
| 5 | Alignment | m/z (ppm) + RT (min) tolerance, greedy one-to-one by score, conflicts reported. RT warping deferred. | Enough for small batches |
| 6 | Ledger | SQLite table, append-only enforced by triggers (no UPDATE/DELETE), JSONL export. Report builder fills numbers from `{ev:…}` slots; a **number guard** rejects narrative prose containing numbers absent from referenced ledger entries. | Machine-verifiable reports |
| 7 | Test data | **Synthetic mzML generator** (psims writer; verify licence) with known ground truth and injectable faults = primary test data. 1–2 small public mzML files downloaded (not bundled) for `network`-marked integration tests. Bundled fixtures ≤ 5 MB total. | Known truth, no licence risk, tiny repo |

Other defaults: Python ≥ 3.11; `uv`; official MCP Python SDK (FastMCP API), pinned; pyteomics for mzML reading and mass/isotope calculations; matchms for spectral similarity; pandas + pyarrow; scipy; pytest + hypothesis; ruff; mypy; GPL-3.0-or-later licence (ADR 0010).

---

## 4. Shared conventions

### 4.1 Tool output envelope (every tool)
```json
{
  "status": "ok | insufficient_evidence | error",
  "verdict": "one plain-language sentence",
  "data": { },
  "limits": ["what this result does not establish"],
  "next_steps": ["suggested follow-up tool calls"],
  "provenance_id": "ev:01J…",
  "truncated": false,
  "page_handle": null
}
```
Errors are instructive: `{"status":"error","error":{"code":"POLARITY_MISMATCH","message":"Run is negative mode; [M+H]+ is invalid.","hint":"Use [M-H]- or [M+Cl]-."}}`

### 4.2 Handles
`run:<ulid>`, `batch:<ulid>`, `chrom:<ulid>`, `feat:<ulid>`, `ftab:<ulid>`, `ann:<ulid>`, `ev:<ulid>`, `job:<ulid>`. Opaque, resolvable after restart via the disk cache (keyed by file SHA-256).

### 4.3 Repo layout
```
src/simplymz_mcp/
  server.py            FastMCP app, tool/prompt/resource registration
  config.py            allowed root, limits, thresholds (TOML)
  core/                envelope, errors, handles, budget, registry
  io/                  mzml reader, validation, vendor refusal, msp/mgf
  state/               sqlite store, parquet cache, TTL
  ledger/              append-only ledger, decorators, export
  analytics/           chromatogram, peaks, integration, qc, features, align, stats
  annotation/          adducts, formulas, isotopes, library, matching, confidence
  jobs/                async executor, job store
  report/              builder, templates, number guard
  tools/               one module per MCP tool (thin)
  prompts/             qc_batch, compare_groups, identify_peak, explain_chromatogram
tests/
  unit/ component/ contract/ e2e/ acceptance/ integration/ eval/
  fixtures/            generated synthetic mzML + MSP (small)
scripts/               verify.py, generate_fixtures.py, download_demo_data.py
eval/                  harness, cached LLM responses, results tables
docs/                  adr/, progress/, tools.md (autogenerated)
```

### 4.4 Test layers
| Layer | What | Speed | Marker |
|---|---|---|---|
| Unit | Pure functions vs analytic or independently computed oracles | ms | default |
| Component | One tool on synthetic mzML | <1 s | default |
| Contract | Schema validity, example I/O, token budget, envelope shape, every tool | fast | default |
| E2E | In-process MCP client ↔ server (and one stdio subprocess test): list tools, run flagship workflows | seconds | `e2e` |
| Acceptance | One test per milestone AC | mixed | `acceptance` |
| Integration | Real public mzML | slow | `network`, `slow` |
| Eval | Fault injection, formula, abstention (deterministic, gated); LLM comparison (reported) | slow | `eval` |

Oracle rule: scientific expected values (exact masses, Gaussian areas) are computed independently of the code under test (analytic formulas or a committed element-mass table with its source cited), never by calling the same library function the code uses.

---

## M0 — Foundations

**Goal:** an empty-but-real MCP server that installs, runs, is tested in CI, has ground-truth test data, and has the verification machinery that every later milestone depends on.

| Task | Description | Verification |
|---|---|---|
| M0.T1 | Scaffold: `uv init --package`, src layout, pyproject (deps pinned with upper bounds), LICENSE, ruff/mypy/pytest config, pre-commit (ruff, gitleaks), `.gitignore` (cache dirs, data downloads). | `uv sync` clean; `pre-commit run --all-files` passes |
| M0.T2 | CI (GitHub Actions): lint, type, tests on ubuntu/macos/windows × Python 3.11/3.12; gitleaks; artifact upload of gate JSON. | CI green on a PR |
| M0.T3 | Server skeleton: FastMCP app, console script `simplymz-mcp`, `--root` / `SIMPLYMZ_ROOT`, stderr logging, `server_info` tool (version, root, limits, enabled extras). | E2E: in-process client lists tools and calls `server_info`; stdio subprocess test confirms nothing but JSON-RPC on stdout |
| M0.T4 | `core/`: envelope builder, error codes, handle generator, token-budget estimator + truncation helper, tool registry (name → budget, schema, example). | Unit tests for envelope, truncation (list shrinks, `truncated` set), budget estimate monotonic |
| M0.T5 | Synthetic data generator (`scripts/generate_fixtures.py`, seeded): compounds defined by formula, RT, peak width, height, adduct; MS1 with isotope envelopes; Gaussian noise; optional MS2 with defined fragments; faults: `rt_shift_min`, `intensity_scale`, `mass_error_ppm`, `contaminant`, `carryover_fraction`, `dropout_scans`. Fixture set: clean run (pos), clean run (neg), QC batch (2 blanks, 3 QC pools, 6 samples in 2 groups with 5 planted differential compounds), faulty variants, MS2 run with 1 compound absent from library, synthetic MSP library. Ground truth written as JSON beside each file. | Same seed → identical SHA-256; files parse with pyteomics; ground-truth JSON schema-valid; total fixture size ≤ 5 MB |
| M0.T6 | Spike + ADRs: install pyOpenMS and asari on all CI OSes in a throwaway workflow, record install time/size/licence; write ADRs 0001–0007 (§3). Check PyPI name `simplymz-mcp` availability; record fallback names. | ADR files exist with status `Proposed`; spike results attached |
| M0.T7 | Progress system: `STATUS.md`, `M0.md` … templates, `scripts/verify.py` (all 9 steps), `CLAUDE.md` with §1 rules, `tests/acceptance/test_m0.py`. | `verify.py M0` runs end to end |

**Acceptance criteria**
- **M0-AC1** CI green on all 6 matrix jobs.
- **M0-AC2** `uvx --from . simplymz-mcp --help` works; the server starts over stdio and `server_info` returns a valid envelope.
- **M0-AC3** No bytes on stdout other than JSON-RPC during a full session (test).
- **M0-AC4** Fixture generation is deterministic and fixtures parse; ground truth exists for every fixture.
- **M0-AC5** `verify.py M0` passes; `M0_SUMMARY.md` written.

**Human checkpoint:** Yuri approves (or edits) ADRs 0001–0007 → status `Accepted`. Gate M0 cannot close until then.

---

## M1 — Ingestion and run-level tools

**Goal:** load an mzML safely, summarize it in under 1.5K tokens, extract chromatograms and integrate peaks, with every result in the ledger and recoverable after restart.

| Task | Description | Verification |
|---|---|---|
| M1.T1 | Security: path resolution under allowed root (realpath, symlink escape blocked), max file size, max scans, extension allowlist; vendor formats (`.raw`, `.d`, `.wiff`, `.wiff2`, `.lcd`) refused with msconvert guidance. | Unit: traversal (`../`), symlink escape, oversize, vendor refusal message contains "msconvert" |
| M1.T2 | Reader: mzML and mzML.gz via pyteomics (indexed where available); validation (ms levels, polarity incl. switching, RT range, scan count); centroid/profile detection from CV terms with heuristic fallback; SHA-256. | Component tests on all fixtures; malformed file → instructive error |
| M1.T3 | State: SQLite store for handles/runs/batches; Parquet ScanTable cache keyed by SHA-256; TTL and bounded cache size; `release_handle`. | Restart test: new server process resolves an old `run:` handle without re-parsing (timing + cache hit flag) |
| M1.T4 | Ledger: append-only table (triggers block UPDATE/DELETE), record = op, params, input hashes, parent handles, versions (simplymz-mcp + key deps), UTC timestamp, result digest. `@ledgered` decorator on every tool; JSONL export. | Unit: UPDATE/DELETE raise; every tool call in E2E test produces exactly one entry with matching `provenance_id` |
| M1.T5 | `load_run` + `run_card` + resource `simplymz://run/{id}/card`: metadata, TIC stats, 30–60 point downsampled TIC (largest-triangle or binned max, documented), MS2 counts, anomalies (RT gaps, TIC dropouts, empty scans, polarity switching). | Contract: ≤ 1,500 tokens on largest fixture; component: `dropout_scans` fault appears in anomalies, clean run has none |
| M1.T6 | `get_chromatogram`: TIC/BPC/EIC with `mz_tol_ppm`, `rt_min` range, MS level; downsampled trace + detected peaks (scipy, prominence-based, parameters echoed in `data`). | Unit vs synthetic truth: EIC apex RT within ±1 scan; ppm window includes/excludes correctly at boundary |
| M1.T7 | `integrate_peak`: area (trapezoid, baseline method stated), height, FWHM, asymmetry (10% height), SNR (noise method stated in `limits`). | Unit: area within ±3% of analytic Gaussian area at SNR ≥ 50; overlapping-peak case returns `limits` warning |
| M1.T8 | Contract tests + `docs/tools.md` autogenerated from registry (schemas, examples, budgets). | Contract suite green; doc regenerates with no diff in CI |

**Acceptance criteria**
- **M1-AC1** All fixtures load; malformed and vendor files fail with instructive errors.
- **M1-AC2** Run Card ≤ 1,500 tokens and flags injected dropouts with zero anomalies on the clean run.
- **M1-AC3** EIC apex within ±1 scan of ground truth for every planted compound.
- **M1-AC4** Integrated areas within ±3% of analytic truth (SNR ≥ 50).
- **M1-AC5** Handles survive a server restart.
- **M1-AC6** Every tool call writes one immutable ledger entry; ledger rows cannot be modified.
- **M1-AC7** Path traversal and symlink escape are blocked.

---

## M2 — Batch QC (flagship workflow 1)

**Goal:** "Did last night's batch pass?" answered with deterministic metrics, configurable thresholds and verdicts, proven by fault injection.

| Task | Description | Verification |
|---|---|---|
| M2.T1 | `load_batch`: sample sheet CSV (`file, sample_type ∈ {sample, blank, qc}, group, injection_order`); validates files exist under root, types, duplicate orders; returns `batch:` handle. | Unit: each validation error has a hint |
| M2.T2 | QC metrics (pure functions): TIC CV across QC injections; RT drift of reference features (auto-picked stable high-intensity features, or user target list); mass accuracy (ppm) on reference masses; blank carryover ratio (blank vs preceding sample); QC replicate CV per feature (median and % above threshold); missingness; MS2 count stability; trends vs injection order (slope). | Unit tests per metric against hand-computed values |
| M2.T3 | Thresholds in `qc_defaults.toml` (pass/warn/fail), documented as configurable defaults informed by community QA/QC guidance, not standards; user override via tool argument. | Unit: boundary values produce pass/warn/fail exactly |
| M2.T4 | `qc_batch` tool: per-metric verdict, overall verdict (worst wins), top offending runs/features, `limits`; async job if run count > configurable N. Resource `simplymz://batch/{id}/qc`. | Contract ≤ budget for a 12-run batch |
| M2.T5 | Fault-injection suite: for each fault type, generate batches at 0×, 0.5×, 1×, 2×, 4× the fail threshold. | Detection matrix test (see AC) |
| M2.T6 | Prompts `/qc_batch` and `/explain_chromatogram`: tool sequence + honesty rules (cite metrics, don't speculate on causes beyond listed possibilities, state limits). | E2E: prompt renders; a scripted tool sequence from the prompt runs without error |

**Acceptance criteria**
- **M2-AC1** Clean batch: every metric `pass` (zero false fails, zero false warns).
- **M2-AC2** Each fault at ≥ 2× threshold → that metric `fail`, and only metrics plausibly affected by that fault change (allowed side-effects listed in the test).
- **M2-AC3** Fault at 0.5× threshold → not `fail`.
- **M2-AC4** Identical inputs → identical output digest (determinism).
- **M2-AC5** `qc_batch` output ≤ budget on the largest fixture batch.

---

## M3 — Features, async jobs, group comparison (flagship workflow 2)

**Goal:** "What's different between treated and control?" with blank subtraction and a ranked, statistically annotated list.

| Task | Description | Verification |
|---|---|---|
| M3.T1 | Jobs: async executor (local, thread/process pool), job store in SQLite, `job_status` (state, progress, result handle), timeout and cancellation. Tools return a `job:` handle in < 1 s when work is long. | Unit: state transitions; component: long job returns immediately, completes, result retrievable after restart |
| M3.T2 | `FeatureDetector` interface + **masstrace-lite**: build mass traces (centroids within ppm across consecutive scans), smooth, pick peaks on traces, compute area/height/SNR/RT bounds, group ¹³C isotopes (Δ = 1.00336/z) and common adducts. | Synthetic truth: recall ≥ 95%, precision ≥ 90% on clean fixtures (documented as synthetic-only) |
| M3.T3 | Optional pyOpenMS adapter (only if ADR 0001 accepted it). Same interface, same tests (marked to skip when extra not installed). | Adapter passes the interface test suite |
| M3.T4 | `detect_features` (async) → `ftab:` handle; `get_feature` → Feature Card (≤ 800 tokens). Feature tables stored as Parquet. | Contract + component |
| M3.T5 | Alignment: ppm + RT tolerance, greedy one-to-one by combined score; unmatched and conflicting features reported. | Unit: planted RT jitter within tolerance aligns; two candidates in window → best chosen, conflict logged |
| M3.T6 | `compare_groups`: blank subtraction (feature removed if sample/blank ratio < configurable fold), missing-value handling (documented rule), log2 fold change, Welch t-test, Benjamini–Hochberg FDR, top-N ranked list with effect sizes. | Unit: stats vs scipy reference on fixed arrays; component on fixture batch |
| M3.T7 | Prompt `/compare_groups` with honesty rules (statistical caveats for small n, no biological claims). | E2E prompt render + scripted sequence |

**Acceptance criteria**
- **M3-AC1** All 5 planted differential compounds appear in the top 10 of `compare_groups`.
- **M3-AC2** Blank-only contaminants are absent from the ranked list.
- **M3-AC3** Feature detection meets recall ≥ 95% / precision ≥ 90% on synthetic truth.
- **M3-AC4** Long jobs return a handle in < 1 s and complete; results survive restart.
- **M3-AC5** With n = 3 per group, output `limits` includes the small-sample caveat.

---

## M4 — Annotation ladder (flagship workflow 3)

**Goal:** "What is this peak?" with candidates, evidence and a rule-assigned confidence level, or an honest `insufficient_evidence`.

| Task | Description | Verification |
|---|---|---|
| M4.T1 | Adduct table (positive and negative common adducts, multiply charged optional); neutral-mass computation; polarity-mismatch errors with suggested adducts. | Unit vs independent oracle masses |
| M4.T2 | Formula enumeration (CHNOPS; Cl/Br optional) within `mz_tol_ppm`; filters: RDBE ≥ 0 and integer-consistent for the ion, element-ratio rules (Seven-Golden-Rules subset, documented); ranked by ppm error. | Unit: oracle compound set (≥ 20 compounds, masses computed from committed element table) — true formula present in candidates for 100% at 5 ppm |
| M4.T3 | Isotope fit: theoretical pattern (pyteomics isotopologues) vs observed M+1/M+2 from the MS1 scan at apex; score; candidates with impossible patterns rejected. | Synthetic: with isotope data, true formula rank 1 for ≥ 90% of oracle set below 400 Da |
| M4.T4 | Library layer: MSP/MGF loading via matchms; library registry (name, version, source URL, licence per spectrum); precursor index; MassBank opt-in downloader (`scripts/download_library.py`, never bundled). | Component on synthetic MSP; licence field propagated to results |
| M4.T5 | `match_spectrum`: CosineGreedy / ModifiedCosine (configurable), min matched peaks, precursor ppm gate; returns top hits with matched-peak pairs (capped), scores, licence. | Synthetic: in-library compound → correct top-1; decoys (shuffled fragments) → no hit above threshold |
| M4.T6 | `assign_confidence`: table-driven, versioned rules following Schymanski levels (5 exact mass → 4 unequivocal formula → 3 tentative candidate → 2 library match). Level 1 never assigned in v0.1 (no reference-standard evidence type yet; stated in `limits`). Input is evidence handles only; no argument can set the level directly. | Unit: rule table fully covered; attempt to pass a level → schema rejection |
| M4.T7 | `propose_formulas` tool and prompt `/identify_peak` (honesty rules: Claude may discuss evidence but never raise the level; say "insufficient evidence" plainly). | E2E: scripted identify workflow on in-library and out-of-library peaks |

**Acceptance criteria**
- **M4-AC1** True formula in candidate list for 100% of oracle compounds at 5 ppm.
- **M4-AC2** With isotope data, true formula ranked first for ≥ 90% of oracle compounds < 400 Da.
- **M4-AC3** In-library synthetic spectra → correct top-1 match and Level 2.
- **M4-AC4** Out-of-library spectrum → `insufficient_evidence` (or Level ≥ 3 with no library claim) in 100% of cases.
- **M4-AC5** Decoy spectra never exceed the match threshold.
- **M4-AC6** Polarity mismatch returns an instructive error naming valid adducts.

---

## M5 — Report, public data, evaluation, release

**Goal:** a verifiable report, a reproducible benchmark, and an installable 0.1.0 with a README that sells it.

| Task | Description | Verification |
|---|---|---|
| M5.T1 | `export_report` (Markdown + HTML): numeric content rendered only from `{ev:…}` slots; narrative sections supplied by the client pass through the **number guard** (any numeric token not traceable to a referenced ledger entry → error listing the offending numbers); provenance appendix (versions, file hashes, parameters, ledger IDs). | Unit: report with an invented number is rejected; valid report renders; every number in output maps to a ledger entry (property test) |
| M5.T2 | `fetch_public_dataset`: allowlisted hosts, requires `confirm: true`, size cap, checksum, saves under root. `scripts/download_demo_data.py`. Pick 1–2 small public mzML studies; record accession, licence, size in `docs/data.md`. | Unit with mocked HTTP; `network` test downloads and checksums |
| M5.T3 | Real-data integration tests (`network`, `slow`): load → run card → chromatogram → features → QC on the public files; all outputs within budget; no crashes. | Runs in a scheduled CI job, not on every PR |
| M5.T4 | Eval harness (`eval/`): **gated deterministic evals** = fault-injection matrix (M2), formula oracle (M4), abstention (M4). **Reported LLM eval** = Claude alone vs Claude + SimplyMZ on formula accuracy and confidence calibration, plus QC fault-flagging via the MCP client; model ID pinned; responses cached to disk; cost cap in config; API key from env only. Results to `eval/results.md`. | Deterministic evals pass thresholds; LLM eval runs once and writes the table (numbers reported, not gated) |
| M5.T5 | Docs: README (what/why, 3 workflows, install via `uvx simplymz-mcp`, Claude Desktop and Claude Code config snippets, benchmark table, limitations, research-use-only, licence notes), CONTRIBUTING, CHANGELOG, regenerated `docs/tools.md`. | Markdown lint; config snippets tested by E2E launching the exact command |
| M5.T6 | Packaging: build wheel/sdist, TestPyPI upload, CI job installs from TestPyPI in a clean env on 3 OSes and runs `simplymz-mcp --help` + E2E smoke. Version 0.1.0. | CI job green |
| M5.T7 | Demo GIF/recording (human task; agent prepares the script and dataset). | File present in `docs/media/` |

**Acceptance criteria**
- **M5-AC1** Reports with untraceable numbers are rejected; every number in a valid report traces to the ledger.
- **M5-AC2** Pipeline runs end to end on at least one real public mzML.
- **M5-AC3** Deterministic evals meet M2/M4 thresholds; LLM eval table exists in `eval/results.md`.
- **M5-AC4** Clean install from TestPyPI works on Linux, macOS, Windows.
- **M5-AC5** README contains install, config, three workflows, benchmark table, limitations.

---

## Final Verification — Definition of Done for v0.1

Run `uv run python scripts/verify.py FINAL`. It executes everything below and writes `docs/progress/FINAL_VERIFICATION.md` with command, output summary and ✅/❌ per line. **The project is complete only when every line is ✅ and the human sign-off is recorded.**

**A. Process integrity**
1. Tags `m0-verified` … `m5-verified` exist, in order, each on a commit whose gate JSON passed.
2. Every task in `M0.md`–`M5.md` is `VERIFIED` with a commit hash; no `BLOCKED` or `TODO` remains.
3. All six milestone summaries exist and list every acceptance criterion with evidence.
4. Test count never decreased across gates; no `skip`/`xfail` exists outside `network`/optional-extra markers (scripted grep).

**B. Quality**
5. From a fresh clone: `uv sync && uv run pytest -m "not network"` → 0 failures on all CI OSes.
6. Network and eval suites pass in their scheduled job (latest run linked).
7. ruff, ruff format, mypy clean; core coverage ≥ 85%.
8. Every acceptance test from M0–M5 passes in one run (`pytest -m acceptance`).

**C. Product behaviour (E2E over stdio, scripted MCP client)**
9. Server lists ~15 tools, 4 prompts, resources; every tool output validates against its schema and is within its token budget.
10. Workflow 1: QC on the faulty fixture batch flags exactly the injected faults; clean batch passes.
11. Workflow 2: group comparison returns all planted differential compounds in the top 10 with blanks removed.
12. Workflow 3: identification returns Level 2 for an in-library compound and `insufficient_evidence` for the out-of-library one.
13. `export_report` for each workflow renders, and the number guard rejects a tampered narrative.
14. Restart mid-session: handles and ledger survive.

**D. Safety, licence, hygiene**
15. Path traversal, symlink escape, oversize and vendor files are refused.
16. No network calls outside `fetch_public_dataset` (test with network disabled).
17. `gitleaks detect` clean over full history.
18. Dependency licence report (`pip-licenses`) attached; no copyleft dependency in the core install; no third-party spectra bundled; `docs/data.md` lists every dataset and licence.
19. No code or data from past employers (human attests).

**E. Release**
20. `uvx simplymz-mcp` from TestPyPI works on 3 OSes; version 0.1.0; CHANGELOG entry.
21. README complete (M5-AC5); `eval/results.md` present; demo GIF present.

**F. Human sign-off (Yuri)**
22. Installs SimplyMZ in Claude Desktop or Claude Code via the README snippet and runs the three workflows on the bundled data.
23. Spot-checks one report: picks 3 numbers and finds them in the ledger.
24. Records sign-off line in `FINAL_VERIFICATION.md`. Only then: publish to PyPI and announce.

---

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Heavy scientific deps break `uvx` installs on some OS | Core uses numpy/scipy/pyteomics/matchms/pyarrow only; heavy engines are extras; 3-OS CI from M0 |
| Synthetic data hides real-world mess | M5 real-data integration tests; thresholds labelled "synthetic"; post demo to MS subreddits for feedback |
| Host tool-call timeouts on large files | Async job pattern from M3; scan/size limits; cached parsing |
| Agent "games" tests to pass gates | Rules in §1, test-count check, no-skip grep, Opus review of each summary, independent oracles |
| Library licences | Never bundle; per-spectrum licence propagated; NIST excluded |
| Competing MCP server appears | Re-check landscape before announcing; differentiator is QC + ledger + abstention |
| Scope creep | Brief §11 non-goals are binding; new ideas go to `docs/backlog.md`, not into milestones |
