from __future__ import annotations

import gzip
import json
from pathlib import Path

import numpy as np
import pytest
from pyteomics.auxiliary import unitfloat

from simplymz_mcp.config import Limits
from simplymz_mcp.core.errors import ErrorCode, SimplyMZError
from simplymz_mcp.io.mzml import (
    CENTROID,
    PROFILE,
    UNKNOWN_MODE,
    guess_centroided,
    read_mzml,
    rt_minutes,
)
from simplymz_mcp.synth.fixtures import truth_path
from tests.conftest import FIXTURES

MZML = sorted(p for p in FIXTURES.rglob("*") if p.name.endswith((".mzML", ".mzML.gz")))


@pytest.mark.parametrize("path", MZML, ids=lambda p: p.name)
def test_every_fixture_reads_and_matches_truth(path: Path) -> None:
    truth = json.loads(truth_path(path).read_text())
    run = read_mzml(path)
    assert run.sha256 == truth["sha256"]
    assert run.meta["ms_level_counts"].get("1", 0) == truth["n_ms1"]
    assert run.meta["ms_level_counts"].get("2", 0) == truth["n_ms2"]
    assert run.meta["polarity"] == truth["polarity"]
    assert run.meta["spectrum_mode"] == "centroid"
    assert run.meta["rt_range_min"][0] == pytest.approx(truth["rt_range_min"][0], abs=1e-4)
    assert run.offsets[-1] == run.mz.size == run.intensity.size
    assert not run.meta["warnings"]


def test_ms2_precursors_match_planted_ions() -> None:
    path = FIXTURES / "runs" / "ms2_dda.mzML.gz"
    truth = json.loads(truth_path(path).read_text())
    run = read_mzml(path)
    prec = run.scans.precursor_mz[run.scans.ms_level == 2]
    planted = {round(c["ion_mz"], 4) for c in truth["compounds"]}
    assert {round(float(p), 4) for p in prec} == planted
    assert np.isnan(run.scans.precursor_mz[run.scans.ms_level == 1]).all()


def test_dropout_scans_are_empty_with_zero_tic() -> None:
    path = FIXTURES / "faults" / "dropout.mzML.gz"
    truth = json.loads(truth_path(path).read_text())
    run = read_mzml(path)
    ms1 = np.flatnonzero(run.scans.ms_level == 1)
    for i in truth["dropout_ms1_indices"]:
        assert run.scans.n_peaks[ms1[i]] == 0 and run.scans.tic[ms1[i]] == 0


def _err(path: Path, limits: Limits | None = None) -> SimplyMZError:
    with pytest.raises(SimplyMZError) as ei:
        read_mzml(path, limits)
    assert ei.value.hint
    return ei.value


def test_truncated_file_is_malformed(tmp_path: Path) -> None:
    data = (FIXTURES / "runs" / "clean_pos.mzML").read_bytes()
    bad = tmp_path / "cut.mzML"
    bad.write_bytes(data[: len(data) // 2])
    e = _err(bad)
    assert e.code == ErrorCode.MALFORMED_FILE and "msconvert" in e.hint


def test_not_xml_and_bad_gzip_are_malformed(tmp_path: Path) -> None:
    (tmp_path / "x.mzML").write_text("hello, not xml")
    (tmp_path / "y.mzML.gz").write_bytes(b"not gzip at all")
    assert _err(tmp_path / "x.mzML").code == ErrorCode.MALFORMED_FILE
    assert _err(tmp_path / "y.mzML.gz").code == ErrorCode.MALFORMED_FILE


def test_no_spectra_is_malformed(tmp_path: Path) -> None:
    p = tmp_path / "empty.mzML"
    p.write_text(
        '<?xml version="1.0"?><mzML xmlns="http://psi.hupo.org/ms/mzml">'
        '<run id="r"><spectrumList count="0"/></run></mzML>'
    )
    e = _err(p)
    assert e.code == ErrorCode.MALFORMED_FILE and "no spectra" in e.message


def test_max_scans_limit(tmp_path: Path) -> None:
    e = _err(FIXTURES / "runs" / "clean_pos.mzML", Limits(max_scans=10))
    assert e.code == ErrorCode.FILE_TOO_LARGE


def test_gzip_and_plain_give_identical_content(tmp_path: Path) -> None:
    src = FIXTURES / "runs" / "clean_pos.mzML"
    gz = tmp_path / "clean_pos.mzML.gz"
    gz.write_bytes(gzip.compress(src.read_bytes()))
    a, b = read_mzml(src), read_mzml(gz)
    assert np.array_equal(a.mz, b.mz) and np.array_equal(a.scans.rt_min, b.scans.rt_min)


def test_rt_units() -> None:
    assert rt_minutes(unitfloat(90.0, "second")) == pytest.approx(1.5)
    assert rt_minutes(unitfloat(1.5, "minute")) == pytest.approx(1.5)
    assert rt_minutes(2.0) == 2.0


def test_centroid_heuristic() -> None:
    assert guess_centroided(np.linspace(100, 101, 200)) == PROFILE
    assert guess_centroided(np.linspace(100, 900, 200)) == CENTROID
    assert guess_centroided(np.array([1.0, 2.0])) == UNKNOWN_MODE
