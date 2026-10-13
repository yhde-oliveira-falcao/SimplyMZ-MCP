# ADR 0007: Test data
Status: Accepted · Date: 2026-10-04 · Accepted by Yuri Falcao (chat, 2026-10-04)

## Decision
Primary test data = the synthetic mzML generator (`simplymz_mcp.synth`, psims writer,
Apache-2.0) with known ground truth and injectable faults. 1–2 small public mzML files are
downloaded (never bundled) for `network`-marked tests in M5. Bundled fixtures ≤ 5 MB.

## Implementation notes (M0.T5)
* Ground truth uses an element table from NIST kept separate from pyteomics (oracle rule);
  a test cross-checks the two (agree within 5e-6 u).
* 20 runs + ground truth + sample sheet + MSP = 1.5 MB. All but one run are `.mzML.gz`
  (gzip mtime 0); `runs/clean_pos.mzML` stays plain so both formats are exercised.
* Determinism: same seed → identical SHA-256 on the same platform (tested). Across
  platforms the zlib build can change bytes, so `generate_fixtures.py --check` compares a
  platform-independent content digest of decoded arrays and only warns on byte differences.
* `.gitattributes` marks fixtures `-text`; pre-commit text fixers exclude them.
