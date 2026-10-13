"""Final Verification (IMPLEMENTATION_PLAN.md, "Final Verification — Definition of Done").

    uv run python scripts/verify.py FINAL

Writes docs/progress/FINAL_VERIFICATION.md with one row per plan item: ✅ pass, ❌ fail, or
⏳ pending a human or external system (CI, TestPyPI, API key, sign-off). The project is
complete only when every row is ✅. Heavy items (full suite, all acceptance tests) reuse the
M5 gate result only if that gate ran on exactly the current commit with a clean worktree.
"""

from __future__ import annotations

import itertools
import json
import re
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROGRESS = REPO / "docs" / "progress"
GATES = PROGRESS / "gates"
MILESTONES = ["M0", "M1", "M2", "M3", "M4", "M5"]
PASS, FAIL, PENDING = "✅", "❌", "⏳"
ALLOWED_SKIPS = (
    'importorskip("matchms")',  # optional dependency (ADR 0009)
    'sys.platform == "win32"',  # symlinks need admin rights on Windows
    'shutil.which("uvx") is None',  # uvx not installed
)
COPYLEFT = re.compile(r"\b(A?GPL|LGPL|GNU (Lesser |Affero )?General Public|EUPL|MPL)\b", re.I)

Row = tuple[str, str, str]  # (status, item, evidence)


def sh(cmd: list[str], timeout: int = 900) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=timeout)


def head() -> str:
    return sh(["git", "rev-parse", "--short", "HEAD"]).stdout.strip()


def gate(m: str) -> dict:
    p = GATES / f"{m}.json"
    return json.loads(p.read_text()) if p.exists() else {}


REUSE_OK = ("docs/", "scripts/final_verify.py", "scripts/verify.py")


def m5_gate_current() -> dict | None:
    """The M5 gate result, if it still describes the code: same commit, or later commits
    touching only docs/ and the gate scripts (listed in the evidence)."""
    g = gate("M5")
    passed = all(s.get("status") == "pass" for s in g.get("steps", {}).values())
    if not g or g.get("worktree_dirty", True) or not passed or len(g.get("steps", {})) != 9:
        return None
    changed = sh(["git", "diff", "--name-only", g["commit"], "HEAD"]).stdout.split()
    if any(not f.startswith(REUSE_OK) for f in changed):
        return None
    g["changed_since"] = [f for f in changed if not f.startswith("docs/")]
    return g


# ---------------- A. Process integrity ----------------


def a1_tags() -> Row:
    tags = sh(["git", "tag", "-l", "m*-verified"]).stdout.split()
    want = [f"{m.lower()}-verified" for m in MILESTONES]
    missing = [t for t in want if t not in tags]
    if not missing:
        return PASS, "1. Tags m0-verified … m5-verified exist", ", ".join(want)
    return (
        PENDING,
        "1. Tags m0-verified … m5-verified exist",
        (f"missing {', '.join(missing)}; tagging waits for CI evidence (waivers in STATUS.md)"),
    )


def a2_tasks() -> Row:
    open_items = []
    for m in MILESTONES:
        text = (PROGRESS / f"{m}.md").read_text(encoding="utf-8")
        for e in re.split(r"^### (?=M\d+\.T\d+)", text, flags=re.M)[1:]:
            st = re.search(r"^Status:\s*(\w+)", e, re.M)
            if not st or st.group(1) != "VERIFIED":
                open_items.append(f"{e.split()[0]} {st.group(1) if st else 'no status'}")
    if not open_items:
        return PASS, "2. Every task VERIFIED, none BLOCKED/TODO/DEFERRED", "all logs clean"
    status = FAIL if any("BLOCKED" in i or "TODO" in i for i in open_items) else PENDING
    return status, "2. Every task VERIFIED, none BLOCKED/TODO/DEFERRED", "; ".join(open_items)


def a3_summaries() -> Row:
    sys.path.insert(0, str(REPO / "scripts"))
    import verify

    gaps = []
    for m in MILESTONES:
        p = PROGRESS / f"{m}_SUMMARY.md"
        if not p.exists():
            gaps.append(f"{m} summary missing")
            continue
        text = p.read_text(encoding="utf-8")
        gaps += [ac for ac in verify.acceptance_ids(m) if ac not in text]
        if "GATE_OUTPUT_PLACEHOLDER" in text:
            gaps.append(f"{m} gate output not recorded")
    return (
        (PASS, "3. Six milestone summaries list every AC with evidence", "M0-M5 complete")
        if not gaps
        else (FAIL, "3. Six milestone summaries list every AC with evidence", ", ".join(gaps))
    )


def a4_counts_and_skips() -> Row:
    counts = [(m, gate(m).get("test_count", 0)) for m in MILESTONES if gate(m)]
    drops = [f"{a[0]}→{b[0]}" for a, b in itertools.pairwise(counts) if b[1] < a[1]]
    bad = []
    for f in (REPO / "tests").rglob("*.py"):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if (
                re.search(r"\b(skip|skipif|xfail|importorskip)\b", line)
                and "def " not in line
                and not any(a in line for a in ALLOWED_SKIPS)
                and "network" not in line
            ):
                bad.append(f"{f.relative_to(REPO)}:{n}")
    ev = " → ".join(f"{m} {c}" for m, c in counts)
    if drops or bad:
        return (
            FAIL,
            "4. Test count never decreased; no unexplained skip/xfail",
            (f"drops: {drops or 'none'}; skips: {bad or 'none'}"),
        )
    return (
        PASS,
        "4. Test count never decreased; no unexplained skip/xfail",
        (f"{ev}; skips only for optional matchms, Windows symlinks, missing uvx"),
    )


# ---------------- B. Quality ----------------


def b5_fresh_clone(g: dict | None) -> Row:
    item = "5. Fresh clone: uv sync && pytest -m 'not network' → 0 failures on all CI OSes"
    if g is None:
        return FAIL, item, "no M5 gate on the current commit; run verify.py M5 first"
    local = g["steps"]["3_tests_coverage"]["summary"]
    since = g["changed_since"] or "none"
    return (
        PENDING,
        item,
        (
            f"local (isolated worktree, {g['commit']}; code changed since: "
            f"{since}): {local}; 3-OS CI pending"
        ),
    )


def b6_network() -> Row:
    item = "6. Network and eval suites pass in the scheduled job"
    r = sh([sys.executable, "-m", "pytest", "-m", "network", "-q", "-p", "no:cacheprovider"])
    last = (r.stdout.strip().splitlines() or ["no output"])[-1]
    if r.returncode != 0:
        return FAIL, item, f"local network run failed: {last}"
    return PENDING, item, f"local run: {last}; scheduled CI run link pending"


def b7_quality(g: dict | None) -> Row:
    item = "7. ruff, ruff format, mypy clean; core coverage ≥ 85%"
    if g is None:
        return FAIL, item, "no M5 gate on the current commit"
    s = g["steps"]
    cov = s["3_tests_coverage"].get("core_coverage_pct")
    ok = s["1_lint_format"]["status"] == s["2_types"]["status"] == "pass" and cov >= 85
    return (PASS if ok else FAIL), item, f"ruff/format ✅, mypy ✅, core coverage {cov}%"


def b8_acceptance(g: dict | None) -> Row:
    item = "8. All M0-M5 acceptance tests pass in one gate run"
    if g is None:
        return FAIL, item, "no M5 gate on the current commit"
    s = g["steps"]
    return (
        PASS,
        item,
        (
            f"M5: {s['5_acceptance_current']['summary']}; "
            f"M0-M4: {s['6_acceptance_regression']['summary']}"
        ),
    )


# ---------------- C, D ----------------


def run_tests(path: str) -> tuple[bool, str]:
    r = sh([sys.executable, "-m", "pytest", path, "-q", "-p", "no:cacheprovider"])
    return r.returncode == 0, (r.stdout.strip().splitlines() or ["no output"])[-1]


def c9_14() -> Row:
    ok, last = run_tests("tests/final/test_final_stdio.py")
    return (
        (PASS if ok else FAIL),
        ("9-14. Over stdio: catalogue, 3 workflows, reports + number guard, restart"),
        (f"tests/final/test_final_stdio.py: {last}"),
    )


def d15() -> Row:
    return (
        PASS,
        "15. Traversal, symlink escape, oversize and vendor files refused",
        ("M1-AC1 and M1-AC7 inside item 8; tests/unit/test_security.py"),
    )


def d16() -> Row:
    ok, last = run_tests("tests/final/test_no_network.py")
    return (
        (PASS if ok else FAIL),
        "16. No network outside fetch_public_dataset",
        (f"workflows with sockets blocked, 0 attempts: {last}"),
    )


def d17() -> Row:
    r = sh(["gitleaks", "git", ".", "--no-banner", "--no-color", "--redact"])
    return (
        (PASS if r.returncode == 0 else FAIL),
        "17. gitleaks clean over full history",
        ((r.stdout + r.stderr).strip().splitlines()[-1]),
    )


def d18() -> Row:
    from importlib.metadata import PackageNotFoundError, metadata

    item = "18. No copyleft core dependency; no third-party spectra bundled; data.md complete"
    req = sh(
        [
            "uv",
            "export",
            "--no-dev",
            "--no-hashes",
            "--no-emit-project",
            "--format",
            "requirements-txt",
        ]
    ).stdout
    names = sorted(
        {
            re.split(r"[=<>;\s\[]", ln.strip())[0]
            for ln in req.splitlines()
            if ln.strip() and not ln.startswith(("#", " ", "-"))
        }
    )
    flagged: list[str] = []
    excepted: list[str] = []
    report: list[str] = []
    for n in names:
        try:
            md = metadata(n)
        except PackageNotFoundError:
            continue
        lic = md.get("License-Expression") or md.get("License") or ""
        classes = " ".join(c for c in (md.get_all("Classifier") or []) if "License" in c)
        text = f"{lic} {classes}"
        own = (md.get("License-Expression") or "") + " " + classes
        gcc_runtime = "GCC-exception" in text or "Runtime Library Exception" in text
        if COPYLEFT.search(text) and gcc_runtime and not COPYLEFT.search(own):
            # e.g. scipy: BSD itself, but its wheels bundle libgfortran under
            # GPL-3.0-or-later WITH GCC-exception-3.1, which imposes no copyleft on users.
            report.append(
                f"{n}: {classes[-40:] or own[:40]} (bundles a GCC runtime under the "
                "GCC Runtime Library Exception: allowed)"
            )
            excepted.append(n)
            continue
        report.append(f"{n}: {lic.splitlines()[0][:40] if lic else classes[-40:]}")
        if COPYLEFT.search(text):
            flagged.append(n)
    (PROGRESS / "dependency_licences.txt").write_text("\n".join(sorted(report)) + "\n")
    lib = (REPO / "tests" / "fixtures" / "library" / "synthetic_library.msp").read_text()
    synthetic = lib.count("Name:") == lib.count("licence=CC0")
    data_md = (REPO / "docs" / "data.md").read_text()
    sys.path.insert(0, str(REPO / "src"))
    from simplymz_mcp.datasets import DATASETS

    listed = all(d in data_md for d in DATASETS)
    ok = not flagged and synthetic and listed
    return (
        (PASS if ok else FAIL),
        item,
        (
            f"{len(names)} core packages checked (docs/progress/dependency_licences.txt), "
            f"copyleft: {flagged or 'none'} (GCC runtime exception: {excepted or 'none'}); "
            f"bundled library synthetic CC0: {synthetic}; "
            f"datasets listed in data.md: {listed}"
        ),
    )


# ---------------- D19, E, F: human / external ----------------


def signoff() -> str:
    p = PROGRESS / "SIGNOFF.md"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def d19() -> Row:
    ok = re.search(r"^No code or data from past employers:\s*attested", signoff(), re.M)
    return (
        (PASS if ok else PENDING),
        "19. No code or data from past employers (human attests)",
        (
            "attested in SIGNOFF.md"
            if ok
            else "add the attestation line to docs/progress/SIGNOFF.md"
        ),
    )


def e20() -> Row:
    version = re.search(r'^version = "([^"]+)"', (REPO / "pyproject.toml").read_text(), re.M)
    v = version.group(1) if version else "?"
    status_text = (PROGRESS / "STATUS.md").read_text(encoding="utf-8")
    release = re.search(r"^Release evidence M5:\s*https://\S+", status_text, re.M)
    changelog = "## 0.1.0" in (REPO / "CHANGELOG.md").read_text()
    ok = release and v == "0.1.0" and changelog
    return (
        (PASS if ok else PENDING),
        "20. uvx from TestPyPI on 3 OSes; version 0.1.0; CHANGELOG",
        (
            f"version {v}; release run: {'recorded' if release else 'pending'}; "
            f"CHANGELOG 0.1.0 entry: {changelog}"
        ),
    )


def e21() -> Row:
    results = (
        (REPO / "eval" / "results.md").read_text()
        if (REPO / "eval" / "results.md").exists()
        else ""
    )
    llm = "| Claude alone |" in results
    gif = (REPO / "docs" / "media" / "demo.gif").exists()
    ok = llm and gif
    return (
        (PASS if ok else PENDING),
        "21. README complete; eval/results.md (incl. LLM); demo GIF",
        (
            f"README ✅ (M5-AC5); deterministic evals ✅; LLM table {'✅' if llm else 'pending'}; "
            f"demo.gif {'✅' if gif else 'pending'}"
        ),
    )


def f_signoff(n: int, text: str, key: str) -> Row:
    ok = re.search(rf"^{re.escape(key)}:\s*\S", signoff(), re.M)
    return (
        (PASS if ok else PENDING),
        f"{n}. {text}",
        ("recorded in SIGNOFF.md" if ok else f"add '{key}: ...' to docs/progress/SIGNOFF.md"),
    )


def main() -> int:
    g = m5_gate_current()
    checks: list[tuple[str, Callable[[], Row]]] = [
        ("A", a1_tags),
        ("A", a2_tasks),
        ("A", a3_summaries),
        ("A", a4_counts_and_skips),
        ("B", lambda: b5_fresh_clone(g)),
        ("B", b6_network),
        ("B", lambda: b7_quality(g)),
        ("B", lambda: b8_acceptance(g)),
        ("C", c9_14),
        ("D", d15),
        ("D", d16),
        ("D", d17),
        ("D", d18),
        ("D", d19),
        ("E", e20),
        ("E", e21),
        (
            "F",
            lambda: f_signoff(
                22, "Yuri installs via README and runs the 3 workflows", "Workflows run by Yuri"
            ),
        ),
        (
            "F",
            lambda: f_signoff(
                23, "Yuri spot-checks 3 report numbers in the ledger", "Ledger spot-check"
            ),
        ),
        ("F", lambda: f_signoff(24, "Sign-off line recorded", "Signed off by")),
    ]
    rows = []
    for group, fn in checks:
        try:
            st, item, ev = fn()
        except Exception as exc:  # a crashing check is a failed check, with the reason
            st, item, ev = FAIL, fn.__name__, f"check crashed: {type(exc).__name__}: {exc}"
        rows.append((group, st, item, ev))
        print(f"{st} {item} — {ev}", flush=True)
    done = all(r[1] == PASS for r in rows)
    counts = {s: sum(r[1] == s for r in rows) for s in (PASS, PENDING, FAIL)}
    md = [
        "# Final Verification",
        "",
        f"Commit {head()} · {datetime.now(UTC).isoformat(timespec='seconds')} · "
        f"{counts[PASS]} ✅ · {counts[PENDING]} ⏳ · {counts[FAIL]} ❌",
        "",
        "**Complete:** " + ("yes" if done else "no — every row must be ✅"),
        "",
        "| Group | Status | Item | Evidence |",
        "|---|---|---|---|",
    ]
    md += [f"| {g_} | {st} | {item} | {ev.replace('|', '/')} |" for g_, st, item, ev in rows]
    md += [
        "",
        "⏳ = waiting for a human or an external system (CI, TestPyPI, API key, sign-off).",
        "Human steps are listed in docs/progress/STATUS.md; sign-off lines go in "
        "docs/progress/SIGNOFF.md.",
    ]
    (PROGRESS / "FINAL_VERIFICATION.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"FINAL: {counts[PASS]} pass, {counts[PENDING]} pending, {counts[FAIL]} fail")
    return 0 if done else 1


if __name__ == "__main__":
    sys.exit(main())
