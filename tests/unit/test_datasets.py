"""M5.T2: dataset downloads with a fake HTTP opener (no network)."""

from __future__ import annotations

import hashlib
import io
from dataclasses import replace
from pathlib import Path

import pytest

from simplymz_mcp import datasets
from simplymz_mcp.datasets import DATASETS, DownloadError, download

PAYLOAD = b"<mzML>tiny</mzML>" * 100
DS = replace(
    DATASETS["openms-ffm-1"], sha256=hashlib.sha256(PAYLOAD).hexdigest(), size_bytes=len(PAYLOAD)
)


class FakeResp(io.BytesIO):
    def __init__(self, data: bytes, url: str) -> None:
        super().__init__(data)
        self.url = url


class FakeOpener:
    def __init__(self, data: bytes = PAYLOAD, final_url: str | None = None) -> None:
        self.data, self.final_url, self.calls = data, final_url, 0

    def open(self, url: str, timeout: float = 0) -> FakeResp:
        self.calls += 1
        return FakeResp(self.data, self.final_url or url)


def test_download_verifies_and_is_idempotent(tmp_path: Path) -> None:
    op = FakeOpener()
    p = download(DS, tmp_path, op)
    assert p.read_bytes() == PAYLOAD and op.calls == 1
    download(DS, tmp_path, op)
    assert op.calls == 1  # already present with the right checksum
    assert not list(tmp_path.glob("*.part"))


def test_checksum_mismatch_keeps_nothing(tmp_path: Path) -> None:
    with pytest.raises(DownloadError, match="checksum"):
        download(DS, tmp_path, FakeOpener(PAYLOAD[:-1] + b"X"))
    assert list(tmp_path.iterdir()) == []


def test_oversize_aborts(tmp_path: Path) -> None:
    with pytest.raises(DownloadError, match="size"):
        download(DS, tmp_path, FakeOpener(PAYLOAD * 3))
    assert list(tmp_path.iterdir()) == []


def test_hosts_are_allowlisted(tmp_path: Path) -> None:
    with pytest.raises(DownloadError, match="host"):
        download(replace(DS, url="https://evil.example/x.mzML"), tmp_path, FakeOpener())
    with pytest.raises(DownloadError, match="host"):
        download(DS, tmp_path, FakeOpener(final_url="https://evil.example/x"))
    with pytest.raises(DownloadError, match="host"):
        download(replace(DS, url="http://raw.githubusercontent.com/x"), tmp_path, FakeOpener())


def test_registry_entries_are_pinned() -> None:
    for ds in DATASETS.values():
        assert len(ds.sha256) == 64 and ds.licence and ds.size_bytes > 0
        assert "/develop/" not in ds.url and "/master/" not in ds.url and "/main/" not in ds.url
        assert ds.size_bytes <= datasets.MAX_DOWNLOAD_BYTES


@pytest.mark.network
def test_real_download_and_load(tmp_path: Path) -> None:
    from simplymz_mcp.io.mzml import read_mzml

    p = download(DATASETS["openms-ffm-1"], tmp_path)
    run = read_mzml(p)
    assert run.meta["n_spectra"] == 279 and run.meta["polarity"] == "positive"
