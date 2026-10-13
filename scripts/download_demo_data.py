"""Download the pinned public demo datasets (network). Usage:
uv run python scripts/download_demo_data.py --root DATA_DIR [--id openms-ffm-1]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from simplymz_mcp.datasets import DATASETS, download


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--id", action="append")
    args = ap.parse_args()
    for ds_id in args.id or sorted(DATASETS):
        ds = DATASETS[ds_id]
        print(f"{ds.id}: {ds.size_bytes / 1e6:.1f} MB, {ds.licence}")
        print(f"  -> {download(ds, Path(args.root) / 'public_data' / ds.id)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
