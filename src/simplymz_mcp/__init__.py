"""SimplyMZ: an MCP server for evidence-backed LC-MS / GC-MS run analysis."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("simplymz-mcp")
except PackageNotFoundError:  # pragma: no cover - running from a source tree without install
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
