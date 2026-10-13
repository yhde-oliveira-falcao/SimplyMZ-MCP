"""Path security for every file the server opens (plan M1.T1).

Rules, checked in this order:
1. Vendor formats are refused with msconvert guidance (even if the path is outside the root:
   the user learns *why* before anything else).
2. The path, after resolving ``..`` and symlinks, must lie inside the data root.
3. The file must exist, be a regular file, have an allowed extension and be under the
   size limit.
"""

from __future__ import annotations

from pathlib import Path

from simplymz_mcp.config import Limits
from simplymz_mcp.core.errors import ErrorCode, SimplyMZError

VENDOR_EXTENSIONS: dict[str, str] = {
    ".raw": "Thermo .raw",
    ".d": "Agilent/Bruker .d",
    ".wiff": "SCIEX .wiff",
    ".wiff2": "SCIEX .wiff2",
    ".lcd": "Shimadzu .lcd",
}
MSCONVERT_HINT = (
    "Convert it to mzML with ProteoWizard msconvert, e.g. "
    '`msconvert <file> --mzML --filter "peakPicking vendor msLevel=1-"`, '
    "then load the .mzML file."
)


def compound_suffix(path: Path) -> str:
    name = path.name.lower()
    if name.endswith(".gz"):
        stem_suffix = Path(name[:-3]).suffix
        return f"{stem_suffix}.gz" if stem_suffix else ".gz"
    return path.suffix.lower()


def resolve_data_path(root: Path, user_path: str, limits: Limits) -> Path:
    """Return the resolved, validated path or raise an instructive SimplyMZError."""
    if not user_path or "\x00" in user_path:
        raise SimplyMZError(
            ErrorCode.INVALID_ARGUMENT, "Empty or invalid path.", "Give a path under the data root."
        )
    raw = Path(user_path)
    suffix = raw.suffix.lower().rstrip("/\\")
    if suffix in VENDOR_EXTENSIONS:
        raise SimplyMZError(
            ErrorCode.VENDOR_FORMAT,
            f"{VENDOR_EXTENSIONS[suffix]} files cannot be read directly.",
            MSCONVERT_HINT,
        )
    root = root.resolve()
    candidate = raw if raw.is_absolute() else root / raw
    resolved = candidate.resolve()  # follows symlinks and collapses ".."
    if not resolved.is_relative_to(root):
        raise SimplyMZError(
            ErrorCode.PATH_OUTSIDE_ROOT,
            "That path resolves outside the allowed data root.",
            f"Only files under {root} can be read. Copy the file there, or restart the server "
            "with a different --root.",
        )
    if not resolved.exists():
        raise SimplyMZError(
            ErrorCode.FILE_NOT_FOUND,
            f"No file at {_rel(resolved, root)}.",
            "Check the spelling; paths are relative to the data root.",
        )
    if not resolved.is_file():
        raise SimplyMZError(
            ErrorCode.INVALID_ARGUMENT,
            f"{_rel(resolved, root)} is not a file.",
            "Give a file path.",
        )
    ext = compound_suffix(resolved)
    if ext not in limits.allowed_extensions:
        raise SimplyMZError(
            ErrorCode.UNSUPPORTED_FORMAT,
            f"Files ending in {ext or '(no extension)'} are not supported.",
            f"Supported: {', '.join(limits.allowed_extensions)}.",
        )
    size_mb = resolved.stat().st_size / 1024 / 1024
    if size_mb > limits.max_file_mb:
        raise SimplyMZError(
            ErrorCode.FILE_TOO_LARGE,
            f"File is {size_mb:.0f} MB; the limit is {limits.max_file_mb} MB.",
            "Raise max_file_mb in the server config, or split the run.",
        )
    return resolved


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:  # pragma: no cover - only called for paths inside root
        return path.name
