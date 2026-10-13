from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


MULTIPLES = (0.5, 1.0, 2.0, 4.0)


@pytest.fixture(scope="session")
def fault_matrix(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """QC results for the clean batch and every fault x multiple, via the qc_batch tool.

    Returns {"clean": data, (fault, multiple): {"case": FaultCase, "data": data}}."""
    import shutil

    import anyio
    from mcp import Client

    from simplymz_mcp.analytics.qc import load_thresholds
    from simplymz_mcp.config import Config
    from simplymz_mcp.server import build_server
    from simplymz_mcp.synth.faults import FAULT_CASES, make_case
    from simplymz_mcp.synth.model import render
    from simplymz_mcp.synth.writer import write_mzml

    root = tmp_path_factory.mktemp("faults")
    shutil.copytree(FIXTURES / "batch_qc", root / "batch_qc")
    sheet = (FIXTURES / "batch_qc" / "sample_sheet.csv").read_text().splitlines()
    th = load_thresholds()
    cases = {}
    for fault, (metric, run_name, _) in FAULT_CASES.items():
        for k in MULTIPLES:
            case = make_case(fault, k, th[metric]["fail"])
            folder = root / f"{fault}_{k:g}x"
            folder.mkdir()
            scans, _ = render(case.spec)
            write_mzml(scans, folder / f"{run_name}.mzML.gz", case.spec.name, "positive")
            rows = [sheet[0]] + [
                line if line.startswith(run_name) else f"../batch_qc/{line}" for line in sheet[1:]
            ]
            (folder / "sheet.csv").write_text("\n".join(rows) + "\n")
            cases[(fault, k)] = case

    async def run_all() -> dict:
        server, _ = build_server(Config(root=root, cache_dir=root / ".cache"))
        out: dict = {}
        async with Client(server) as client:

            async def qc(sheet_rel: str) -> dict:
                b = await client.call_tool("load_batch", {"sample_sheet": sheet_rel})
                h = b.structured_content["data"]["batch_handle"]
                r = await client.call_tool("qc_batch", {"batch_handle": h})
                return r.structured_content

            out["clean"] = await qc("batch_qc/sample_sheet.csv")
            for key, case in cases.items():
                out[key] = {"case": case, "env": await qc(f"{key[0]}_{key[1]:g}x/sheet.csv")}
        return out

    return anyio.run(run_all)
