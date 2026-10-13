"""Feature alignment across runs (ADR 0005, plan M3.T5).

Greedy one-to-one matching by combined score
``(d_ppm / ppm_tol)^2 + (d_rt / rt_tol)^2`` between each run's monoisotopic features and
the growing consensus list. Pairs outside either tolerance never match. Ambiguities (a
feature with several candidates, or a consensus feature claimed by several features of
one run) are counted as conflicts and resolved by score.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Consensus:
    cid: str
    mzs: list[float] = field(default_factory=list)
    rts: list[float] = field(default_factory=list)
    members: dict[str, dict[str, Any]] = field(default_factory=dict)  # run label -> feature

    @property
    def mz(self) -> float:
        return sum(self.mzs) / len(self.mzs)

    @property
    def rt(self) -> float:
        return sum(self.rts) / len(self.rts)

    def add(self, label: str, f: dict[str, Any]) -> None:
        self.members[label] = f
        self.mzs.append(float(f["mz"]))
        self.rts.append(float(f["rt_min"]))


def align(
    runs: list[tuple[str, list[dict[str, Any]]]], ppm_tol: float = 10.0, rt_tol: float = 0.15
) -> dict[str, Any]:
    """runs: [(label, monoisotopic features)]. Returns consensus features and statistics."""
    if not runs:
        return {"consensus": [], "conflicts": 0, "unmatched_new": 0, "params": {}}
    order = sorted(range(len(runs)), key=lambda i: -len(runs[i][1]))  # richest run first
    cons: list[Consensus] = []
    conflicts = 0
    new_from_later = 0
    for rank, i in enumerate(order):
        label, feats = runs[i]
        pairs = []
        cand_count_f: dict[int, int] = {}
        cand_count_c: dict[int, int] = {}
        for fi, f in enumerate(feats):
            for ci, c in enumerate(cons):
                d_ppm = abs(float(f["mz"]) - c.mz) / c.mz * 1e6
                d_rt = abs(float(f["rt_min"]) - c.rt)
                if d_ppm <= ppm_tol and d_rt <= rt_tol:
                    pairs.append(((d_ppm / ppm_tol) ** 2 + (d_rt / rt_tol) ** 2, fi, ci))
                    cand_count_f[fi] = cand_count_f.get(fi, 0) + 1
                    cand_count_c[ci] = cand_count_c.get(ci, 0) + 1
        conflicts += sum(1 for n in cand_count_f.values() if n > 1)
        conflicts += sum(1 for n in cand_count_c.values() if n > 1)
        used_f: set[int] = set()
        used_c: set[int] = set()
        for _, fi, ci in sorted(pairs):
            if fi in used_f or ci in used_c:
                continue
            cons[ci].add(label, feats[fi])
            used_f.add(fi)
            used_c.add(ci)
        for fi, f in enumerate(feats):
            if fi not in used_f:
                c = Consensus(cid="")
                c.add(label, f)
                cons.append(c)
                if rank > 0:
                    new_from_later += 1
    cons.sort(key=lambda c: (c.rt, c.mz))
    for n, c in enumerate(cons, start=1):
        c.cid = f"C{n:05d}"
    return {
        "consensus": cons,
        "conflicts": conflicts,
        "unmatched_new": new_from_later,
        "params": {"ppm_tol": ppm_tol, "rt_tol_min": rt_tol, "method": "greedy one-to-one"},
    }
