"""Write synthetic scans to mzML (psims) and synthetic libraries to MSP."""

from __future__ import annotations

import gzip
import hashlib
import io
from pathlib import Path
from typing import Any

import numpy as np

from simplymz_mcp.synth.compounds import COMPOUNDS
from simplymz_mcp.synth.model import Scan

SOFTWARE_ID = "simplymz_synth"


def mzml_bytes(scans: list[Scan], run_id: str, polarity: str) -> bytes:
    try:
        from psims.mzml.writer import MzMLWriter
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("psims is required: pip install 'simplymz-mcp[fixtures]'") from exc

    pol = "positive scan" if polarity == "positive" else "negative scan"
    buf = io.BytesIO()
    with MzMLWriter(buf, close=False) as out:
        out.controlled_vocabularies()
        out.file_description(["MS1 spectrum", "MSn spectrum"])
        out.software_list(
            [{"id": SOFTWARE_ID, "version": "1", "params": ["custom unreleased software tool"]}]
        )
        out.instrument_configuration_list(
            [{"id": "IC1", "component_list": [], "params": ["instrument model"]}]
        )
        out.data_processing_list(
            [
                {
                    "id": "dp1",
                    "processing_methods": [
                        {
                            "order": 0,
                            "software_reference": SOFTWARE_ID,
                            "params": ["Conversion to mzML"],
                        }
                    ],
                }
            ]
        )
        with (
            out.run(id=run_id, instrument_configuration="IC1"),
            out.spectrum_list(count=len(scans)),
        ):
            for s in scans:
                tic = float(np.sum(s.intensity, dtype=np.float64))
                params: list[Any] = [{"ms level": s.ms_level}, {"total ion current": tic}]
                if s.intensity.size:
                    j = int(np.argmax(s.intensity))
                    params += [
                        {"base peak m/z": float(s.mz[j])},
                        {
                            "name": "base peak intensity",
                            "value": float(s.intensity[j]),
                            "unit_name": "number of detector counts",
                        },
                    ]
                kwargs: dict[str, Any] = {}
                if s.ms_level == 2:
                    kwargs["precursor_information"] = {
                        "mz": s.precursor_mz,
                        "charge": s.precursor_charge,
                        "scan_id": s.precursor_scan_id,
                        "activation": ["collision-induced dissociation", {"collision energy": 20}],
                    }
                out.write_spectrum(
                    s.mz.astype(np.float64),
                    s.intensity.astype(np.float32),
                    id=s.native_id,
                    polarity=pol,
                    centroided=True,
                    scan_start_time=s.rt_min,
                    params=params,
                    encoding={"m/z array": np.float64, "intensity array": np.float32},
                    **kwargs,
                )
    return buf.getvalue()


def write_mzml(scans: list[Scan], path: Path, run_id: str, polarity: str) -> str:
    """Write ``.mzML`` or ``.mzML.gz`` (gzip mtime fixed to 0). Returns file SHA-256."""
    data = mzml_bytes(scans, run_id, polarity)
    if path.name.lower().endswith(".gz"):
        gz = io.BytesIO()
        with gzip.GzipFile(filename="", mode="wb", fileobj=gz, mtime=0) as fh:
            fh.write(data)
        data = gz.getvalue()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def msp_text(entries: list[str], licence: str = "CC0-1.0 (synthetic)") -> str:
    """Synthetic [M+H]+ MS/MS library for the given compound names."""
    blocks = []
    for name in entries:
        c = COMPOUNDS[name]
        if not c.fragments:
            raise ValueError(f"{name} has no fragments")
        peaks = sorted((f.mz, f.rel_intensity * 999) for f in c.fragments)
        lines = [
            f"Name: {name}",
            f"Formula: {c.formula}",
            f"PrecursorMZ: {c.ion_mz('[M+H]+'):.6f}",
            "Precursor_type: [M+H]+",
            "Ion_mode: Positive",
            f"Comments: licence={licence}; source=simplymz-mcp synthetic fixtures",
            f"Num Peaks: {len(peaks)}",
            *[f"{mz:.6f} {inten:.1f}" for mz, inten in peaks],
        ]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"
