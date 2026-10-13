# Status
Current milestone: M5
Current task: Final Verification (human items open)
Last verified task: M5.T6 (commit 3f01a44); release fix 337618e
Gates: M0 ⚠️ pass with waiver (not tagged) | M1 ⚠️ pass with waiver (not tagged) | M2 ⚠️ pass with waiver (not tagged) | M3 ⚠️ pass with waivers (not tagged) | M4 ⚠️ pass with waiver (not tagged) | M5 ⚠️ local pass, pending human (not tagged)
Blockers: none
Next action: M5 gate; then Final Verification. Human: run eval/llm_eval.py with ANTHROPIC_API_KEY; enable TestPyPI trusted publishing and run the release workflow; record the demo (docs/media/DEMO_SCRIPT.md).

## Human / external items
- [ ] LLM evaluation: `ANTHROPIC_API_KEY=... uv run python -m eval.llm_eval` (writes the table into eval/results.md)
- [ ] TestPyPI: add trusted publisher, push tag v0.1.0rc1, then add `Release evidence M5: <run URL>` below
- [ ] Demo GIF per docs/media/DEMO_SCRIPT.md
- [x] ADR 0009 accepted with amendment (matchms optional, disclosed; backlog for final report)
- [x] ADRs 0001–0007 Accepted by Yuri (chat, 2026-10-04)
- [x] CI evidence for M0 (recorded 2026-10-12; gates still to be re-run and tagged) (replace the waiver below with a line `CI evidence M0: https://github.com/<user>/<repo>/actions/runs/<id>`, then re-run `verify.py M0` and tag `m0-verified`)
- [ ] spike-engines workflow on macOS/Windows; paste results into docs/spike/M0_engines.md

CI evidence M0: https://github.com/yhde-oliveira-falcao/simplymz-mcp/actions/runs/38318114530
CI evidence M1: https://github.com/yhde-oliveira-falcao/simplymz-mcp/actions/runs/38318114530
CI evidence M2: https://github.com/yhde-oliveira-falcao/simplymz-mcp/actions/runs/38318114530
CI evidence M3: https://github.com/yhde-oliveira-falcao/simplymz-mcp/actions/runs/38318114530
CI evidence M4: https://github.com/yhde-oliveira-falcao/simplymz-mcp/actions/runs/38318114530
CI evidence M5: https://github.com/yhde-oliveira-falcao/simplymz-mcp/actions/runs/38318114530

## Naming (2026-10-12)
Project name is SimplyMZ (see CHANGELOG). Fixtures regenerated (they embed
the software id), uv.lock regenerated. After regeneration: 460 passed / 2 skipped (matchms
optional) including network tests; clean wheel install answers over stdio and parses mzML;
gitleaks clean. Gate JSONs in docs/progress/gates/ predate the rename: re-run
`uv run python scripts/verify.py M5` and `... FINAL` on GitHub CI before tagging.
