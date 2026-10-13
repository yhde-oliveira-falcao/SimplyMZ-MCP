from __future__ import annotations

import time
from pathlib import Path

import pytest

from simplymz_mcp.core.errors import ErrorCode, SimplyMZError
from simplymz_mcp.jobs.executor import JobContext, Jobs
from simplymz_mcp.state.store import Store


@pytest.fixture
def jobs(tmp_path: Path) -> Jobs:
    j = Jobs(Store(tmp_path))
    yield j
    j.shutdown()


def test_submit_returns_immediately_and_completes(jobs: Jobs) -> None:
    def work(ctx: JobContext) -> dict:
        for i in range(5):
            ctx.progress(i / 5, f"step {i}")
            time.sleep(0.05)
        return {"answer": 42}

    t0 = time.monotonic()
    jid = jobs.submit("demo", {"x": 1}, work)
    assert time.monotonic() - t0 < 0.2
    assert jid.startswith("job:")
    assert jobs.get(jid)["state"] in ("queued", "running")
    rec = jobs.wait(jid)
    assert rec["state"] == "done" and rec["progress"] == 1.0 and rec["result"] == {"answer": 42}
    assert rec["params"] == {"x": 1} and rec["started_utc"] and rec["finished_utc"]


def test_cancellation_is_cooperative(jobs: Jobs) -> None:
    def work(ctx: JobContext) -> dict:
        while True:
            ctx.check()
            time.sleep(0.01)

    jid = jobs.submit("loop", {}, work)
    time.sleep(0.05)
    assert jobs.cancel(jid)
    rec = jobs.wait(jid)
    assert rec["state"] == "cancelled" and "cancelled" in rec["message"]
    assert not jobs.cancel(jid)  # already terminal


def test_timeout_marks_failed(jobs: Jobs) -> None:
    def work(ctx: JobContext) -> dict:
        while True:
            ctx.check()
            time.sleep(0.01)

    rec = jobs.wait(jobs.submit("slow", {}, work, timeout_s=0.1))
    assert rec["state"] == "failed" and rec["message"] == "timed out"


def test_errors_recorded_instructively(jobs: Jobs) -> None:
    def known(ctx: JobContext) -> dict:
        raise SimplyMZError(ErrorCode.FILE_NOT_FOUND, "gone.", "check path")

    def bug(ctx: JobContext) -> dict:
        raise RuntimeError("boom")

    a = jobs.wait(jobs.submit("k", {}, known))
    b = jobs.wait(jobs.submit("b", {}, bug))
    assert (
        a["state"] == "failed" and "FILE_NOT_FOUND" in a["message"] and "check path" in a["message"]
    )
    assert b["state"] == "failed" and "boom" not in b["message"]


def test_results_survive_restart_and_running_jobs_fail(tmp_path: Path) -> None:
    j1 = Jobs(Store(tmp_path))
    done = j1.submit("d", {}, lambda ctx: {"v": 1})
    j1.wait(done)
    j1.store.db.execute(
        "INSERT INTO jobs (id, kind, state, params, created_utc, timeout_s) "
        "VALUES ('job:01ARZ3NDEKTSV4RRFFQ69G5FAV', 'x', 'running', '{}', 'now', 10)"
    )
    j1.shutdown()
    j2 = Jobs(Store(tmp_path))  # restart
    assert j2.get(done)["result"] == {"v": 1}
    stale = j2.get("job:01ARZ3NDEKTSV4RRFFQ69G5FAV")
    assert stale["state"] == "failed" and "submit it again" in stale["message"]
    with pytest.raises(SimplyMZError) as ei:
        j2.get("job:01BX5ZZKBKACTAV9WEVGEMMVRZ")
    assert ei.value.code == ErrorCode.UNKNOWN_HANDLE
    j2.shutdown()
