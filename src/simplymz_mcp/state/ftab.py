"""Feature tables on disk (Parquet, ADR 0002): run tables and aligned batch tables."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

RUN_COLUMNS = (
    "id",
    "mz",
    "rt_min",
    "rt_start_min",
    "rt_end_min",
    "height",
    "area",
    "fwhm_min",
    "snr",
    "n_points",
    "isotope_of",
    "isotope_index",
    "charge",
    "adduct_group",
)


class FeatureTables:
    def __init__(self, cache_dir: Path) -> None:
        self.dir = cache_dir / "ftabs"
        self.dir.mkdir(parents=True, exist_ok=True)

    def _p(self, key: str, part: str) -> Path:
        return self.dir / f"{key}.{part}.parquet"

    def save_run(self, key: str, features: list[dict[str, Any]], meta: dict[str, Any]) -> None:
        cols = {c: [f.get(c) for f in features] for c in RUN_COLUMNS}
        t = pa.table(cols).replace_schema_metadata({b"meta": json.dumps(meta).encode()})
        pq.write_table(t, self._p(key, "features"))

    def load_run(self, key: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        t = pq.read_table(self._p(key, "features"))
        meta = json.loads((t.schema.metadata or {}).get(b"meta", b"{}"))
        return t.to_pylist(), meta

    def save_aligned(
        self,
        key: str,
        consensus: list[dict[str, Any]],
        members: list[dict[str, Any]],
        meta: dict[str, Any],
    ) -> None:
        pq.write_table(
            pa.Table.from_pylist(consensus).replace_schema_metadata(
                {b"meta": json.dumps(meta).encode()}
            ),
            self._p(key, "consensus"),
        )
        pq.write_table(pa.Table.from_pylist(members), self._p(key, "members"))

    def load_aligned(
        self, key: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        c = pq.read_table(self._p(key, "consensus"))
        m = pq.read_table(self._p(key, "members"))
        meta = json.loads((c.schema.metadata or {}).get(b"meta", b"{}"))
        return c.to_pylist(), m.to_pylist(), meta
