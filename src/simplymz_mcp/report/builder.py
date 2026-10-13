"""Report builder with a number guard (plan M5.T1, ADR 0006).

Numbers enter a report in exactly two ways:
1. slots ``{ev:<ULID>:<path>}`` (e.g. ``{ev:01J...:data.metrics.rt_drift_min.value}``),
   filled from the ledger entry's stored result;
2. numbers written in the narrative that also occur in a referenced ledger entry's result
   (compared at the precision written: "4.4" matches 4.4012).
Any other numeric token is rejected and listed. Numbers inside identifiers (formulas such
as C8H10N4O2, adducts such as [M+H]+, "13C", "M+1", ULIDs) and ordered-list markers are not
treated as measurements. Every referenced entry's ``limits`` are carried into the report so
precision notes (ADR 0008) and engine notes (ADR 0009) stay next to the numbers.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

SLOT = re.compile(r"\{(ev:[0-9A-HJKMNP-TV-Z]{26}):([A-Za-z0-9_.\[\]-]+)\}")
NUMBER = re.compile(
    r"(?<![\w.+\-\]\[])"  # not inside an identifier, formula, adduct or version
    r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"
    r"(?![\w.]*[A-Za-z_])"  # not followed by letters (13C, 2H, units glued to digits)
    r"(?!\.?\d)"  # a complete number; a sentence-ending period is allowed
)
LIST_MARKER = re.compile(r"^\s*\d+\.\s", re.M)


class ReportError(Exception):
    def __init__(self, message: str, hint: str, offending: list[str] | None = None) -> None:
        super().__init__(message)
        self.message, self.hint, self.offending = message, hint, offending or []


@dataclass
class Section:
    heading: str
    body: str


@dataclass
class Report:
    title: str
    markdown: str
    referenced: list[str]
    slots_filled: int
    numbers_checked: int
    disclosures: list[str] = field(default_factory=list)


def lookup(obj: Any, path: str) -> Any:
    """Follow a dotted path with optional [index] parts through dicts and lists."""
    cur = obj
    for part in re.findall(r"[^.\[\]]+|\[\d+\]", path):
        cur = cur[int(part[1:-1])] if part.startswith("[") else cur[part]
    return cur


def fmt(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def numbers_in(obj: Any) -> list[float]:
    out: list[float] = []
    if isinstance(obj, bool):
        return out
    if isinstance(obj, int | float):
        out.append(float(obj))
    elif isinstance(obj, str):
        out.extend(float(t) for t in NUMBER.findall(obj) if _is_number(t))
    elif isinstance(obj, dict):
        for v in obj.values():
            out.extend(numbers_in(v))
    elif isinstance(obj, list | tuple):
        for v in obj:
            out.extend(numbers_in(v))
    return out


def _is_number(tok: str) -> bool:
    try:
        float(tok)
        return True
    except ValueError:
        return False


def _decimals(tok: str) -> int:
    mant = tok.lower().split("e")[0]
    return len(mant.split(".")[1]) if "." in mant else 0


def traceable(tok: str, pool: Iterable[float]) -> bool:
    """True if some pool value equals the token at the token's written precision."""
    v = float(tok)
    d = _decimals(tok)
    if "e" in tok.lower():
        sig = len(tok.lower().split("e")[0].lstrip("+-").replace(".", "").lstrip("0")) or 1
        return any(float(f"{p:.{sig - 1}e}") == float(f"{v:.{sig - 1}e}") for p in pool)
    return any(round(p, d) == round(v, d) or round(abs(p), d) == round(abs(v), d) for p in pool)


def narrative_numbers(text: str) -> list[str]:
    text = LIST_MARKER.sub(" ", text)
    text = re.sub(r"`[^`]*`", " ", text)  # inline code is quoted, not measured
    return [t for t in NUMBER.findall(text) if _is_number(t)]


def build(
    title: str,
    sections: list[Section],
    evidence: list[str],
    get_record: Callable[[str], dict[str, Any] | None],
) -> Report:
    referenced: list[str] = list(dict.fromkeys(evidence))
    for s in sections:
        for ev, _ in SLOT.findall(s.body):
            if ev not in referenced:
                referenced.append(ev)
    records: dict[str, dict[str, Any]] = {}
    for ev in referenced:
        rec = get_record(ev)
        if rec is None:
            raise ReportError(
                f"{ev} is not in the ledger.",
                "Reference provenance_ids returned by tools in this SimplyMZ instance.",
            )
        records[ev] = rec
    pool = [n for rec in records.values() for n in numbers_in(rec["result"])]
    filled = 0
    out_sections = []
    bad: list[str] = []
    checked = 0

    def fill(m: re.Match[str]) -> str:
        nonlocal filled
        ev, path = m.group(1), m.group(2)
        try:
            value = lookup(records[ev]["result"], path)
        except (KeyError, IndexError, TypeError) as exc:
            raise ReportError(
                f"Slot {{{ev}:{path}}} does not exist in that ledger entry.",
                "Paths start at the tool result, e.g. data.metrics.<name>.value or verdict.",
            ) from exc
        if isinstance(value, dict | list):
            raise ReportError(
                f"Slot {{{ev}:{path}}} points to a structure, not a value.",
                "Point the slot at a single number or string.",
            )
        filled += 1
        return fmt(value)

    for s in sections:
        narrative = SLOT.sub(" ", s.body)
        for tok in narrative_numbers(narrative) + narrative_numbers(s.heading):
            checked += 1
            if not traceable(tok, pool):
                bad.append(tok)
        out_sections.append((s.heading, SLOT.sub(fill, s.body)))
    if bad:
        raise ReportError(
            f"Number guard: {len(bad)} number(s) in the narrative are not in any referenced "
            "ledger entry: " + ", ".join(sorted(set(bad), key=bad.index)) + ".",
            "Replace them with {ev:<id>:<path>} slots, reference the evidence that contains "
            "them, or remove them.",
            bad,
        )
    disclosures: list[str] = []
    for ev in referenced:
        for lim in records[ev]["result"].get("limits", []):
            if lim not in disclosures:
                disclosures.append(lim)
    md = [f"# {title}", ""]
    for heading, body in out_sections:
        md += [f"## {heading}", "", body.strip(), ""]
    if disclosures:
        md += ["## Limits and disclosures", "", *[f"- {d}" for d in disclosures], ""]
    md += [
        "## Provenance",
        "",
        "| Evidence | Tool | Time (UTC) | Result digest | Inputs (SHA-256) |",
        "|---|---|---|---|---|",
    ]
    for ev in referenced:
        r = records[ev]
        inputs = ", ".join(h[:12] for h in r["input_hashes"]) or "-"
        md.append(
            f"| `{ev}` | {r['op']} | {r['ts_utc']} | `{r['result_digest'][:16]}` | {inputs} |"
        )
    versions = records[referenced[0]]["versions"] if referenced else {}
    if versions:
        md += ["", "Software: " + ", ".join(f"{k} {v}" for k, v in sorted(versions.items()))]
    md += ["", "Parameters of each tool call are stored in the ledger under the evidence id."]
    return Report(title, "\n".join(md) + "\n", referenced, filled, checked, disclosures)


def to_html(markdown: str, title: str) -> str:
    """Small Markdown subset (headings, lists, tables, paragraphs, code) to safe HTML."""
    out = [
        f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}"
        "</title><style>body{font-family:system-ui,sans-serif;max-width:52rem;margin:2rem "
        "auto;padding:0 1rem;line-height:1.5}table{border-collapse:collapse}td,th{border:"
        "1px solid #ccc;padding:.25rem .5rem}code{background:#f3f3f3}</style></head><body>"
    ]
    in_list = in_table = False

    def inline(t: str) -> str:
        t = html.escape(t)
        return re.sub(r"`([^`]*)`", r"<code>\1</code>", t)

    for line in markdown.splitlines():
        if in_list and not line.startswith("- "):
            out.append("</ul>")
            in_list = False
        if in_table and not line.startswith("|"):
            out.append("</table>")
            in_table = False
        if line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            out.append(f"<h{level}>{inline(line[level:].strip())}</h{level}>")
        elif line.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(line[2:])}</li>")
        elif line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(re.fullmatch(r"-+", c) for c in cells):
                continue
            if not in_table:
                out.append("<table>")
                in_table = True
                out.append("<tr>" + "".join(f"<th>{inline(c)}</th>" for c in cells) + "</tr>")
            else:
                out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in cells) + "</tr>")
        elif line.strip():
            out.append(f"<p>{inline(line)}</p>")
    if in_list:
        out.append("</ul>")
    if in_table:
        out.append("</table>")
    out.append("</body></html>")
    return "\n".join(out) + "\n"
