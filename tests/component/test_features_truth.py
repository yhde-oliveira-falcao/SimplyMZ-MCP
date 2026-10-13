from __future__ import annotations

import json

import pytest

from simplymz_mcp.analytics.features import detect_features
from simplymz_mcp.io.mzml import read_mzml
from simplymz_mcp.synth.fixtures import truth_path
from tests.conftest import FIXTURES
from tests.helpers import measurable_truth, score_features

MZML = sorted(p for p in FIXTURES.rglob("*") if p.name.endswith((".mzML", ".mzML.gz")))


@pytest.mark.parametrize("path", MZML, ids=lambda p: p.name)
def test_masstrace_lite_finds_every_measurable_compound(path) -> None:  # type: ignore[no-untyped-def]
    truth = measurable_truth(json.loads(truth_path(path).read_text()))
    res = detect_features(read_mzml(path))
    matched, good, n_mono = score_features(res["features"], truth)
    names = {c["name"] for c in truth["compounds"]}
    assert matched == names, names - matched
    assert good == n_mono, "monoisotopic features not explained by ground truth"
