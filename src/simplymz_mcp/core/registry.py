"""Tool registry: one place that knows every tool's budget, schema and example.

``Registry.register`` wraps a tool function so that, at the MCP boundary:
  * ``SimplyMZError`` becomes an instructive error envelope (never a stack trace);
  * any other exception becomes an INTERNAL error envelope and is logged to stderr;
  * oversized outputs are truncated (``truncated: true``) or refused (BUDGET_EXCEEDED).
"""

from __future__ import annotations

import functools
import inspect
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from simplymz_mcp.core import envelope
from simplymz_mcp.core.budget import DEFAULT_BUDGET_TOKENS, fits, truncate_lists
from simplymz_mcp.core.errors import ErrorCode, SimplyMZError

log = logging.getLogger("simplymz_mcp")

ToolFn = Callable[..., dict[str, Any]]
PROVENANCE_KEY = "_provenance"
PROVENANCE_RESERVE_TOKENS = 16


class LedgerLike(Protocol):
    def record(
        self,
        op: str,
        params: dict[str, Any],
        result: dict[str, Any],
        *,
        input_hashes: list[str] | None = None,
        parents: list[str] | None = None,
    ) -> str: ...


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    fn: ToolFn
    budget_tokens: int = DEFAULT_BUDGET_TOKENS
    example_input: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Docstrings arrive indented; clients should see clean text.
        object.__setattr__(self, "description", inspect.cleandoc(self.description))


def enforce_budget(result: dict[str, Any], budget_tokens: int) -> dict[str, Any]:
    if fits(result, budget_tokens):
        return result
    shrunk = truncate_lists(result, budget_tokens)
    if fits(shrunk, budget_tokens):
        return shrunk
    return envelope.error(
        ErrorCode.BUDGET_EXCEEDED,
        f"Result exceeds the {budget_tokens}-token budget even after truncation.",
        "Narrow the request (smaller RT range, fewer files) or use a paging handle.",
    )


def guard(spec: ToolSpec, ledger: LedgerLike | None = None) -> ToolFn:
    """Return a wrapper with the same signature that applies the boundary rules.

    Tools may add a private ``_provenance`` dict (``input_hashes``, ``parents``) to their
    envelope; it is removed here and written to the ledger with the call's parameters.
    Successful and insufficient-evidence results get exactly one ledger row; errors none.
    """
    fn = spec.fn
    sig = inspect.signature(fn, eval_str=True)

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            result = fn(*args, **kwargs)
        except SimplyMZError as exc:
            return envelope.from_exception(exc)
        except Exception:
            log.exception("tool %s failed", spec.name)
            return envelope.error(
                ErrorCode.INTERNAL,
                f"Internal error in {spec.name}.",
                "This is a bug. Check the server log (stderr) and report it.",
            )
        prov = result.pop(PROVENANCE_KEY, None) or {}
        # reserve room for the provenance_id added below
        out = enforce_budget(result, spec.budget_tokens - PROVENANCE_RESERVE_TOKENS)
        if ledger is not None and out.get("status") != "error":
            bound = sig.bind_partial(*args, **kwargs)
            bound.apply_defaults()
            try:
                out["provenance_id"] = ledger.record(
                    spec.name,
                    dict(bound.arguments),
                    out,
                    input_hashes=prov.get("input_hashes"),
                    parents=prov.get("parents"),
                )
            except Exception:
                log.exception("ledger write failed for %s", spec.name)
                return envelope.error(
                    ErrorCode.INTERNAL,
                    "Result computed but could not be recorded in the evidence ledger.",
                    "Check that the cache directory is writable and has free space.",
                )
        return out

    # Resolve string annotations against the *tool's* module, so the SDK builds the
    # right JSON schema even though the wrapper lives here.
    wrapper.__signature__ = sig  # type: ignore[attr-defined]
    del wrapper.__wrapped__  # stop introspection from re-reading unresolved strings
    wrapper.__annotations__ = {
        name: p.annotation
        for name, p in wrapper.__signature__.parameters.items()  # type: ignore[attr-defined]
        if p.annotation is not inspect.Parameter.empty
    }
    wrapper.__annotations__["return"] = dict[str, Any]
    return wrapper


class Registry:
    def __init__(self, ledger: LedgerLike | None = None) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self.ledger = ledger

    def register(self, spec: ToolSpec) -> ToolFn:
        if spec.name in self._specs:
            raise ValueError(f"tool {spec.name!r} registered twice")
        if spec.budget_tokens <= 0:
            raise ValueError("budget_tokens must be positive")
        self._specs[spec.name] = spec
        return guard(spec, self.ledger)

    def get(self, name: str) -> ToolSpec:
        return self._specs[name]

    def names(self) -> list[str]:
        return sorted(self._specs)

    def specs(self) -> list[ToolSpec]:
        return [self._specs[n] for n in self.names()]
