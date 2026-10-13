"""Sample sheet parsing and validation (plan M2.T1). Pure: text in, rows or errors out."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from simplymz_mcp.core.errors import ErrorCode, SimplyMZError

REQUIRED = ("file", "sample_type", "group", "injection_order")
SAMPLE_TYPES = ("sample", "blank", "qc")
MAX_REPORTED = 8


@dataclass(frozen=True)
class SheetRow:
    file: str
    sample_type: str
    group: str
    injection_order: int


def parse_sample_sheet(text: str) -> list[SheetRow]:
    """Parse CSV with columns file, sample_type, group, injection_order.

    Collects every problem (with row numbers) and raises one instructive error."""
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    header = [h.strip().lower() for h in (reader.fieldnames or [])]
    missing = [c for c in REQUIRED if c not in header]
    if missing:
        raise SimplyMZError(
            ErrorCode.INVALID_ARGUMENT,
            f"Sample sheet is missing column(s): {', '.join(missing)}.",
            "Header must be: file,sample_type,group,injection_order "
            "(group may be empty for blanks and QCs).",
        )
    reader.fieldnames = header
    rows: list[SheetRow] = []
    problems: list[str] = []
    seen_order: dict[int, int] = {}
    seen_file: dict[str, int] = {}
    for n, raw in enumerate(reader, start=2):  # row 1 is the header
        rec = {k: (v or "").strip() for k, v in raw.items() if k}
        if not any(rec.values()):
            continue
        st = rec["sample_type"].lower()
        if not rec["file"]:
            problems.append(f"row {n}: empty file")
        if st not in SAMPLE_TYPES:
            problems.append(f"row {n}: sample_type {rec['sample_type']!r} not in {SAMPLE_TYPES}")
        if st == "sample" and not rec["group"]:
            problems.append(f"row {n}: samples need a group")
        try:
            order = int(rec["injection_order"])
            if order < 1:
                raise ValueError
        except ValueError:
            problems.append(
                f"row {n}: injection_order {rec['injection_order']!r} is not a positive integer"
            )
            order = -n
        if order in seen_order:
            problems.append(f"row {n}: injection_order {order} duplicates row {seen_order[order]}")
        seen_order.setdefault(order, n)
        if rec["file"] in seen_file:
            problems.append(
                f"row {n}: file {rec['file']!r} duplicates row {seen_file[rec['file']]}"
            )
        seen_file.setdefault(rec["file"], n)
        rows.append(SheetRow(rec["file"], st, rec["group"], order))
    if not rows:
        problems.append("no data rows")
    if problems:
        shown = "; ".join(problems[:MAX_REPORTED])
        more = f" (+{len(problems) - MAX_REPORTED} more)" if len(problems) > MAX_REPORTED else ""
        raise SimplyMZError(
            ErrorCode.INVALID_ARGUMENT,
            f"Sample sheet has {len(problems)} problem(s): {shown}{more}.",
            "Fix the listed rows and load the batch again.",
        )
    return sorted(rows, key=lambda r: r.injection_order)
