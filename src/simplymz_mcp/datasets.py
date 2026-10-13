"""Pinned public datasets and the only network code in SimplyMZ (plan M5.T2).

Downloads are restricted to registry entries (exact URL, size and SHA-256 pinned), need
explicit confirmation, are size-capped and checksum-verified, and are written atomically
under <root>/public_data/<id>/. Nothing is bundled; see docs/data.md.
"""

from __future__ import annotations

import hashlib
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

ALLOWED_HOSTS = frozenset({"raw.githubusercontent.com", "github.com"})
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024


@dataclass(frozen=True)
class Dataset:
    id: str
    url: str
    filename: str
    sha256: str
    size_bytes: int
    licence: str
    source: str
    description: str


DATASETS: dict[str, Dataset] = {
    d.id: d
    for d in [
        Dataset(
            id="openms-ffm-1",
            url="https://raw.githubusercontent.com/OpenMS/OpenMS/"
            "07996f6cefff36557d3a908f6c9b8a43afefbfad/src/tests/topp/"
            "FeatureFinderMetabo_1_input.mzML",
            filename="FeatureFinderMetabo_1_input.mzML",
            sha256="6aa46aad3d6dff6ed32e698a6e6f9ee7f089a4ca8bc3e7860062b7a2943e048c",
            size_bytes=1140121,
            licence="BSD-3-Clause (OpenMS test data)",
            source="OpenMS repository, src/tests/topp, commit 07996f6 (2016-04-15)",
            description="Real LC-MS metabolomics excerpt: 279 centroided MS1 spectra, positive "
            "mode, RT 33.4-41.6 min.",
        ),
    ]
}


class DownloadError(Exception):
    pass


def _check_url(url: str) -> None:
    u = urlparse(url)
    if u.scheme != "https" or u.hostname not in ALLOWED_HOSTS:
        raise DownloadError(f"host not allowed: {u.hostname}")


def download(ds: Dataset, dest_dir: Path, opener: object | None = None) -> Path:
    """Fetch, size-cap, checksum and atomically place one dataset. Returns the file path."""
    _check_url(ds.url)
    if ds.size_bytes > MAX_DOWNLOAD_BYTES:
        raise DownloadError(f"{ds.id} is larger than the {MAX_DOWNLOAD_BYTES} byte cap")
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / ds.filename
    if final.exists() and hashlib.sha256(final.read_bytes()).hexdigest() == ds.sha256:
        return final
    tmp = final.with_suffix(final.suffix + ".part")
    h = hashlib.sha256()
    total = 0
    urlopen = getattr(opener, "open", None) or urllib.request.urlopen
    with urlopen(ds.url, timeout=60) as resp, open(tmp, "wb") as out:
        final_url = getattr(resp, "url", ds.url)
        _check_url(final_url)  # redirects must stay on allowed hosts
        while chunk := resp.read(1 << 16):
            total += len(chunk)
            if total > min(MAX_DOWNLOAD_BYTES, ds.size_bytes + 1024):
                out.close()
                tmp.unlink(missing_ok=True)
                raise DownloadError("download exceeded the expected size; aborted")
            h.update(chunk)
            out.write(chunk)
    if h.hexdigest() != ds.sha256:
        tmp.unlink(missing_ok=True)
        raise DownloadError(f"checksum mismatch for {ds.id}: got {h.hexdigest()[:16]}...")
    os.replace(tmp, final)
    return final
