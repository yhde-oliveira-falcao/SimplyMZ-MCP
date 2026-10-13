"""Oracle compound set for formula/isotope tests (M4). Masses come from the independent
element table in simplymz_mcp.synth.elements, never from the annotation code."""

from __future__ import annotations

from simplymz_mcp.synth.compounds import COMPOUNDS

EXTRA = {
    "glucose": "C6H12O6",
    "serine": "C3H7NO3",
    "glutamic_acid": "C5H9NO4",
    "citrulline": "C6H13N3O3",
    "histidine": "C6H9N3O2",
    "methionine": "C5H11NO2S",
    "cysteine": "C3H7NO2S",
    "amp": "C10H14N5O7P",
    "phosphoserine": "C3H8NO6P",
    "chlorpromazine": "C17H19ClN2S",
    "diclofenac": "C14H11Cl2NO2",
    "atrazine": "C8H14ClN5",
    "ibuprofen": "C13H18O2",
    "paracetamol": "C8H9NO2",
    "nicotine": "C10H14N2",
    "uracil": "C4H4N2O2",
    "thymine": "C5H6N2O2",
    "cytosine": "C4H5N3O",
    "glycerophosphocholine": "C8H20NO6P",
}
ORACLE: dict[str, str] = {**{n: c.formula for n, c in COMPOUNDS.items()}, **EXTRA}


def elements_for(formula: str) -> str:
    return "CHNOPSCl" if "Cl" in formula else "CHNOPS"
