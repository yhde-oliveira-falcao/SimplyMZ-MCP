"""fetch_public_dataset (plan M5.T2): the only tool that touches the network."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from simplymz_mcp import datasets
from simplymz_mcp.core import envelope
from simplymz_mcp.core.errors import ErrorCode, SimplyMZError
from simplymz_mcp.core.registry import Registry, ToolSpec

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from simplymz_mcp.server import App


def register(server: MCPServer, registry: Registry, app: App) -> dict[str, Any]:
    def fetch_public_dataset(dataset_id: str, confirm: bool = False) -> dict[str, Any]:
        """Download a pinned public dataset into <root>/public_data/<id>/ (network!).

        Only registry datasets are allowed (exact URL, size and SHA-256 pinned). Call once
        with confirm=false to see size and licence, then ask the user, then confirm=true."""
        ds = datasets.DATASETS.get(dataset_id)
        if ds is None:
            raise SimplyMZError(
                ErrorCode.INVALID_ARGUMENT,
                f"Unknown dataset {dataset_id!r}.",
                f"Available: {', '.join(sorted(datasets.DATASETS))}.",
            )
        info = {
            "dataset_id": ds.id,
            "filename": ds.filename,
            "size_mb": round(ds.size_bytes / 1e6, 2),
            "licence": ds.licence,
            "source": ds.source,
            "description": ds.description,
        }
        if not confirm:
            return envelope.insufficient(
                f"Not downloaded: {ds.id} is {info['size_mb']} MB ({ds.licence}). Ask the user, "
                "then call again with confirm=true.",
                info,
                next_steps=[f"fetch_public_dataset(dataset_id='{ds.id}', confirm=true)"],
            )
        dest = app.config.root.resolve() / "public_data" / ds.id
        try:
            path = datasets.download(ds, dest)
        except (datasets.DownloadError, OSError) as exc:
            raise SimplyMZError(
                ErrorCode.INTERNAL,
                f"Download failed: {exc}.",
                "Check the network connection and try again; nothing partial was kept.",
            ) from exc
        rel = path.relative_to(app.config.root.resolve()).as_posix()
        env = envelope.ok(
            f"Downloaded {ds.id} to {rel} (checksum verified).",
            {**info, "path": rel, "sha256": ds.sha256},
            limits=[f"Licence: {ds.licence}. Cite the source when publishing."],
            next_steps=[f"load_run(path='{rel}')"],
        )
        env["_provenance"] = {"input_hashes": [ds.sha256], "parents": []}
        return env

    spec = ToolSpec(
        "fetch_public_dataset",
        fetch_public_dataset.__doc__ or "",
        fetch_public_dataset,
        600,
        {"dataset_id": "openms-ffm-1", "confirm": False},
    )
    guarded = registry.register(spec)
    server.add_tool(guarded, name=spec.name, description=spec.description)
    return {"fetch_public_dataset": guarded}
