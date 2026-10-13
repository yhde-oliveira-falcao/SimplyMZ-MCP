from __future__ import annotations

import subprocess
import sys

from tests.conftest import REPO


def test_tools_doc_is_current() -> None:
    p = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "gen_tools_doc.py"), "--check"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert p.returncode == 0, p.stdout + p.stderr
