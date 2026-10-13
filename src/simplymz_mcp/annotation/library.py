"""Spectral libraries: MSP/MGF parsing, licence tracking, precursor index (plan M4.T4).

Every spectrum keeps the licence stated in its record (``licence=``/``License:``/
``Comments`` fields); records without one are labelled "unknown" and reported as such.
Third-party spectra are never bundled (ADR 0004).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

_LIC = re.compile(r"licen[cs]e\s*[=:]\s*([^;\n]+)", re.I)


@dataclass
class LibSpectrum:
    name: str
    precursor_mz: float
    mz: np.ndarray
    intensity: np.ndarray
    formula: str = ""
    adduct: str = ""
    ion_mode: str = ""
    licence: str = "unknown"
    meta: dict[str, str] = field(default_factory=dict)


def _peaks(lines: list[str]) -> tuple[np.ndarray, np.ndarray]:
    pts = []
    for ln in lines:
        parts = re.split(r"[\s,;]+", ln.strip())
        if len(parts) >= 2:
            try:
                pts.append((float(parts[0]), float(parts[1])))
            except ValueError:
                continue
    pts.sort()
    arr = np.asarray(pts, dtype=float).reshape(-1, 2)
    return arr[:, 0], arr[:, 1]


def _licence(meta: dict[str, str]) -> str:
    for key in ("licence", "license"):
        if meta.get(key):
            return meta[key]
    for value in meta.values():
        m = _LIC.search(value)
        if m:
            return m.group(1).strip()
    return "unknown"


def parse_msp(text: str) -> list[LibSpectrum]:
    out = []
    for block in re.split(r"\n\s*\n", text.strip()):
        meta: dict[str, str] = {}
        peak_lines: list[str] = []
        in_peaks = False
        for ln in block.splitlines():
            if in_peaks:
                peak_lines.append(ln)
            elif ":" in ln:
                k, v = ln.split(":", 1)
                meta[k.strip().lower()] = v.strip()
                if k.strip().lower() == "num peaks":
                    in_peaks = True
        prec = meta.get("precursormz") or meta.get("precursor_mz") or meta.get("pepmass")
        if not meta.get("name") or not prec:
            continue
        mz, it = _peaks(peak_lines)
        out.append(
            LibSpectrum(
                name=meta["name"],
                precursor_mz=float(prec.split()[0]),
                mz=mz,
                intensity=it,
                formula=meta.get("formula", ""),
                adduct=meta.get("precursor_type", meta.get("precursortype", "")),
                ion_mode=meta.get("ion_mode", meta.get("ionmode", "")),
                licence=_licence(meta),
                meta=meta,
            )
        )
    return out


def parse_mgf(text: str) -> list[LibSpectrum]:
    out = []
    for m in re.finditer(r"BEGIN IONS(.*?)END IONS", text, re.S):
        meta: dict[str, str] = {}
        peak_lines = []
        for ln in m.group(1).strip().splitlines():
            if "=" in ln and not ln[0].isdigit():
                k, v = ln.split("=", 1)
                meta[k.strip().lower()] = v.strip()
            else:
                peak_lines.append(ln)
        if "pepmass" not in meta:
            continue
        mz, it = _peaks(peak_lines)
        out.append(
            LibSpectrum(
                name=meta.get("name", meta.get("title", "unnamed")),
                precursor_mz=float(meta["pepmass"].split()[0]),
                mz=mz,
                intensity=it,
                formula=meta.get("formula", ""),
                adduct=meta.get("adduct", ""),
                ion_mode=meta.get("ionmode", ""),
                licence=_licence(meta),
                meta=meta,
            )
        )
    return out


class Library:
    def __init__(self, name: str, spectra: list[LibSpectrum]) -> None:
        self.name = name
        self.spectra = sorted(spectra, key=lambda s: s.precursor_mz)
        self._prec = np.array([s.precursor_mz for s in self.spectra])

    def __len__(self) -> int:
        return len(self.spectra)

    def by_precursor(self, mz: float, ppm: float) -> list[LibSpectrum]:
        tol = mz * ppm * 1e-6
        a, b = (
            np.searchsorted(self._prec, mz - tol),
            np.searchsorted(self._prec, mz + tol, side="right"),
        )
        return self.spectra[a:b]

    def licences(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for s in self.spectra:
            out[s.licence] = out.get(s.licence, 0) + 1
        return out
