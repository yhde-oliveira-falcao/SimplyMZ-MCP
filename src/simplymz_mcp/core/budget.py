"""Token-budget estimation and truncation (ADR 0003).

The estimate is deliberately conservative: it is computed on the indented JSON the
MCP SDK actually sends as text content, divided by 3.5 characters per token.
"""

from __future__ import annotations

import json
import math
from typing import Any, Final

CHARS_PER_TOKEN: Final[float] = 3.5
DEFAULT_BUDGET_TOKENS: Final[int] = 1500


def estimate_tokens(obj: Any) -> int:
    text = json.dumps(obj, indent=2, ensure_ascii=False, default=str)
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def fits(obj: Any, budget_tokens: int) -> bool:
    return estimate_tokens(obj) <= budget_tokens


def truncate_lists(envelope: dict[str, Any], budget_tokens: int) -> dict[str, Any]:
    """Shrink the longest list inside ``envelope["data"]`` until the envelope fits.

    Sets ``truncated: true`` when anything was removed. Returns a new dict; the input is
    not modified. If the envelope still does not fit with every list empty, the caller
    must handle it (the registry converts that into a BUDGET_EXCEEDED error).
    """
    out: dict[str, Any] = json.loads(json.dumps(envelope, default=str))
    data = out.get("data")
    if not isinstance(data, dict):
        return out
    while not fits(out, budget_tokens):
        lists = [(k, v) for k, v in data.items() if isinstance(v, list) and v]
        if not lists:
            break
        key, longest = max(lists, key=lambda kv: len(kv[1]))
        keep = len(longest) // 2
        data[key] = longest[:keep]
        out["truncated"] = True
    return out
