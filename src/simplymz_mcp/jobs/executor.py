"""Job store (SQLite) + thread-pool executor with progress, timeout and cancellation.

Work functions receive a :class:`JobContext` and must call ``ctx.check()`` regularly; it
raises :class:`JobCancelled` when the job was cancelled or its timeout passed (Python
threads cannot be killed, so cancellation is cooperative). Results are stored as JSON and
survive restarts; jobs still queued or running when the server stops are marked failed.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from simplymz_mcp.core.errors import ErrorCode, SimplyMZError
from simplymz_mcp.core.handles import new_handle
from simplymz_mcp.state.store import Store, utcnow

log = logging.getLogger("simplymz_mcp")

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    state TEXT NOT NULL,
    progress REAL NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    params TEXT NOT NULL,
    created_utc TEXT NOT NULL,
    started_utc TEXT,
    finished_utc TEXT,
    timeout_s REAL NOT NULL,
    result TEXT
);
"""
TERMINAL = ("done", "failed", "cancelled")


class JobCancelled(Exception):
    pass


class JobContext:
    def __init__(self, jobs: Jobs, job_id: str, timeout_s: float) -> None:
        self._jobs = jobs
        self.job_id = job_id
        self.cancel_event = threading.Event()
        self.deadline = time.monotonic() + timeout_s

    def check(self) -> None:
        if self.cancel_event.is_set():
            raise JobCancelled("cancelled")
        if time.monotonic() > self.deadline:
            raise JobCancelled("timeout")

    def progress(self, fraction: float, message: str = "") -> None:
        self.check()
        self._jobs._update(self.job_id, progress=max(0.0, min(1.0, fraction)), message=message)


WorkFn = Callable[[JobContext], dict[str, Any]]


class Jobs:
    def __init__(self, store: Store, max_workers: int = 2) -> None:
        self.store = store
        self.pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="job")
        self._contexts: dict[str, JobContext] = {}
        self._lock = threading.Lock()
        with store.lock:
            store.db.executescript(SCHEMA)
            store.db.execute(
                "UPDATE jobs SET state = 'failed', finished_utc = ?, message = "
                "'server stopped before the job finished; submit it again' "
                "WHERE state IN ('queued', 'running')",
                (utcnow(),),
            )

    def _update(self, job_id: str, **fields: Any) -> None:
        # column names come from internal keyword arguments only, never from clients
        cols = ", ".join(f"{k} = ?" for k in fields)
        with self.store.lock:
            self.store.db.execute(
                f"UPDATE jobs SET {cols} WHERE id = ?",
                (*fields.values(), job_id),
            )

    def submit(
        self, kind: str, params: dict[str, Any], work: WorkFn, timeout_s: float = 3600
    ) -> str:
        job_id = new_handle("job")
        with self.store.lock:
            self.store.db.execute(
                "INSERT INTO jobs (id, kind, state, params, created_utc, timeout_s) "
                "VALUES (?, ?, 'queued', ?, ?, ?)",
                (job_id, kind, json.dumps(params, default=str), utcnow(), timeout_s),
            )
        ctx = JobContext(self, job_id, timeout_s)
        with self._lock:
            self._contexts[job_id] = ctx
        self.pool.submit(self._run, ctx, work)
        return job_id

    def _run(self, ctx: JobContext, work: WorkFn) -> None:
        job_id = ctx.job_id
        try:
            ctx.check()
            self._update(job_id, state="running", started_utc=utcnow())
            result = work(ctx)
            ctx.check()
            self._update(
                job_id,
                state="done",
                progress=1.0,
                finished_utc=utcnow(),
                result=json.dumps(result, default=str),
            )
        except JobCancelled as exc:
            reason = str(exc)
            self._update(
                job_id,
                state="cancelled" if reason == "cancelled" else "failed",
                finished_utc=utcnow(),
                message="cancelled by request" if reason == "cancelled" else "timed out",
            )
        except SimplyMZError as exc:
            self._update(
                job_id,
                state="failed",
                finished_utc=utcnow(),
                message=f"{exc.code}: {exc.message} Hint: {exc.hint}",
            )
        except Exception:
            log.exception("job %s failed", job_id)
            self._update(
                job_id,
                state="failed",
                finished_utc=utcnow(),
                message="internal error (see server log)",
            )
        finally:
            with self._lock:
                self._contexts.pop(job_id, None)

    def get(self, job_id: str) -> dict[str, Any]:
        with self.store.lock:
            cur = self.store.db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
            row = cur.fetchone()
            cols = [d[0] for d in cur.description]
        if row is None:
            raise SimplyMZError(
                ErrorCode.UNKNOWN_HANDLE,
                f"No job {job_id}.",
                "Use the job: handle returned by the tool that started it.",
            )
        rec = dict(zip(cols, row, strict=True))
        rec["params"] = json.loads(rec["params"])
        rec["result"] = json.loads(rec["result"]) if rec["result"] else None
        return rec

    def cancel(self, job_id: str) -> bool:
        rec = self.get(job_id)
        if rec["state"] in TERMINAL:
            return False
        with self._lock:
            ctx = self._contexts.get(job_id)
        if ctx is not None:
            ctx.cancel_event.set()
        return True

    def wait(self, job_id: str, timeout_s: float = 60) -> dict[str, Any]:
        """Block until a job is terminal (used by tests and small synchronous paths)."""
        end = time.monotonic() + timeout_s
        while time.monotonic() < end:
            rec = self.get(job_id)
            if rec["state"] in TERMINAL:
                return rec
            time.sleep(0.02)
        raise TimeoutError(job_id)

    def shutdown(self) -> None:
        with self._lock:
            for ctx in self._contexts.values():
                ctx.cancel_event.set()
        self.pool.shutdown(wait=True, cancel_futures=True)
