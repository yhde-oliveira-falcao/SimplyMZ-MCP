"""Generate (or check) the synthetic fixture set in tests/fixtures/.

    uv run python scripts/generate_fixtures.py           # regenerate
    uv run python scripts/generate_fixtures.py --check   # verify committed fixtures

--check compares platform-independent content digests (exact bytes can legitimately
differ across zlib builds); on the same platform the SHA-256 must match as well.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from simplymz_mcp.synth.fixtures import DEFAULT_SEED, write_all

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
MAX_TOTAL_BYTES = 5 * 1024 * 1024


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = ap.parse_args()
    if not args.check:
        manifest = write_all(OUT, args.seed)
        total = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())
        print(f"wrote {len(manifest['files'])} fixtures, total {total / 1024:.0f} KiB")
        return 0 if total <= MAX_TOTAL_BYTES else 1
    committed = json.loads((OUT / "MANIFEST.json").read_text())
    with tempfile.TemporaryDirectory() as tmp:
        fresh = write_all(Path(tmp), committed["seed"])
    problems = []
    for rel, meta in committed["files"].items():
        new = fresh["files"].get(rel)
        key = "content_digest" if "content_digest" in meta else "sha256"
        if new is None or new[key] != meta[key]:
            problems.append(rel)
        elif new["sha256"] != meta["sha256"]:
            print(f"note: {rel} bytes differ but content matches (zlib build)", file=sys.stderr)
    if set(fresh["files"]) != set(committed["files"]):
        problems.append("file set differs")
    for p in problems:
        print(f"MISMATCH: {p}")
    print("fixtures OK" if not problems else f"{len(problems)} fixture(s) differ")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
