"""M5.T1: report builder, number guard, provenance and disclosures."""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from simplymz_mcp.report.builder import (
    ReportError,
    Section,
    build,
    narrative_numbers,
    to_html,
    traceable,
)

EV1 = "ev:01ARZ3NDEKTSV4RRFFQ69G5FAV"
EV2 = "ev:01ARZ3NDEKTSV4RRFFQ69G5FAW"


def _rec(result: dict[str, Any], op: str = "qc_batch") -> dict[str, Any]:
    return {
        "op": op,
        "result": result,
        "ts_utc": "2026-10-05T00:00:00+00:00",
        "result_digest": "ab" * 32,
        "input_hashes": ["cd" * 32],
        "versions": {"simplymz-mcp": "0.1.0", "numpy": "2.0"},
    }


LEDGER = {
    EV1: _rec(
        {
            "status": "ok",
            "verdict": "Batch PASSES QC.",
            "data": {
                "metrics": {"rt_drift_min": {"value": 0.0123, "verdict": "pass"}},
                "n_runs": 11,
                "ids": [3.5, 7],
            },
            "limits": ["Thresholds are defaults, not a standard."],
        }
    ),
    EV2: _rec(
        {
            "status": "ok",
            "verdict": "Peak",
            "data": {"area_counts_min": 106446.702},
            "limits": ["At SNR >= 100 every validation trace was within +/-3%."],
        },
        op="integrate_peak",
    ),
}


def _build(body: str, evidence: list[str] | None = None) -> Any:
    return build("T", [Section("Results", body)], evidence or [], LEDGER.get)


def test_tokenizer_ignores_identifiers() -> None:
    text = (
        "Drift 0.21 min; caffeine C8H10N4O2 [M+H]+ 195.0877; 13C M+1; 12% and -3.5 ppm; "
        "1e5; run a_01; " + EV1 + "\n1. item"
    )
    assert narrative_numbers(text) == ["0.21", "195.0877", "12", "-3.5", "1e5"]


def test_traceable_at_written_precision() -> None:
    assert traceable("0.01", [0.0123]) and traceable("0.012", [0.0123])
    assert not traceable("0.02", [0.0123])
    assert traceable("1.06e5", [106446.7])


def test_slots_filled_from_ledger_and_numbers_traced() -> None:
    r = _build(f"RT drift was {{{EV1}:data.metrics.rt_drift_min.value}} min over 11 runs.")
    assert "RT drift was 0.0123 min over 11 runs." in r.markdown
    assert r.slots_filled == 1 and r.numbers_checked == 1 and r.referenced == [EV1]


def test_invented_number_is_rejected_and_listed() -> None:
    with pytest.raises(ReportError) as ei:
        _build(f"Drift {{{EV1}:data.metrics.rt_drift_min.value}} min, recovery 98.5% in 12 runs.")
    assert ei.value.offending == ["98.5", "12"]
    assert "98.5" in ei.value.message and "slots" in ei.value.hint


def test_numbers_need_referenced_evidence() -> None:
    with pytest.raises(ReportError):
        _build("Area 106446.702 counts*min.")  # true value, but EV2 not referenced
    assert _build("Area 106446.702 counts*min.", [EV2]).numbers_checked == 1


@pytest.mark.parametrize(
    ("slot", "phrase"),
    [
        (f"{{{EV1}:data.nope}}", "does not exist"),
        (f"{{{EV1}:data.metrics}}", "structure"),
        ("{ev:01ARZ3NDEKTSV4RRFFQ69G5FAX:verdict}", "not in the ledger"),
    ],
)
def test_bad_slots(slot: str, phrase: str) -> None:
    with pytest.raises(ReportError) as ei:
        _build(f"Value {slot}.")
    assert phrase in ei.value.message


def test_list_index_slot_and_disclosures_and_provenance() -> None:
    r = _build(f"First id {{{EV1}:data.ids[0]}}; area {{{EV2}:data.area_counts_min}}.")
    assert "First id 3.5; area 106447." in r.markdown
    assert "## Limits and disclosures" in r.markdown
    assert "every validation trace was within" in r.markdown  # ADR 0008 note carried
    assert f"| `{EV1}` | qc_batch |" in r.markdown and "simplymz-mcp 0.1.0" in r.markdown


def test_html_is_escaped() -> None:
    page = to_html("# T\n\n<script>alert(1)</script>\n\n- a `x`\n", "T<")
    assert "<script>" not in page and "&lt;script&gt;" in page and "<code>x</code>" in page


POOL = [0.0123, 11.0, 3.5, 7.0, 106446.702]


@settings(max_examples=60, deadline=None)
@given(
    st.lists(
        st.sampled_from(
            [
                "0.0123",
                "11",
                "3.5",
                "7",
                "106446.702",
                f"{{{EV1}:data.n_runs}}",
                f"{{{EV2}:data.area_counts_min}}",
            ]
        ),
        min_size=1,
        max_size=8,
    ),
    st.floats(min_value=1000, max_value=9000, allow_nan=False).map(lambda x: f"{x:.1f}"),
)
def test_property_every_narrative_number_traces_to_the_ledger(
    parts: list[str], intruder: str
) -> None:
    body = " and ".join(parts) + "."
    r = _build(body, [EV1, EV2])
    for tok in narrative_numbers(r.markdown.split("## Limits")[0].split("## Results", 1)[1]):
        assert traceable(tok, POOL)
    if not traceable(intruder, POOL):
        with pytest.raises(ReportError):
            _build(body + f" Extra {intruder}.", [EV1, EV2])


def test_sentence_ending_numbers_are_caught() -> None:
    """Regression: a period after a number once hid it from the guard entirely."""
    assert narrative_numbers("Recovery was 97.2. Then 4 runs.") == ["97.2", "4"]
    with pytest.raises(ReportError):
        _build("Recovery was 97.2.")
