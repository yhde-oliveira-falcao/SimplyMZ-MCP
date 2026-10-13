"""Fixture compounds: real small molecules with invented, plausible chromatographic behaviour.

Fragment entries are *ion* formulas (charge already included); their m/z is the
neutral-formula mass minus one electron mass. Fragments were chosen from common
neutral losses; they are synthetic test data, not reference spectra.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from simplymz_mcp.synth.elements import ELECTRON_MASS, monoisotopic_mass

PROTON = 1.00782503223 - ELECTRON_MASS  # H atom minus electron

# adduct -> (mass delta added to neutral M for z=1, charge sign)
ADDUCTS: dict[str, tuple[float, int]] = {
    "[M+H]+": (PROTON, 1),
    "[M+Na]+": (22.9897692820 - ELECTRON_MASS, 1),
    "[M-H]-": (-PROTON, -1),
}


@dataclass(frozen=True)
class Fragment:
    ion_formula: str
    rel_intensity: float  # 0..1

    @property
    def mz(self) -> float:
        return monoisotopic_mass(self.ion_formula) - ELECTRON_MASS


@dataclass(frozen=True)
class Compound:
    name: str
    formula: str
    rt_min: float
    fwhm_min: float = 0.15
    fragments: tuple[Fragment, ...] = field(default_factory=tuple)

    def ion_mz(self, adduct: str) -> float:
        delta, _ = ADDUCTS[adduct]
        return monoisotopic_mass(self.formula) + delta


F = Fragment
COMPOUNDS: dict[str, Compound] = {
    c.name: c
    for c in [
        Compound("creatinine", "C4H7N3O", 1.10, fragments=(F("C4H6N3", 0.4), F("C3H8N3", 1.0))),
        Compound("niacinamide", "C6H6N2O", 1.60, fragments=(F("C6H4NO", 1.0), F("C5H4N", 0.5))),
        Compound("carnitine", "C7H15NO3", 1.95, fragments=(F("C4H5O2", 1.0), F("C7H14NO2", 0.3))),
        Compound("uric_acid", "C5H4N4O3", 2.30),
        Compound("adenosine", "C10H13N5O4", 2.90, fragments=(F("C5H6N5", 1.0), F("C5H3N4", 0.2))),
        Compound(
            "theophylline", "C7H8N4O2", 3.45, fragments=(F("C6H5N4O", 0.6), F("C5H6N3O", 1.0))
        ),
        Compound(
            "tyrosine",
            "C9H11NO3",
            3.90,
            fragments=(F("C9H9O3", 0.5), F("C8H10NO", 1.0), F("C8H7O", 0.3)),
        ),
        Compound("caffeine", "C8H10N4O2", 4.40, fragments=(F("C6H8N3O", 1.0), F("C5H8N3", 0.4))),
        Compound("phenylalanine", "C9H11NO2", 5.10, fragments=(F("C8H10N", 1.0), F("C8H7", 0.3))),
        Compound(
            "kynurenine", "C10H12N2O3", 5.60, fragments=(F("C10H10NO3", 1.0), F("C6H8N", 0.6))
        ),
        Compound(
            "glutathione",
            "C10H17N3O6S",
            6.10,
            fragments=(F("C10H15N2O6S", 0.4), F("C8H13N2O4S", 1.0), F("C5H8NO3", 0.6)),
        ),
        Compound(
            "tryptophan",
            "C11H12N2O2",
            6.70,
            fragments=(F("C11H10NO2", 1.0), F("C9H8NO", 0.5), F("C8H8N", 0.3)),
        ),
        Compound("hippuric_acid", "C9H9NO3", 7.30, fragments=(F("C7H5O", 1.0), F("C6H5", 0.3))),
        Compound("citric_acid", "C6H8O7", 1.40),
        Compound("triclosan", "C12H7Cl3O2", 9.20),
        # Common lab contaminant (plasticiser, DEHP); used for blank/contaminant faults.
        Compound("dehp_contaminant", "C24H38O4", 9.80, fwhm_min=0.25),
    ]
}
