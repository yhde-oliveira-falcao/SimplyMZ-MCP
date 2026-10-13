"""The gate's process runner: heartbeats while running, kills the process group on timeout."""

from __future__ import annotations

import subprocess
import sys

import pytest

from tests.conftest import REPO

sys.path.insert(0, str(REPO / "scripts"))
import verify


def test_heartbeat_reports_slow_step(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(verify, "HEARTBEAT_S", 0.2)
    monkeypatch.setitem(verify._CURRENT, "step", "unit_hb")
    p = verify.sh(
        [
            sys.executable,
            "-c",
            "import time; print('working', flush=True); time.sleep(1.0); print('done')",
        ]
    )
    assert p.returncode == 0 and "done" in p.stdout
    out = capsys.readouterr().out
    assert "unit_hb still running" in out and "working" in out


def test_timeout_kills_process_group(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verify, "HEARTBEAT_S", 0.2)
    monkeypatch.setitem(verify._CURRENT, "step", "unit_to")
    with pytest.raises(subprocess.TimeoutExpired) as ei:
        verify.sh(
            [sys.executable, "-c", "import time; print('start', flush=True); time.sleep(30)"],
            timeout=0,
        )
    assert "start" in str(ei.value.output)
