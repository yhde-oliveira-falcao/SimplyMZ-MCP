from __future__ import annotations

import inspect
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from simplymz_mcp.core import envelope
from simplymz_mcp.core.budget import estimate_tokens, fits, truncate_lists
from simplymz_mcp.core.errors import ErrorCode, SimplyMZError
from simplymz_mcp.core.handles import (
    KINDS,
    new_handle,
    new_ulid,
    parse_handle,
    ulid_timestamp_ms,
)
from simplymz_mcp.core.registry import Registry, ToolSpec, enforce_budget

# ---------- envelope ----------


def test_ok_envelope_has_all_keys_and_defaults() -> None:
    env = envelope.ok("Run loaded.", {"n": 1})
    assert envelope.is_valid_envelope(env)
    assert env["status"] == "ok" and env["truncated"] is False and env["page_handle"] is None
    assert env["limits"] == [] and env["next_steps"] == []


def test_insufficient_evidence_is_a_valid_non_error_result() -> None:
    env = envelope.insufficient("Not enough evidence to assign a formula.")
    assert env["status"] == "insufficient_evidence"
    assert envelope.is_valid_envelope(env)


def test_error_envelope_is_instructive() -> None:
    env = envelope.error(ErrorCode.POLARITY_MISMATCH, "Run is negative mode.", "Use [M-H]-.")
    assert envelope.is_valid_envelope(env)
    assert env["error"] == {
        "code": "POLARITY_MISMATCH",
        "message": "Run is negative mode.",
        "hint": "Use [M-H]-.",
    }


def test_from_exception_preserves_code_and_hint() -> None:
    exc = SimplyMZError(ErrorCode.VENDOR_FORMAT, "Thermo .raw is not supported.", "msconvert")
    env = envelope.from_exception(exc)
    assert env["error"]["code"] == "VENDOR_FORMAT" and env["error"]["hint"] == "msconvert"


@pytest.mark.parametrize("bad", ["", "   "])
def test_empty_verdict_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        envelope.ok(bad)


def test_ok_refuses_error_status() -> None:
    with pytest.raises(ValueError):
        envelope.ok("x", status="error")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "obj",
    [
        None,
        [],
        {"status": "ok"},
        {**envelope.ok("x"), "status": "maybe"},
        {**envelope.error(ErrorCode.INTERNAL, "m", "h"), "error": {"code": "X"}},
    ],
)
def test_invalid_envelopes_detected(obj: object) -> None:
    assert not envelope.is_valid_envelope(obj)


# ---------- handles ----------


def test_handle_roundtrip_for_every_kind() -> None:
    for kind in KINDS:
        h = new_handle(kind)
        k, u = parse_handle(h)
        assert k == kind and len(u) == 26


def test_unknown_kind_rejected() -> None:
    with pytest.raises(ValueError):
        new_handle("spectrum")


@pytest.mark.parametrize("bad", ["run:", "run:abc", "xyz:01ARZ3NDEKTSV4RRFFQ69G5FAV", "run-01AR"])
def test_malformed_handles_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_handle(bad)


def test_ulid_known_vector() -> None:
    # Spec example: timestamp 1469918176385 encodes to "01ARYZ6S41".
    u = new_ulid(1469918176385, bytes(10))
    assert u == "01ARYZ6S41" + "0" * 16
    assert ulid_timestamp_ms(u) == 1469918176385


def test_ulid_rejects_bad_inputs() -> None:
    with pytest.raises(ValueError):
        new_ulid(-1)
    with pytest.raises(ValueError):
        new_ulid(0, b"short")


@given(st.integers(0, 2**48 - 2))
def test_ulids_sort_by_time(ts: int) -> None:
    assert new_ulid(ts, bytes(10)) < new_ulid(ts + 1, bytes(10))


# ---------- budget ----------


@given(st.lists(st.integers(), max_size=200))
def test_estimate_is_monotonic_in_list_length(xs: list[int]) -> None:
    assert estimate_tokens({"d": xs}) <= estimate_tokens({"d": [*xs, 123456]})


def test_truncate_shrinks_longest_list_and_flags_it() -> None:
    env = envelope.ok("big", {"points": list(range(5000)), "small": [1, 2]})
    assert not fits(env, 300)
    out = truncate_lists(env, 300)
    assert fits(out, 300)
    assert out["truncated"] is True
    assert len(out["data"]["points"]) < 5000
    assert out["data"]["points"] == list(range(len(out["data"]["points"])))  # prefix kept
    assert env["truncated"] is False  # input untouched


def test_truncate_noop_when_fits() -> None:
    env = envelope.ok("tiny", {"a": [1]})
    assert truncate_lists(env, 1500) == env


def test_enforce_budget_refuses_unshrinkable_result() -> None:
    env = envelope.ok("x" * 10_000)
    out = enforce_budget(env, 100)
    assert out["status"] == "error" and out["error"]["code"] == "BUDGET_EXCEEDED"


# ---------- registry ----------


def _demo(mz: float, label: str = "a") -> dict[str, Any]:
    return envelope.ok(f"{label} {mz}")


def test_registry_preserves_signature_and_rejects_duplicates() -> None:
    reg = Registry()
    wrapped = reg.register(ToolSpec("demo", "d", _demo, budget_tokens=200))
    params = inspect.signature(wrapped).parameters
    assert list(params) == ["mz", "label"]
    assert params["mz"].annotation is float
    assert wrapped(mz=1.5)["verdict"] == "a 1.5"
    with pytest.raises(ValueError):
        reg.register(ToolSpec("demo", "d", _demo))
    assert reg.names() == ["demo"] and reg.get("demo").budget_tokens == 200


def test_registry_rejects_nonpositive_budget() -> None:
    with pytest.raises(ValueError):
        Registry().register(ToolSpec("x", "d", _demo, budget_tokens=0))


def test_guard_converts_exceptions_to_envelopes() -> None:
    def known() -> dict[str, Any]:
        raise SimplyMZError(ErrorCode.FILE_NOT_FOUND, "missing.mzML not found", "check path")

    def bug() -> dict[str, Any]:
        raise RuntimeError("boom")

    reg = Registry()
    a = reg.register(ToolSpec("known", "d", known))()
    b = reg.register(ToolSpec("bug", "d", bug))()
    assert a["error"]["code"] == "FILE_NOT_FOUND"
    assert b["error"]["code"] == "INTERNAL" and "boom" not in b["verdict"]


def test_guard_truncates_oversized_output() -> None:
    def big() -> dict[str, Any]:
        return envelope.ok("many", {"rows": list(range(3000))})

    out = Registry().register(ToolSpec("big", "d", big, budget_tokens=250))()
    assert out["truncated"] is True and fits(out, 250)
