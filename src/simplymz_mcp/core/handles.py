"""Opaque handles: ``<kind>:<ULID>``.

A small, dependency-free ULID implementation (Crockford base32, 48-bit ms timestamp +
80 random bits). ULIDs sort by creation time, which keeps ledger exports readable.
"""

from __future__ import annotations

import os
import re
import time
from typing import Final

KINDS: Final[frozenset[str]] = frozenset(
    {"run", "batch", "chrom", "feat", "ftab", "ann", "ev", "job", "lib"}
)
_ALPHABET: Final[str] = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_HANDLE_RE: Final[re.Pattern[str]] = re.compile(r"^([a-z]+):([0-9A-HJKMNP-TV-Z]{26})$")


def _encode(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        chars.append(_ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def new_ulid(timestamp_ms: int | None = None, randomness: bytes | None = None) -> str:
    """Return a 26-character ULID string."""
    ts = int(time.time() * 1000) if timestamp_ms is None else timestamp_ms
    if not 0 <= ts < 2**48:
        raise ValueError("timestamp_ms out of ULID range")
    rnd = os.urandom(10) if randomness is None else randomness
    if len(rnd) != 10:
        raise ValueError("randomness must be exactly 10 bytes")
    return _encode(ts, 10) + _encode(int.from_bytes(rnd, "big"), 16)


def new_handle(kind: str) -> str:
    if kind not in KINDS:
        raise ValueError(f"unknown handle kind {kind!r}; expected one of {sorted(KINDS)}")
    return f"{kind}:{new_ulid()}"


def parse_handle(handle: str) -> tuple[str, str]:
    """Split a handle into (kind, ulid). Raises ValueError on malformed input."""
    m = _HANDLE_RE.match(handle)
    if not m or m.group(1) not in KINDS:
        raise ValueError(f"malformed handle {handle!r}")
    return m.group(1), m.group(2)


def ulid_timestamp_ms(ulid: str) -> int:
    value = 0
    for ch in ulid[:10]:
        value = value * 32 + _ALPHABET.index(ch)
    return value
