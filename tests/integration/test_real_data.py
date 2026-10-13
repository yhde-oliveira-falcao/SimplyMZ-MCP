"""M5.T3: the full pipeline on a real public mzML (network, slow; scheduled CI only).

Goal: no crashes, valid envelopes, every output within its token budget on real data.
The QC step uses three copies of one file, so it tests the machinery, not QC validity.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest
from mcp import Client

from simplymz_mcp.config import Config
from simplymz_mcp.core.budget import estimate_tokens
from simplymz_mcp.core.envelope import is_valid_envelope
from simplymz_mcp.server import build_server

pytestmark = [pytest.mark.network, pytest.mark.slow]


@pytest.mark.anyio
async def test_pipeline_on_openms_lcms_excerpt(tmp_path: Path) -> None:
    server, registry = build_server(Config(root=tmp_path))

    async def call(tool: str, **args: object) -> dict:
        env = (await client.call_tool(tool, args)).structured_content
        assert is_valid_envelope(env), (tool, env)
        assert env["status"] != "error", (tool, env)
        assert estimate_tokens(env) <= registry.get(tool).budget_tokens or env["truncated"]
        return env

    async with Client(server) as client:
        got = await call("fetch_public_dataset", dataset_id="openms-ffm-1", confirm=True)
        path = got["data"]["path"]
        run = (await call("load_run", path=path))["data"]["run_handle"]
        card = await call("run_card", run_handle=run)
        assert card["data"]["n_spectra"] == 279

        tic = await call("get_chromatogram", run_handle=run, kind="TIC")
        bpc = await call("get_chromatogram", run_handle=run, kind="BPC")
        top_rt = max(bpc["data"]["peaks"], key=lambda p: p["height_counts"])["rt_min"]
        await call("integrate_peak", chrom_handle=tic["data"]["chrom_handle"], apex_rt_min=top_rt)

        job = (await call("detect_features", run_handle=run))["data"]["job_handle"]
        deadline = time.monotonic() + 300
        while True:
            st = await call("job_status", job_handle=job)
            if st["data"]["state"] not in ("queued", "running"):
                break
            assert time.monotonic() < deadline, "feature detection did not finish"
            time.sleep(1)
        assert st["data"]["state"] == "done", st
        result = st["data"]["result"]["data"]
        assert result["n_features"] >= 10, result["n_features"]
        first = await call("get_feature", ftab_handle=result["ftab_handle"], feature_id="F00001")
        await call(
            "propose_formulas",
            mz=first["data"]["mz"],
            run_handle=run,
            rt_min=first["data"]["rt_min"],
        )

        base = tmp_path / Path(path).parent
        for name in ("qc_1", "qc_2", "qc_3"):
            shutil.copy(tmp_path / path, base / f"{name}.mzML")
        (base / "sheet.csv").write_text(
            "file,sample_type,group,injection_order\n"
            "qc_1.mzML,qc,,1\nqc_2.mzML,qc,,2\nqc_3.mzML,qc,,3\n"
        )
        batch = await call("load_batch", sample_sheet=str(Path(path).parent / "sheet.csv"))
        qc = await call("qc_batch", batch_handle=batch["data"]["batch_handle"])
        report = await call(
            "export_report",
            title="Real data smoke test",
            filename="real_smoke",
            sections=[
                {
                    "heading": "Run",
                    "body": f"{{{card['provenance_id']}:data.n_spectra}} spectra; QC "
                    f"{{{qc['provenance_id']}:data.overall}}.",
                }
            ],
        )
        assert report["data"]["slots_filled"] == 2


OPENMS = "https://raw.githubusercontent.com/OpenMS/OpenMS/07996f6cefff36557d3a908f6c9b8a43afefbfad"
OPENMS_OUT = f"{OPENMS}/src/tests/topp/FeatureFinderMetabo_1_output.featureXML"


def test_feature_recall_against_openms_reference(tmp_path: Path) -> None:
    """Real-data benchmark: OpenMS FeatureFinderMetabo's own expected output for this file
    (446 features) is the reference. Floor recorded 2026-10-05 with masstrace-lite defaults:
    5/10 of OpenMS's most intense features (it was 2/10 before gap tolerance)."""
    import re
    import urllib.request

    from simplymz_mcp.analytics.features import DetectorParams, detect_features
    from simplymz_mcp.datasets import DATASETS, download
    from simplymz_mcp.io.mzml import read_mzml

    run = read_mzml(download(DATASETS["openms-ffm-1"], tmp_path))
    xml = urllib.request.urlopen(OPENMS_OUT, timeout=60).read().decode()
    ref = []
    for blk in re.findall(r"<feature id.*?</feature>", xml, re.S):
        pos = dict(re.findall(r'<position dim="(\d)">([\d.eE+-]+)</position>', blk)[:2])
        inten = float(re.search(r"<intensity>([\d.eE+-]+)</intensity>", blk).group(1))
        ref.append((inten, float(pos["0"]) / 60, float(pos["1"])))
    ref.sort(reverse=True)
    assert len(ref) == 446
    ours = detect_features(run, DetectorParams())["features"]
    hit = sum(
        any(abs(f["mz"] - mz) / mz * 1e6 <= 10 and abs(f["rt_min"] - rt) <= 0.2 for f in ours)
        for _, rt, mz in ref[:10]
    )
    assert hit >= 5, hit
