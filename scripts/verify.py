"""Milestone gate (IMPLEMENTATION_PLAN.md §2.4).

    uv run python scripts/verify.py M0              # strict local gate
    uv run python scripts/verify.py --current --ci --allow-pending   # CI

Steps run in order and stop at the first failure. Results are written to
docs/progress/gates/<M>.json. Exit code 0 only when every step passes.

``--allow-pending`` turns *human/external* checks (ADR approval, CI evidence) into
PENDING instead of FAIL; the gate JSON then says "local_pass_pending_human" and the
milestone must NOT be tagged.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
PROGRESS = REPO / "docs" / "progress"
GATES = PROGRESS / "gates"
MILESTONES = ["M0", "M1", "M2", "M3", "M4", "M5"]
CORE_PACKAGES = ["core", "io", "state", "ledger", "analytics", "annotation", "report"]
COVERAGE_MIN = 85.0
STEP_NAMES = [
    "1_lint_format",
    "2_types",
    "3_tests_coverage",
    "4_contract",
    "5_acceptance_current",
    "6_acceptance_regression",
    "7_progress_records",
    "8_test_count",
    "9_gitleaks",
]


class StepFailed(Exception):
    pass


STEP_TIMEOUT_S = int(os.environ.get("SIMPLYMZ_GATE_STEP_TIMEOUT", "1500"))
HEARTBEAT_S = 20
_LOG: Path | None = None
_CURRENT = {"step": "setup"}


def log(msg: str) -> None:
    """Timestamped progress line to stdout (flushed) and to the run log."""
    line = f"{datetime.now(UTC).strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    if _LOG is not None:
        with open(_LOG, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def sh(cmd: list[str], timeout: int = STEP_TIMEOUT_S) -> subprocess.CompletedProcess[str]:
    """Run a command, streaming its output to a per-step log, with heartbeats.

    Every HEARTBEAT_S seconds a heartbeat reports elapsed time and the last output line,
    so a slow or stuck step is visible while it runs. On timeout the whole process group is
    killed and TimeoutExpired is raised with the output so far.
    """
    GATES.mkdir(parents=True, exist_ok=True)
    out_path = GATES / f".step_{_CURRENT['step']}.log"
    start = time.monotonic()
    with open(out_path, "w", encoding="utf-8") as out:
        proc = subprocess.Popen(
            cmd, cwd=REPO, stdout=out, stderr=subprocess.STDOUT, text=True, start_new_session=True
        )
        while True:
            try:
                proc.wait(timeout=HEARTBEAT_S)
                break
            except subprocess.TimeoutExpired:
                elapsed = int(time.monotonic() - start)
                last = tail(out_path.read_text(encoding="utf-8", errors="replace"), 1)[:120]
                log(f"  ... {_CURRENT['step']} still running ({elapsed}s): {last}")
                if elapsed > timeout:
                    kill_tree(proc)
                    proc.wait()
                    text = out_path.read_text(encoding="utf-8", errors="replace")
                    raise subprocess.TimeoutExpired(cmd, timeout, output=text) from None
    text = out_path.read_text(encoding="utf-8", errors="replace")
    return subprocess.CompletedProcess(cmd, proc.returncode, text, "")


def kill_tree(proc: subprocess.Popen[str]) -> None:
    """Kill a process and its children (process group on POSIX, taskkill /T on Windows)."""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    else:
        os.killpg(proc.pid, signal.SIGKILL)


def tail(text: str, n: int = 3) -> str:
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    return " | ".join(lines[-n:])


def run_ok(cmd: list[str], what: str) -> str:
    p = sh(cmd)
    if p.returncode != 0:
        raise StepFailed(f"{what} failed: {tail(p.stdout + p.stderr, 8)}")
    return tail(p.stdout + p.stderr, 1) or "ok"


# ---------------- steps ----------------


def step_lint(_: str, __: argparse.Namespace) -> dict[str, Any]:
    a = run_ok(["ruff", "check", "."], "ruff check")
    b = run_ok(["ruff", "format", "--check", "."], "ruff format")
    return {"summary": f"{a}; {b}"}


def step_types(_: str, __: argparse.Namespace) -> dict[str, Any]:
    return {"summary": run_ok(["mypy"], "mypy")}


def step_tests(_: str, __: argparse.Namespace) -> dict[str, Any]:
    junit = GATES / ".junit.xml"
    covjson = GATES / ".coverage.json"
    p = sh(
        [
            sys.executable,
            "-m",
            "pytest",
            "-m",
            "not network",
            "--durations=10",
            "-q",
            "--cov=simplymz_mcp",
            f"--cov-report=json:{covjson}",
            f"--junitxml={junit}",
        ]
    )
    counts = junit_counts(junit)
    if p.returncode != 0:
        raise StepFailed(f"pytest failed: {tail(p.stdout, 6)}")
    cov = json.loads(covjson.read_text())
    covered = statements = 0
    for fname, data in cov["files"].items():
        parts = Path(fname).parts
        if "simplymz_mcp" in parts and any(pkg in parts for pkg in CORE_PACKAGES):
            covered += data["summary"]["covered_lines"]
            statements += data["summary"]["num_statements"]
    core_cov = 100.0 * covered / statements if statements else 0.0
    junit.unlink(missing_ok=True)
    covjson.unlink(missing_ok=True)
    if core_cov < COVERAGE_MIN:
        raise StepFailed(f"core coverage {core_cov:.1f}% < {COVERAGE_MIN}%")
    return {
        "summary": f"{counts['passed']} passed / {counts['failed']} failed / "
        f"{counts['skipped']} skipped; core coverage {core_cov:.1f}%",
        "tests": counts,
        "core_coverage_pct": round(core_cov, 1),
    }


def junit_counts(path: Path) -> dict[str, int]:
    if not path.exists():
        return {"total": 0, "passed": 0, "failed": 0, "skipped": 0}
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root)
    total = sum(int(s.get("tests", 0)) for s in suites)
    failed = sum(int(s.get("failures", 0)) + int(s.get("errors", 0)) for s in suites)
    skipped = sum(int(s.get("skipped", 0)) for s in suites)
    return {
        "total": total,
        "passed": total - failed - skipped,
        "failed": failed,
        "skipped": skipped,
    }


def step_contract(_: str, __: argparse.Namespace) -> dict[str, Any]:
    files = list((REPO / "tests" / "contract").glob("test_*.py"))
    if not files:
        raise StepFailed("no contract tests found in tests/contract/")
    return {
        "summary": run_ok(
            [sys.executable, "-m", "pytest", "-q", "tests/contract"], "contract tests"
        )
    }


def acceptance_file(m: str) -> Path:
    return REPO / "tests" / "acceptance" / f"test_{m.lower()}.py"


def step_acceptance(m: str, __: argparse.Namespace) -> dict[str, Any]:
    f = acceptance_file(m)
    if not f.exists():
        raise StepFailed(f"missing {f.relative_to(REPO)}")
    expected = acceptance_ids(m)
    names = set(re.findall(r"def (test_" + m + r"_AC\d+\w*)", f.read_text()))
    missing = [
        ac
        for ac in expected
        if not any(n.startswith(f"test_{ac.replace('-', '_')}_") for n in names)
    ]
    if missing:
        raise StepFailed(f"no acceptance test for {missing}")
    out = run_ok([sys.executable, "-m", "pytest", "-q", str(f)], f"{m} acceptance")
    return {"summary": out, "criteria": expected}


def step_regression(m: str, __: argparse.Namespace) -> dict[str, Any]:
    earlier = MILESTONES[: MILESTONES.index(m)] if m in MILESTONES else MILESTONES
    files = [str(acceptance_file(e)) for e in earlier if acceptance_file(e).exists()]
    if not files:
        return {"summary": "no earlier milestones"}
    return {
        "summary": run_ok([sys.executable, "-m", "pytest", "-q", *files], "regression acceptance")
    }


def acceptance_ids(m: str) -> list[str]:
    """AC ids for milestone m, read from the plan so the gate and plan cannot drift."""
    plan = (REPO / "IMPLEMENTATION_PLAN.md").read_text(encoding="utf-8")
    return sorted(set(re.findall(rf"\*\*({m}-AC\d+)\*\*", plan)), key=lambda s: int(s[5:]))


def step_progress(m: str, args: argparse.Namespace) -> dict[str, Any]:
    log = PROGRESS / f"{m}.md"
    if not log.exists():
        raise StepFailed(f"missing {log.relative_to(REPO)}")
    # Task entries are "### M<n>.T<k> ..."; other headings are notes, not tasks.
    entries = re.split(r"^### (?=M\d+\.T\d+)", log.read_text(encoding="utf-8"), flags=re.M)[1:]
    if not entries:
        raise StepFailed(f"{log.name} has no task entries")
    bad = []
    deferred = []
    for e in entries:
        task = e.split()[0]
        status = re.search(r"^Status:\s*(\w+)", e, re.M)
        if status and status.group(1) == "DEFERRED":
            # Allowed only with an explicit, recorded decision; reported as a waiver and
            # never tagged. Final Verification requires none to remain.
            if re.search(r"^Deferred by:\s*\S", e, re.M):
                deferred.append(task)
            else:
                bad.append(f"{task}(DEFERRED without 'Deferred by:')")
            continue
        commit = re.search(r"^Commit:\s*([0-9a-f]{7,40})\b", e, re.M)
        if not status or status.group(1) != "VERIFIED" or not commit:
            bad.append(task)
        elif sh(["git", "cat-file", "-e", f"{commit.group(1)}^{{commit}}"]).returncode != 0:
            bad.append(f"{task}(unknown commit)")
    if bad:
        raise StepFailed(f"tasks not VERIFIED with a valid commit: {bad}")
    summary = PROGRESS / f"{m}_SUMMARY.md"
    if not summary.exists():
        raise StepFailed(f"{summary.name} missing: write it from the gate JSON, then re-run")
    missing_ac = [ac for ac in acceptance_ids(m) if ac not in summary.read_text()]
    if missing_ac:
        raise StepFailed(f"{summary.name} does not cover {missing_ac}")
    human = human_checks(m)
    pending = [h for h, v in human.items() if v == "pending"]
    waived = [h for h, v in human.items() if v == "waived"]
    waived += [f"{t} deferred" for t in deferred]
    result: dict[str, Any] = {
        "summary": f"{len(entries) - len(deferred)} tasks VERIFIED, {len(deferred)} deferred; "
        "summary present",
        "human_checks": human,
    }
    if waived:
        result["waived"] = waived
    if pending:
        if not args.allow_pending:
            raise StepFailed(f"human/external checks pending: {pending}")
        result["pending_human"] = pending
    return result


def human_checks(m: str) -> dict[str, str]:
    """Checks only a human (or a real CI run) can satisfy: 'ok' | 'pending' | 'waived'.

    A waiver is a line ``CI waiver M<n>: <reason>`` in STATUS.md written on the human's
    explicit instruction. Waived items are reported, and the milestone is not tagged.
    """
    checks: dict[str, str] = {}
    status_text = (PROGRESS / "STATUS.md").read_text(encoding="utf-8")
    ci = re.search(
        rf"^CI evidence {m}:\s*(https://github\.com/\S+/actions/runs/\d+)", status_text, re.M
    )
    waiver = re.search(rf"^CI waiver {m}:\s*\S", status_text, re.M)
    checks[f"CI run URL recorded for {m}"] = "ok" if ci else ("waived" if waiver else "pending")
    if m == "M5":
        results = (
            (REPO / "eval" / "results.md").read_text(encoding="utf-8")
            if (REPO / "eval" / "results.md").exists()
            else ""
        )
        checks["LLM evaluation table in eval/results.md (needs ANTHROPIC_API_KEY)"] = (
            "ok" if "| Claude alone |" in results else "pending"
        )
        release = re.search(
            r"^Release evidence M5:\s*(https://github\.com/\S+/actions/runs/\d+)", status_text, re.M
        )
        checks["TestPyPI install on 3 OSes (release workflow run URL in STATUS.md)"] = (
            "ok" if release else "pending"
        )
    for adr in sorted((REPO / "docs" / "adr").glob("0*.md")):
        # Every ADR must be decided by the human; a Proposed ADR blocks any milestone gate.
        status = re.search(r"^Status:\s*(\w+)", adr.read_text(), re.M)
        if m == "M0" or (status and status.group(1) == "Proposed"):
            accepted = bool(status) and status.group(1) == "Accepted"
            checks[f"{adr.stem} Accepted by human"] = "ok" if accepted else "pending"
    return checks


def step_test_count(m: str, args: argparse.Namespace) -> dict[str, Any]:
    current = args.results.get("3_tests_coverage", {}).get("tests", {}).get("total", 0)
    prev_total, prev_name = 0, None
    idx = MILESTONES.index(m) if m in MILESTONES else len(MILESTONES)
    for e in reversed(MILESTONES[:idx]):
        f = GATES / f"{e}.json"
        if f.exists():
            prev_total = json.loads(f.read_text()).get("test_count", 0)
            prev_name = e
            break
    if current < prev_total:
        raise StepFailed(f"test count dropped: {current} < {prev_total} ({prev_name})")
    return {"summary": f"{current} tests (previous gate {prev_name or 'none'}: {prev_total})"}


def step_gitleaks(_: str, __: argparse.Namespace) -> dict[str, Any]:
    if not shutil.which("gitleaks"):
        raise StepFailed("gitleaks not installed (https://github.com/gitleaks/gitleaks)")
    p = sh(["gitleaks", "git", ".", "--no-banner", "--no-color", "--redact"])
    if p.returncode != 0:
        raise StepFailed(f"gitleaks found leaks: {tail(p.stdout + p.stderr, 5)}")
    return {"summary": tail(p.stdout + p.stderr, 1)}


STEPS = [
    step_lint,
    step_types,
    step_tests,
    step_contract,
    step_acceptance,
    step_regression,
    step_progress,
    step_test_count,
    step_gitleaks,
]


def write_json(m: str, status: str, args: argparse.Namespace) -> None:
    git = ["git", "-C", str(REPO)]
    commit = subprocess.run(
        [*git, "rev-parse", "--short", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    dirty = args.dirty_at_start
    out = {
        "milestone": m,
        "status": status,
        "timestamp_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "commit": commit,
        "worktree_dirty": dirty,
        "ci": args.ci,
        "test_count": args.results.get("3_tests_coverage", {}).get("tests", {}).get("total", 0),
        "steps": args.results,
    }
    (GATES / f"{m}.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")


def current_milestone() -> str:
    text = (PROGRESS / "STATUS.md").read_text(encoding="utf-8")
    m = re.search(r"^Current milestone:\s*(M\d)", text, re.M)
    if not m:
        raise SystemExit("STATUS.md has no 'Current milestone:' line")
    return m.group(1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("milestone", nargs="?", help="M0..M5")
    ap.add_argument("--current", action="store_true", help="read milestone from STATUS.md")
    ap.add_argument("--ci", action="store_true", help="running in CI")
    ap.add_argument(
        "--allow-pending",
        action="store_true",
        help="report human/external checks as PENDING instead of failing",
    )
    args = ap.parse_args()
    m = current_milestone() if args.current else (args.milestone or "").upper()
    if m == "FINAL":
        import final_verify

        return final_verify.main()
    if m not in MILESTONES:
        ap.error("give a milestone M0..M5, FINAL, or --current")
    GATES.mkdir(parents=True, exist_ok=True)
    args.results = {}
    status = "pass"
    global _LOG
    # Cleanliness of what is being gated, measured before the gate writes its own files.
    porcelain = subprocess.run(
        ["git", "-C", str(REPO), "status", "--porcelain"], capture_output=True, text=True
    ).stdout.splitlines()
    args.dirty_at_start = any("docs/progress/gates/" not in ln for ln in porcelain)
    _LOG = GATES / f".{m}.run.log"
    _LOG.write_text("", encoding="utf-8")
    log(f"gate {m} started (step timeout {STEP_TIMEOUT_S}s, log {_LOG.relative_to(REPO)})")
    for name, step in zip(STEP_NAMES, STEPS, strict=True):
        _CURRENT["step"] = name
        log(f"-> {name}")
        t0 = time.monotonic()
        try:
            res = step(m, args)
            res["status"] = "pass"
        except StepFailed as exc:
            res = {"status": "fail", "summary": str(exc)}
            status = "fail"
        except subprocess.TimeoutExpired as exc:
            res = {
                "status": "fail",
                "summary": f"timeout after {exc.timeout}s: {tail(str(exc.output or ''), 3)}",
            }
            status = "fail"
        except Exception as exc:  # a crash in the gate itself must still leave a record
            res = {"status": "fail", "summary": f"gate error: {type(exc).__name__}: {exc}"}
            status = "fail"
        res["seconds"] = round(time.monotonic() - t0, 1)
        args.results[name] = res
        mark = "PASS" if res["status"] == "pass" else "FAIL"
        log(f"[{mark}] {name} ({res['seconds']}s): {res['summary']}")
        write_json(m, "in_progress" if status == "pass" else status, args)
        if status == "fail":
            break
    step7 = args.results.get("7_progress_records", {})
    pending, waived = step7.get("pending_human", []), step7.get("waived", [])
    if status == "pass" and pending:
        status = "local_pass_pending_human"
    elif status == "pass" and waived:
        status = "pass_with_waivers"
    for p in pending:
        log(f"[PENDING] {p}")
    for w in waived:
        log(f"[WAIVED] {w} (do not tag until resolved)")
    write_json(m, status, args)
    log(f"gate {m}: {status.upper()} (written docs/progress/gates/{m}.json)")
    return (
        0
        if status in ("pass", "local_pass_pending_human")
        and (status == "pass" or args.allow_pending)
        else 1
    )


if __name__ == "__main__":
    sys.exit(main())
