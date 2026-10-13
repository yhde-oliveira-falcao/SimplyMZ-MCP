"""Runtime configuration: allowed data root and safety limits."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ENV_ROOT = "SIMPLYMZ_ROOT"


@dataclass(frozen=True)
class Limits:
    max_file_mb: int = 2048
    max_scans: int = 500_000
    allowed_extensions: tuple[str, ...] = (".mzml", ".mzml.gz", ".csv", ".msp", ".mgf")


@dataclass(frozen=True)
class Config:
    root: Path
    limits: Limits = field(default_factory=Limits)
    extras: tuple[str, ...] = ()
    cache_dir: Path | None = None  # None -> SIMPLYMZ_CACHE or <root>/.simplymz
    cache_max_mb: float = 2048
    handle_ttl_days: float = 30

    @classmethod
    def from_args(cls, root: str | None, cache_dir: str | None = None) -> Config:
        raw = root or os.environ.get(ENV_ROOT) or os.getcwd()
        r = Path(raw).expanduser().resolve()
        c = Path(cache_dir).expanduser().resolve() if cache_dir else None
        return cls(root=r, extras=detect_extras(), cache_dir=c)

    def resolved_cache_dir(self) -> Path:
        return self.cache_dir or default_cache_dir(self.root)


def detect_extras() -> tuple[str, ...]:
    """Optional engines that happen to be importable (ADR 0001)."""
    import importlib.util

    found = []
    for module, extra in (("pyopenms", "openms"), ("asari", "asari"), ("matchms", "matchms")):
        if importlib.util.find_spec(module) is not None:
            found.append(extra)
    return tuple(found)


ENV_CACHE = "SIMPLYMZ_CACHE"


def default_cache_dir(root: Path) -> Path:
    raw = os.environ.get(ENV_CACHE)
    return Path(raw).expanduser().resolve() if raw else root / ".simplymz"
