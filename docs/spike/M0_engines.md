# M0.T6 spike: optional feature-detection engines

Date: 2026-10-04. Python 3.12, `uv pip install` into a fresh venv.

| Engine | Version | Licence | Install time (Linux) | Venv size (Linux) | Import |
|---|---|---|---|---|---|
| SimplyMZ core (baseline) | 0.1.0.dev0 | GPL-3.0-or-later | n/a | 101 MB | ✅ |
| pyOpenMS | 3.6.0 | BSD-3-Clause | ~2 s (wheel cached by uv) | 297 MB | ✅ |
| asari-metabolomics | 1.18.5 | BSD-3-Clause | ~3 s (wheel cached by uv) | 468 MB (13 direct deps) | ✅ |

**Linux only so far.** macOS and Windows results come from the manual workflow
`.github/workflows/spike-engines.yml` (Actions tab → spike-engines → Run). Paste its
step summaries here before ADR 0001 is accepted.

Install times are not representative of a cold machine (uv cache); sizes are.

## PyPI name check
2026-10-12: `simplymz`, `simplymz-mcp` and `simply-mz` all returned 404 on
pypi.org/pypi/<name>/json. Availability can change until the
name is reserved by a first upload (TestPyPI does not reserve PyPI).
