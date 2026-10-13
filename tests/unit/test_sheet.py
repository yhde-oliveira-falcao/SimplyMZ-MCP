from __future__ import annotations

import pytest

from simplymz_mcp.analytics.sheet import parse_sample_sheet
from simplymz_mcp.core.errors import ErrorCode, SimplyMZError

GOOD = """file,sample_type,group,injection_order
b.mzML,sample,A,2
a.mzML,blank,,1
q.mzML,QC,,3
"""


def _err(text: str) -> SimplyMZError:
    with pytest.raises(SimplyMZError) as ei:
        parse_sample_sheet(text)
    assert ei.value.code == ErrorCode.INVALID_ARGUMENT and ei.value.hint
    return ei.value


def test_good_sheet_sorted_by_injection_order_and_case_insensitive() -> None:
    rows = parse_sample_sheet("\ufeff" + GOOD + "\n,,,\n")
    assert [r.file for r in rows] == ["a.mzML", "b.mzML", "q.mzML"]
    assert rows[2].sample_type == "qc"


def test_missing_column() -> None:
    e = _err("file,sample_type,injection_order\na,qc,1\n")
    assert "group" in e.message


@pytest.mark.parametrize(
    ("row", "phrase"),
    [
        ("x.mzML,standard,,9", "sample_type"),
        ("x.mzML,sample,,9", "need a group"),
        ("x.mzML,blank,,zero", "positive integer"),
        ("x.mzML,blank,,0", "positive integer"),
        ("x.mzML,blank,,2", "duplicates row 2"),
        ("b.mzML,blank,,9", "file 'b.mzML' duplicates"),
        (",blank,,9", "empty file"),
    ],
)
def test_each_problem_reported_with_row_number(row: str, phrase: str) -> None:
    e = _err(GOOD + row + "\n")
    assert phrase in e.message and "row 5" in e.message


def test_problems_are_aggregated() -> None:
    e = _err("file,sample_type,group,injection_order\nx,bad,,a\ny,bad,,b\n")
    assert "4 problem(s)" in e.message


def test_empty_sheet() -> None:
    assert "no data rows" in _err("file,sample_type,group,injection_order\n").message
