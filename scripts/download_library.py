"""Opt-in MassBank downloader (plan M4.T4 / ADR 0004). Never run by tests or CI.

MassBank's NIST-format MSP has no licence field, so licences are taken per record from
MassBank.json (Bioschemas JSON-LD, one `license` per record) and written into each MSP
record as `Comments: licence=<url>; accession=<MSBNK-...>`, which SimplyMZ's MSP
parser reads. Records without a licence are labelled "unknown".

    uv run python scripts/download_library.py --root DATA_DIR [--release 2026.03]
(~670 MB download; the merged MSP is written to DATA_DIR/libraries/)
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.request
from collections.abc import Iterable, Iterator
from pathlib import Path

BASE = "https://github.com/MassBank/MassBank-data/releases/download/{release}/{name}"
ACC = re.compile(r"Accession (MSBNK-[A-Za-z0-9_-]+)")
LIC = re.compile(r'"license"\s*:\s*"([^"]+)"')


def licence_map(json_lines: Iterable[str]) -> dict[str, str]:
    """Stream MassBank.json: pair each record's accession with the next licence seen."""
    out: dict[str, str] = {}
    pending: str | None = None
    for line in json_lines:
        m = ACC.search(line)
        if m:
            pending = m.group(1)
            continue
        m = LIC.search(line)
        if m and pending:
            out.setdefault(pending, m.group(1))
            pending = None
    return out


def annotate_msp(msp_lines: Iterable[str], licences: dict[str, str]) -> Iterator[str]:
    """Yield MSP lines with a licence comment added to every record (DB# = accession)."""
    record: list[str] = []

    def flush() -> Iterator[str]:
        acc = next(
            (ln.split(":", 1)[1].strip() for ln in record if ln.lower().startswith("db#:")), ""
        )
        lic = licences.get(acc, "unknown")
        extra = f"licence={lic}; accession={acc or 'unknown'}"
        done = False
        for ln in record:
            if ln.lower().startswith("comments:") and not done:
                yield f"{ln.rstrip()}; {extra}\n"
                done = True
            elif ln.lower().startswith("num peaks:") and not done:
                yield f"Comments: {extra}\n"
                yield ln
                done = True
            else:
                yield ln

    for line in msp_lines:
        if line.strip() == "":
            if record:
                yield from flush()
                yield "\n"
            record = []
        else:
            record.append(line if line.endswith("\n") else line + "\n")
    if record:
        yield from flush()


def _lines(url: str) -> Iterator[str]:
    with urllib.request.urlopen(url, timeout=120) as resp:
        for raw in resp:
            yield raw.decode("utf-8", errors="replace")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--release", default="2026.03")
    args = ap.parse_args()
    print("Reading licences from MassBank.json (~535 MB, streamed) ...", flush=True)
    lic = licence_map(_lines(BASE.format(release=args.release, name="MassBank.json")))
    print(f"  {len(lic)} records with a licence", flush=True)
    out = Path(args.root) / "libraries" / f"MassBank_{args.release}_licensed.msp"
    out.parent.mkdir(parents=True, exist_ok=True)
    msp = _lines(BASE.format(release=args.release, name="MassBank_NISTformat.msp"))
    with open(out, "w", encoding="utf-8") as fh:
        fh.writelines(annotate_msp(msp, lic))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
