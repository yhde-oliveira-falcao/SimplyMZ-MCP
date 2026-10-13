from __future__ import annotations

from simplymz_mcp.annotation.library import Library, parse_mgf, parse_msp
from simplymz_mcp.synth.fixtures import LIBRARY_COMPOUNDS
from tests.conftest import FIXTURES


def test_parse_fixture_msp_with_licences() -> None:
    spectra = parse_msp((FIXTURES / "library" / "synthetic_library.msp").read_text())
    assert sorted(s.name for s in spectra) == sorted(LIBRARY_COMPOUNDS)
    assert all(s.licence.startswith("CC0") for s in spectra)
    assert all(s.mz.size >= 2 and (s.mz[:-1] < s.mz[1:]).all() for s in spectra)


def test_parse_mgf_and_unknown_licence() -> None:
    text = """BEGIN IONS
TITLE=thing one
PEPMASS=195.0877 1000
LICENSE=CC BY 4.0
138.0662 999
110.0713 400
END IONS
BEGIN IONS
TITLE=no licence
PEPMASS=166.0863
120.0808 999
END IONS
"""
    s = parse_mgf(text)
    assert [x.name for x in s] == ["thing one", "no licence"]
    assert s[0].licence == "CC BY 4.0" and s[1].licence == "unknown"
    assert s[0].precursor_mz == 195.0877


def test_precursor_index() -> None:
    lib = Library("t", parse_msp((FIXTURES / "library" / "synthetic_library.msp").read_text()))
    hits = lib.by_precursor(195.087652, 5)
    assert [h.name for h in hits] == ["caffeine"]
    assert lib.by_precursor(209.0921, 10) == []  # kynurenine is not in the library
    assert lib.licences() == {"CC0-1.0 (synthetic)": len(LIBRARY_COMPOUNDS)}
