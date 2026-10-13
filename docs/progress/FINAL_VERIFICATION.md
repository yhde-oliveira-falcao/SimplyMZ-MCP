# Final Verification

Commit 49eb842 · 2026-10-06T00:35:26+00:00 · 9 ✅ · 10 ⏳ · 0 ❌

**Complete:** no — every row must be ✅

| Group | Status | Item | Evidence |
|---|---|---|---|
| A | ⏳ | 1. Tags m0-verified … m5-verified exist | missing m0-verified, m1-verified, m2-verified, m3-verified, m4-verified, m5-verified; tagging waits for CI evidence (waivers in STATUS.md) |
| A | ⏳ | 2. Every task VERIFIED, none BLOCKED/TODO/DEFERRED | M3.T3 DEFERRED; M5.T7 DEFERRED |
| A | ✅ | 3. Six milestone summaries list every AC with evidence | M0-M5 complete |
| A | ✅ | 4. Test count never decreased; no unexplained skip/xfail | M0 85 → M1 195 → M2 260 → M3 316 → M4 451 → M5 458; skips only for optional matchms, Windows symlinks, missing uvx |
| B | ⏳ | 5. Fresh clone: uv sync && pytest -m 'not network' → 0 failures on all CI OSes | local (isolated worktree, 3f70c52; code changed since: ['scripts/final_verify.py', 'scripts/verify.py']): 456 passed / 0 failed / 2 skipped; core coverage 97.6%; 3-OS CI pending |
| B | ⏳ | 6. Network and eval suites pass in the scheduled job | local run: 4 passed, 458 deselected in 11.48s; scheduled CI run link pending |
| B | ✅ | 7. ruff, ruff format, mypy clean; core coverage ≥ 85% | ruff/format ✅, mypy ✅, core coverage 97.6% |
| B | ✅ | 8. All M0-M5 acceptance tests pass in one gate run | M5: 5 passed in 33.89s; M0-M4: 44 passed in 41.79s |
| C | ✅ | 9-14. Over stdio: catalogue, 3 workflows, reports + number guard, restart | tests/final/test_final_stdio.py: 1 passed in 8.50s |
| D | ✅ | 15. Traversal, symlink escape, oversize and vendor files refused | M1-AC1 and M1-AC7 inside item 8; tests/unit/test_security.py |
| D | ✅ | 16. No network outside fetch_public_dataset | workflows with sockets blocked, 0 attempts: 1 passed in 2.82s |
| D | ✅ | 17. gitleaks clean over full history | 12:35AM INF no leaks found |
| D | ✅ | 18. No copyleft core dependency; no third-party spectra bundled; data.md complete | 38 core packages checked (docs/progress/dependency_licences.txt), copyleft: none (GCC runtime exception: ['scipy']); bundled library synthetic CC0: True; datasets listed in data.md: True |
| D | ⏳ | 19. No code or data from past employers (human attests) | add the attestation line to docs/progress/SIGNOFF.md |
| E | ⏳ | 20. uvx from TestPyPI on 3 OSes; version 0.1.0; CHANGELOG | version 0.1.0.dev0; release run: pending; CHANGELOG 0.1.0 entry: True |
| E | ⏳ | 21. README complete; eval/results.md (incl. LLM); demo GIF | README ✅ (M5-AC5); deterministic evals ✅; LLM table pending; demo.gif pending |
| F | ⏳ | 22. Yuri installs via README and runs the 3 workflows | add 'Workflows run by Yuri: ...' to docs/progress/SIGNOFF.md |
| F | ⏳ | 23. Yuri spot-checks 3 report numbers in the ledger | add 'Ledger spot-check: ...' to docs/progress/SIGNOFF.md |
| F | ⏳ | 24. Sign-off line recorded | add 'Signed off by: ...' to docs/progress/SIGNOFF.md |

⏳ = waiting for a human or an external system (CI, TestPyPI, API key, sign-off).
Human steps are listed in docs/progress/STATUS.md; sign-off lines go in docs/progress/SIGNOFF.md.
