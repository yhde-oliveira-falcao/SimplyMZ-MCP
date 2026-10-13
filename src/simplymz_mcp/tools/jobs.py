"""job_status and cancel_job, plus a helper that runs a tool body as a ledgered job."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from simplymz_mcp.core import envelope
from simplymz_mcp.core.registry import Registry, ToolSpec, guard
from simplymz_mcp.jobs.executor import JobContext

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from simplymz_mcp.server import App


def submit_tool_job(
    app: App,
    name: str,
    body: Callable[..., dict[str, Any]],
    kwargs: dict[str, Any],
    budget_tokens: int,
    timeout_s: float = 3600,
) -> dict[str, Any]:
    """Run ``body(ctx, **kwargs)`` in the job pool.

    The body's envelope goes through the same guard as a synchronous tool (budget,
    instructive errors, exactly one ledger entry when it finishes)."""
    sig = inspect.signature(body, eval_str=True)
    public = sig.replace(parameters=[p for n, p in sig.parameters.items() if n != "ctx"])

    def work(ctx: JobContext) -> dict[str, Any]:
        def runner(**kw: Any) -> dict[str, Any]:
            return body(ctx, **kw)

        runner.__signature__ = public  # type: ignore[attr-defined]
        return guard(ToolSpec(name, name, runner, budget_tokens), app.ledger)(**kwargs)

    job = app.jobs.submit(name, kwargs, work, timeout_s=timeout_s)
    return envelope.ok(
        f"{name} is running as {job}; poll job_status for the result.",
        {"job_handle": job, "state": "queued"},
        limits=["Results are available from job_status once the state is 'done'."],
        next_steps=[f"job_status(job_handle='{job}')"],
    )


def register(server: MCPServer, registry: Registry, app: App) -> None:
    def job_status(job_handle: str) -> dict[str, Any]:
        """State, progress and (when done) the result of an asynchronous job."""
        rec = app.jobs.get(job_handle)
        data: dict[str, Any] = {
            "job_handle": job_handle,
            "kind": rec["kind"],
            "state": rec["state"],
            "progress": round(rec["progress"], 3),
            "message": rec["message"],
            "created_utc": rec["created_utc"],
            "finished_utc": rec["finished_utc"],
        }
        if rec["state"] == "done":
            data["result"] = rec["result"]
            res = rec["result"] or {}
            env = envelope.ok(
                f"Job {job_handle} finished: {res.get('verdict', '')}",
                data,
                limits=res.get("limits", []),
                next_steps=res.get("next_steps", []),
            )
        elif rec["state"] in ("queued", "running"):
            env = envelope.ok(
                f"Job {job_handle} is {rec['state']} ({rec['progress']:.0%}).",
                data,
                next_steps=[f"job_status(job_handle='{job_handle}') again shortly"],
            )
        else:
            env = envelope.ok(
                f"Job {job_handle} {rec['state']}: {rec['message']}",
                data,
                next_steps=["Fix the cause and submit the work again."],
            )
        return env

    def cancel_job(job_handle: str) -> dict[str, Any]:
        """Request cancellation of a queued or running job (takes effect at its next check)."""
        ok = app.jobs.cancel(job_handle)
        state = app.jobs.get(job_handle)["state"]
        return envelope.ok(
            f"Cancellation requested for {job_handle}."
            if ok
            else f"{job_handle} already finished ({state}); nothing to cancel.",
            {"job_handle": job_handle, "cancel_requested": ok, "state": state},
        )

    for spec in [
        ToolSpec("job_status", job_status.__doc__ or "", job_status, 2600, {"job_handle": "<job>"}),
        ToolSpec("cancel_job", cancel_job.__doc__ or "", cancel_job, 300, {"job_handle": "<job>"}),
    ]:
        server.add_tool(registry.register(spec), name=spec.name, description=spec.description)
