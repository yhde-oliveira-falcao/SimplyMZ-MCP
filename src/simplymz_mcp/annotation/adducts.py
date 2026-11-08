"""Adduct table and neutral-mass arithmetic (plan M4.T1).

Masses come from pyteomics' NIST table (the code under test); tests check them against
the independent table in simplymz_mcp.synth.elements.
"""

from __future__ import annotations

from dataclasses import dataclass

from pyteomics import mass as pmass

from simplymz_mcp.core.errors import ErrorCode, SimplyMZError

ELECTRON = 0.000548579909


def _m(formula: str) -> float:
    return float(pmass.calculate_mass(formula=formula))


@dataclass(frozen=True)
class Adduct:
    name: str
    charge: int  # signed
    multimer: int  # M count (1 for [M+H]+, 2 for [2M+H]+)
    delta: float  # mass added to multimer*M before dividing by |charge| (electrons included)

    def ion_mz(self, neutral: float) -> float:
        return (self.multimer * neutral + self.delta) / abs(self.charge)

    def neutral(self, mz: float) -> float:
        return (mz * abs(self.charge) - self.delta) / self.multimer


def _a(name: str, charge: int, add: str = "", lose: str = "", multimer: int = 1) -> Adduct:
    delta = (_m(add) if add else 0.0) - (_m(lose) if lose else 0.0) - charge * ELECTRON
    return Adduct(name, charge, multimer, delta)


ADDUCTS: dict[str, Adduct] = {
    a.name: a
    for a in [
        _a("[M+H]+", 1, add="H"),
        _a("[M+Na]+", 1, add="Na"),
        _a("[M+K]+", 1, add="K"),
        _a("[M+NH4]+", 1, add="NH4"),
        _a("[M+H-H2O]+", 1, add="H", lose="H2O"),
        _a("[M+2H]2+", 2, add="H2"),
        _a("[2M+H]+", 1, add="H", multimer=2),
        _a("[M-H]-", -1, lose="H"),
        _a("[M+Cl]-", -1, add="Cl"),
        _a("[M+HCOO]-", -1, add="CHO2"),
        _a("[M+CH3COO]-", -1, add="C2H3O2"),
        _a("[M-H-H2O]-", -1, lose="H3O"),
        _a("[M-2H]2-", -2, lose="H2"),
    ]
}


def normalize_adduct(name: str | None) -> str | None:
    """Map common library spellings to a supported adduct name, else None. Pure.

    Accepts the canonical form ("[M+H]+") and frequent MSP/MGF variants: no brackets
    ("M+H"), no charge ("[M+H]") or an explicit unit charge ("[M+H]1+"). A charge is
    inferred only when exactly one supported adduct matches. Unknown names return None.
    """
    s = (name or "").strip().replace(" ", "")
    if not s:
        return None
    if s in ADDUCTS:
        return s
    if not s.startswith("["):
        s = f"[{s}]" if "]" not in s else f"[{s}"
    core, _, charge = s.partition("]")
    core += "]"
    charge = {"1+": "+", "1-": "-"}.get(charge, charge)
    if charge:
        return core + charge if core + charge in ADDUCTS else None
    charges = {"+", "-", "2+", "2-"}
    matches = [n for n in ADDUCTS if n.startswith(core) and n[len(core) :] in charges]
    return matches[0] if len(matches) == 1 else None


def valid_for(polarity: str) -> list[str]:
    sign = 1 if polarity == "positive" else -1
    return [n for n, a in ADDUCTS.items() if a.charge * sign > 0]


def get_adduct(name: str, polarity: str | None = None) -> Adduct:
    if name not in ADDUCTS:
        raise SimplyMZError(
            ErrorCode.INVALID_ARGUMENT,
            f"Unknown adduct {name!r}.",
            f"Supported: {', '.join(ADDUCTS)}.",
        )
    a = ADDUCTS[name]
    ion_pol = "positive" if a.charge > 0 else "negative"
    if polarity in ("positive", "negative") and ion_pol != polarity:
        raise SimplyMZError(
            ErrorCode.POLARITY_MISMATCH,
            f"Run is {polarity} mode; {name} is a {ion_pol} ion.",
            f"Use one of: {', '.join(valid_for(polarity))}.",
        )
    return a
