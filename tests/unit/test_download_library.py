"""MassBank licence merge (offline, format-faithful snippets)."""

from __future__ import annotations

import sys

from simplymz_mcp.annotation.library import parse_msp
from tests.conftest import REPO

sys.path.insert(0, str(REPO / "scripts"))
from download_library import annotate_msp, licence_map

JSON = """[
  {
    "description": "This MassBank record with Accession MSBNK-TEST-0001 contains ...",
    "license": "https://creativecommons.org/licenses/by-sa/4.0",
  },
  {
    "description": "This MassBank record with Accession MSBNK-TEST-0002 contains ...",
    "license": "https://creativecommons.org/licenses/by/4.0",
  }
]""".splitlines()

MSP = """Name: A
DB#: MSBNK-TEST-0001
PrecursorMZ: 391.2474
Comments: Parent=391.2474
Num Peaks: 2
107.0491 43
185.1325 999

Name: B
DB#: MSBNK-TEST-0002
PrecursorMZ: 249.0405
Num Peaks: 1
205.0507 999

Name: C
DB#: MSBNK-TEST-0003
PrecursorMZ: 100.0
Num Peaks: 1
50.0 10
""".splitlines(keepends=True)


def test_licences_are_attached_per_record() -> None:
    lic = licence_map(JSON)
    assert lic == {
        "MSBNK-TEST-0001": "https://creativecommons.org/licenses/by-sa/4.0",
        "MSBNK-TEST-0002": "https://creativecommons.org/licenses/by/4.0",
    }
    spectra = parse_msp("".join(annotate_msp(MSP, lic)))
    got = {s.name: s.licence for s in spectra}
    assert got == {
        "A": "https://creativecommons.org/licenses/by-sa/4.0",
        "B": "https://creativecommons.org/licenses/by/4.0",
        "C": "unknown",
    }
    assert [len(s.mz) for s in spectra] == [2, 1, 1]
