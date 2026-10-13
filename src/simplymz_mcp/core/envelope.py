"""The output envelope every tool returns (plan §4.1)."""

from __future__ import annotations

from typing import Any, Literal

from simplymz_mcp.core.errors import ErrorCode, SimplyMZError

Status = Literal["ok", "insufficient_evidence", "error"]
ENVELOPE_KEYS = (
    "status",
    "verdict",
    "data",
    "limits",
    "next_steps",
    "provenance_id",
    "truncated",
    "page_handle",
)


def ok(
    verdict: str,
    data: dict[str, Any] | None = None,
    *,
    limits: list[str] | None = None,
    next_steps: list[str] | None = None,
    provenance_id: str | None = None,
    status: Status = "ok",
) -> dict[str, Any]:
    if status == "error":
        raise ValueError("use error() for error envelopes")
    if not verdict.strip():
        raise ValueError("verdict must be a non-empty sentence")
    return {
        "status": status,
        "verdict": verdict,
        "data": data or {},
        "limits": limits or [],
        "next_steps": next_steps or [],
        "provenance_id": provenance_id,
        "truncated": False,
        "page_handle": None,
    }


def insufficient(verdict: str, data: dict[str, Any] | None = None, **kw: Any) -> dict[str, Any]:
    """A correct, honest 'not enough evidence' result. Not a failure."""
    return ok(verdict, data, status="insufficient_evidence", **kw)


def error(code: ErrorCode, message: str, hint: str) -> dict[str, Any]:
    return {
        "status": "error",
        "verdict": message,
        "error": {"code": str(code), "message": message, "hint": hint},
        "data": {},
        "limits": [],
        "next_steps": [],
        "provenance_id": None,
        "truncated": False,
        "page_handle": None,
    }


def from_exception(exc: SimplyMZError) -> dict[str, Any]:
    return error(exc.code, exc.message, exc.hint)


def is_valid_envelope(obj: object) -> bool:
    if not isinstance(obj, dict) or any(k not in obj for k in ENVELOPE_KEYS):
        return False
    if obj["status"] not in ("ok", "insufficient_evidence", "error"):
        return False
    if obj["status"] == "error":
        err = obj.get("error")
        return isinstance(err, dict) and {"code", "message", "hint"} <= err.keys()
    return isinstance(obj["data"], dict) and isinstance(obj["verdict"], str)
