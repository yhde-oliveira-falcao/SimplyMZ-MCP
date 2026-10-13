"""LLM evaluation (plan M5.T4): reported, not gated.

Compares Claude alone with Claude given SimplyMZ's tool output on formula
identification from m/z + isotope pattern (oracle compounds below 400 Da). The model is
pinned, responses are cached on disk (re-runs are free and reproducible), the number of
API requests is capped, and the API key comes only from ANTHROPIC_API_KEY.

    ANTHROPIC_API_KEY=... uv run python -m eval.llm_eval [--max-requests 80]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "eval" / "cache"
MODEL = "claude-sonnet-5-5"  # pinned; change deliberately and re-run
MAX_TOKENS = 300

Ask = Callable[[str], str]


class Budget:
    def __init__(self, max_requests: int) -> None:
        self.left = max_requests

    def spend(self) -> None:
        if self.left <= 0:
            raise RuntimeError("request cap reached; raise --max-requests to continue")
        self.left -= 1


def cached(ask: Ask, model: str, budget: Budget, cache_dir: Path = CACHE) -> Ask:
    cache_dir.mkdir(parents=True, exist_ok=True)

    def inner(prompt: str) -> str:
        key = hashlib.sha256(f"{model}\n{prompt}".encode()).hexdigest()
        path = cache_dir / f"{key}.json"
        if path.exists():
            return str(json.loads(path.read_text())["text"])
        budget.spend()
        text = ask(prompt)
        path.write_text(json.dumps({"model": model, "prompt": prompt, "text": text}))
        return text

    return inner


def anthropic_ask(model: str) -> Ask:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set; the LLM evaluation was not run")
    import urllib.request

    def ask(prompt: str) -> str:
        body = json.dumps(
            {
                "model": model,
                "max_tokens": MAX_TOKENS,
                "messages": [{"role": "user", "content": prompt}],
            }
        ).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=body,
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        return "".join(b.get("text", "") for b in data["content"])

    return ask


def tasks() -> list[dict[str, Any]]:
    from simplymz_mcp.annotation.adducts import ADDUCTS
    from simplymz_mcp.annotation.formulas import enumerate_formulas
    from simplymz_mcp.annotation.propose import rank
    from simplymz_mcp.synth.elements import (
        ELECTRON_MASS,
        ISOTOPES,
        isotope_pattern,
        monoisotopic_mass,
    )
    from tests.oracle.compounds import ORACLE, elements_for

    out = []
    for name, f in sorted(ORACLE.items()):
        m = monoisotopic_mass(f)
        if m >= 400:
            continue
        mz = m + ISOTOPES["H"][0][0] - ELECTRON_MASS
        pat = [round(a, 4) for _, a in isotope_pattern(f, 3)]
        cands = rank(
            enumerate_formulas(ADDUCTS["[M+H]+"].neutral(mz), 5.0, elements_for(f)), [1.0, *pat[1:]]
        )
        out.append(
            {
                "name": name,
                "truth": f,
                "mz": round(mz, 5),
                "pattern": pat,
                "tool": [
                    {k: c[k] for k in ("formula", "ppm", "score", "rejected")} for c in cands[:5]
                ],
            }
        )
    return out


PROMPT = (
    "An LC-MS feature was measured as [M+H]+ at m/z {mz} with relative isotope "
    "intensities M+0, M+1, M+2 = {pattern}. Allowed elements: C, H, N, O, P, S, Cl. "
    "{extra}Give the most likely neutral molecular formula and your confidence (0-1). "
    "Answer exactly as: FORMULA: <formula>; CONFIDENCE: <number>"
)


def parse(text: str) -> tuple[str | None, float | None]:
    f = re.search(r"FORMULA:\s*([A-Za-z0-9]+)", text)
    c = re.search(r"CONFIDENCE:\s*([0-9.]+)", text)
    return (f.group(1) if f else None, float(c.group(1)) if c else None)


def run(ask: Ask) -> dict[str, Any]:
    rows = []
    for t in tasks():
        alone = parse(ask(PROMPT.format(mz=t["mz"], pattern=t["pattern"], extra="")))
        tool_txt = (
            "SimplyMZ propose_formulas returned (best first): " + json.dumps(t["tool"]) + ". "
        )
        helped = parse(ask(PROMPT.format(mz=t["mz"], pattern=t["pattern"], extra=tool_txt)))
        rows.append({"name": t["name"], "truth": t["truth"], "alone": alone, "with": helped})

    def summary(key: str) -> dict[str, Any]:
        correct = [r[key][0] == r["truth"] for r in rows]
        conf = [r[key][1] for r in rows if r[key][1] is not None]
        return {
            "accuracy": round(sum(correct) / len(rows), 3),
            "mean_confidence": round(sum(conf) / len(conf), 3) if conf else None,
            "mean_confidence_when_wrong": round(
                sum(r[key][1] or 0 for r, ok in zip(rows, correct, strict=True) if not ok)
                / max(1, correct.count(False)),
                3,
            ),
        }

    return {
        "model": MODEL,
        "n_tasks": len(rows),
        "alone": summary("alone"),
        "with_simplymz": summary("with"),
        "rows": rows,
    }


def write(res: dict[str, Any]) -> None:
    path = ROOT / "eval" / "results.md"
    old = path.read_text() if path.exists() else "# Evaluation results\n\n"
    head = old[: old.index("## LLM evaluation")] if "## LLM evaluation" in old else old
    a, w = res["alone"], res["with_simplymz"]
    md = [
        "## LLM evaluation (reported, not gated)",
        "",
        f"Model `{res['model']}`, {res['n_tasks']} formula tasks (oracle compounds < 400 Da).",
        "",
        "| Setting | Accuracy | Mean confidence | Mean confidence when wrong |",
        "|---|---|---|---|",
        f"| Claude alone | {a['accuracy']} | {a['mean_confidence']} | "
        f"{a['mean_confidence_when_wrong']} |",
        f"| Claude + SimplyMZ | {w['accuracy']} | {w['mean_confidence']} | "
        f"{w['mean_confidence_when_wrong']} |",
        "",
    ]
    path.write_text(head + "\n".join(md) + "\n")
    (ROOT / "eval" / "llm_results.json").write_text(json.dumps(res, indent=1) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-requests", type=int, default=80)
    args = ap.parse_args()
    try:
        ask = cached(anthropic_ask(MODEL), MODEL, Budget(args.max_requests))
        res = run(ask)
    except RuntimeError as exc:
        print(f"LLM evaluation not run: {exc}")
        return 2
    write(res)
    print(json.dumps({k: res[k] for k in ("model", "n_tasks", "alone", "with_simplymz")}))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    sys.exit(main())
