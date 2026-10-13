"""M5.T4: eval harness behaviour without network or API key."""

from __future__ import annotations

from pathlib import Path

import pytest

from eval import llm_eval


def test_cache_budget_and_parsing(tmp_path: Path) -> None:
    calls = []

    def fake(prompt: str) -> str:
        calls.append(prompt)
        return "FORMULA: C8H10N4O2; CONFIDENCE: 0.9"

    budget = llm_eval.Budget(2)
    ask = llm_eval.cached(fake, "m", budget, tmp_path)
    assert ask("p1") == ask("p1")  # second call served from cache
    ask("p2")
    assert len(calls) == 2
    with pytest.raises(RuntimeError, match="cap"):
        ask("p3")
    assert llm_eval.parse("FORMULA: C6H12O6; CONFIDENCE: 0.42") == ("C6H12O6", 0.42)
    assert llm_eval.parse("no idea") == (None, None)


def test_run_with_fake_model_scores_tool_help() -> None:
    truth = {t["mz"]: t["truth"] for t in llm_eval.tasks()}
    assert len(truth) >= 20

    def fake(prompt: str) -> str:
        if "SimplyMZ" in prompt:  # pretend the tool output was followed
            mz = float(prompt.split("m/z ")[1].split(" ")[0])
            return f"FORMULA: {truth[mz]}; CONFIDENCE: 0.8"
        return "FORMULA: C1H4; CONFIDENCE: 0.6"

    res = llm_eval.run(fake)
    assert res["with_simplymz"]["accuracy"] == 1.0 and res["alone"]["accuracy"] == 0.0
    assert res["alone"]["mean_confidence_when_wrong"] == 0.6


def test_missing_key_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        llm_eval.anthropic_ask("m")
