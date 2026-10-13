from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from mcp import Client

from simplymz_mcp.config import Config
from simplymz_mcp.core.budget import estimate_tokens
from simplymz_mcp.core.envelope import is_valid_envelope
from simplymz_mcp.server import build_server
from tests.conftest import FIXTURES

MZML = sorted(p for p in FIXTURES.rglob("*") if p.name.endswith((".mzML", ".mzML.gz")))


@pytest.fixture(scope="module")
def root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    r = tmp_path_factory.mktemp("data")
    for p in MZML:
        dest = r / p.relative_to(FIXTURES)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(p, dest)
    return r


async def _call(client: Client, tool: str, **args: object) -> dict:
    res = await client.call_tool(tool, args)
    env = res.structured_content
    assert is_valid_envelope(env), env
    return env


@pytest.mark.anyio
async def test_run_cards_for_all_fixtures(root: Path) -> None:
    server, registry = build_server(Config(root=root))
    budget = registry.get("run_card").budget_tokens
    async with Client(server) as client:
        for p in MZML:
            rel = str(p.relative_to(FIXTURES))
            loaded = await _call(client, "load_run", path=rel)
            assert loaded["status"] == "ok"
            card = await _call(client, "run_card", run_handle=loaded["data"]["run_handle"])
            assert estimate_tokens(card) <= budget and not card["truncated"]
            kinds = [a["type"] for a in card["data"]["anomalies"]]
            if p.name.startswith("dropout"):
                assert kinds == ["empty_scans"]
                assert card["data"]["anomalies"][0]["n_scans"] == 12
            else:
                assert kinds == [], (p.name, kinds)
            assert len(card["data"]["tic_trace"]["rt_min"]) <= 40


@pytest.mark.anyio
async def test_reload_reuses_handle_and_release_invalidates(root: Path) -> None:
    server, _ = build_server(Config(root=root))
    async with Client(server) as client:
        a = await _call(client, "load_run", path="runs/clean_neg.mzML.gz")
        b = await _call(client, "load_run", path="runs/clean_neg.mzML.gz")
        h = a["data"]["run_handle"]
        assert b["data"]["run_handle"] == h and b["data"]["reused_handle"]
        rel = await _call(client, "release_handle", handle=h)
        assert rel["status"] == "ok"
        gone = await _call(client, "run_card", run_handle=h)
        assert gone["error"]["code"] == "UNKNOWN_HANDLE"
        c = await _call(client, "load_run", path="runs/clean_neg.mzML.gz")
        assert c["data"]["run_handle"] != h and c["data"]["cache_hit"]


@pytest.mark.anyio
async def test_errors_are_instructive_envelopes(root: Path) -> None:
    server, _ = build_server(Config(root=root))
    async with Client(server) as client:
        vendor = await _call(client, "load_run", path="sample.raw")
        assert vendor["error"]["code"] == "VENDOR_FORMAT" and "msconvert" in vendor["error"]["hint"]
        bad = await _call(client, "run_card", run_handle="batch:01ARZ3NDEKTSV4RRFFQ69G5FAV")
        assert bad["error"]["code"] == "INVALID_ARGUMENT"
        out = await _call(client, "load_run", path="../../etc/passwd")
        assert out["error"]["code"] == "PATH_OUTSIDE_ROOT"


@pytest.mark.anyio
async def test_run_card_resource(root: Path) -> None:
    server, _ = build_server(Config(root=root))
    async with Client(server) as client:
        loaded = await _call(client, "load_run", path="runs/clean_pos.mzML")
        run_id = loaded["data"]["run_handle"].split(":", 1)[1]
        templates = await client.list_resource_templates()
        assert any(
            t.uri_template == "simplymz://run/{run_id}/card" for t in templates.resource_templates
        )
        res = await client.read_resource(f"simplymz://run/{run_id}/card")
    env = json.loads(res.contents[0].text)
    assert env["status"] == "ok" and env["data"]["file"] == "runs/clean_pos.mzML"
