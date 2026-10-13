"""Run registry: path → run: handle → RunData, surviving restarts (plan M1.T3)."""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from simplymz_mcp.config import Config
from simplymz_mcp.core.errors import ErrorCode, SimplyMZError
from simplymz_mcp.io.mzml import RunData, read_mzml, sha256_file
from simplymz_mcp.io.security import resolve_data_path
from simplymz_mcp.state.cache import RunCache
from simplymz_mcp.state.store import Store


@dataclass
class Loaded:
    handle: str
    run: RunData
    cache_hit: bool
    reused_handle: bool


class RunRegistry:
    def __init__(self, config: Config, store: Store, cache: RunCache, memory_runs: int = 4):
        self.config = config
        self.store = store
        self.cache = cache
        self._mem: OrderedDict[str, RunData] = OrderedDict()
        self._mem_max = memory_runs
        self._lock = threading.RLock()

    def _remember(self, sha: str, run: RunData) -> None:
        with self._lock:
            self._mem[sha] = run
            self._mem.move_to_end(sha)
            while len(self._mem) > self._mem_max:
                self._mem.popitem(last=False)

    def _materialise(self, sha: str, path: Path) -> tuple[RunData, bool]:
        with self._lock:
            if sha in self._mem:
                self._mem.move_to_end(sha)
                return self._mem[sha], True
        if self.cache.has(sha):
            run = self.cache.load(sha)
            run.path = path
            hit = True
        else:
            run = read_mzml(path, self.config.limits)
            if run.sha256 != sha:  # file changed between hashing and parsing
                raise SimplyMZError(
                    ErrorCode.MALFORMED_FILE,
                    f"{path.name} changed while it was being read.",
                    "Wait for the copy/acquisition to finish, then load it again.",
                )
            self.cache.save(run)
            hit = False
        self._remember(sha, run)
        return run, hit

    def load(self, user_path: str) -> Loaded:
        path = resolve_data_path(self.config.root, user_path, self.config.limits)
        sha = sha256_file(path)
        run, hit = self._materialise(sha, path)
        existing = self.store.find("run", "sha256", sha)
        if existing:
            self.store.get(existing)  # touch
            return Loaded(existing, run, hit, True)
        rel = path.relative_to(self.config.root.resolve()).as_posix()
        handle = self.store.create("run", {"sha256": sha, "path": rel})
        return Loaded(handle, run, hit, False)

    def get(self, handle: str) -> RunData:
        meta = self.store.get(handle, "run")
        sha = meta["sha256"]
        path = self.config.root.resolve() / meta["path"]
        with self._lock:
            in_memory = sha in self._mem
        if not in_memory and not self.cache.has(sha):
            # Cache evicted: re-validate the source file and make sure it is unchanged.
            path = resolve_data_path(self.config.root, meta["path"], self.config.limits)
            if sha256_file(path) != sha:
                raise SimplyMZError(
                    ErrorCode.UNKNOWN_HANDLE,
                    f"The file behind {handle} has changed since it was loaded.",
                    "Load it again with load_run to analyse the current contents.",
                )
        run, _ = self._materialise(sha, path)
        return run
