from __future__ import annotations

from simplymz_mcp.analytics.align import align


def _f(fid: str, mz: float, rt: float) -> dict:
    return {"id": fid, "mz": mz, "rt_min": rt, "area": 1.0}


def test_jitter_within_tolerance_aligns() -> None:
    runs = [
        ("a", [_f("1", 200.0, 3.00), _f("2", 300.0, 5.0)]),
        ("b", [_f("1", 200.0008, 3.06), _f("2", 300.001, 4.95)]),
        ("c", [_f("1", 199.9994, 2.97)]),
    ]
    res = align(runs, ppm_tol=10, rt_tol=0.15)
    assert len(res["consensus"]) == 2
    first = res["consensus"][0]
    assert set(first.members) == {"a", "b", "c"} and res["conflicts"] == 0
    assert abs(first.mz - 200.00007) < 1e-4


def test_outside_tolerance_stays_separate() -> None:
    res = align(
        [
            ("a", [_f("1", 200.0, 3.0)]),
            ("b", [_f("1", 200.0, 3.3)]),
            ("c", [_f("1", 200.004, 3.0)]),
        ],
        ppm_tol=10,
        rt_tol=0.15,
    )
    assert len(res["consensus"]) == 3 and res["unmatched_new"] == 2


def test_two_candidates_best_chosen_and_conflict_counted() -> None:
    runs = [("a", [_f("x", 200.0, 3.0), _f("y", 200.0015, 3.08)]), ("b", [_f("z", 200.0012, 3.07)])]
    res = align(runs, ppm_tol=10, rt_tol=0.15)
    by = {c.members.get("a", {}).get("id"): c for c in res["consensus"]}
    assert by["y"].members["b"]["id"] == "z"  # closer in both m/z and RT
    assert "b" not in by["x"].members
    assert res["conflicts"] >= 1


def test_one_to_one_within_a_run() -> None:
    runs = [("a", [_f("1", 200.0, 3.0)]), ("b", [_f("p", 200.0002, 3.01), _f("q", 200.0004, 3.02)])]
    res = align(runs)
    assert len(res["consensus"]) == 2  # q could not also join the consensus taken by p
    assert all(len([m for m in c.members if m == "b"]) <= 1 for c in res["consensus"])
    assert align([])["consensus"] == []
