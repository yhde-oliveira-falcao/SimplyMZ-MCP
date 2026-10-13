from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from simplymz_mcp.config import Limits
from simplymz_mcp.core.errors import ErrorCode, SimplyMZError
from simplymz_mcp.io.security import compound_suffix, resolve_data_path

LIM = Limits()


def _code(root: Path, p: str, limits: Limits = LIM) -> ErrorCode:
    with pytest.raises(SimplyMZError) as ei:
        resolve_data_path(root, p, limits)
    assert ei.value.hint  # every refusal is instructive
    return ei.value.code


@pytest.fixture
def root(tmp_path: Path) -> Path:
    r = tmp_path / "data"
    (r / "sub").mkdir(parents=True)
    (r / "sub" / "a.mzML").write_text("<mzML/>")
    (r / "b.mzML.gz").write_bytes(b"\x1f\x8b")
    (tmp_path / "secret.mzML").write_text("outside")
    return r


def test_valid_relative_and_absolute_paths(root: Path) -> None:
    assert resolve_data_path(root, "sub/a.mzML", LIM) == (root / "sub" / "a.mzML").resolve()
    assert resolve_data_path(root, str(root / "b.mzML.gz"), LIM).name == "b.mzML.gz"


@pytest.mark.parametrize("p", ["../secret.mzML", "sub/../../secret.mzML"])
def test_parent_traversal_blocked(root: Path, p: str) -> None:
    assert _code(root, p) == ErrorCode.PATH_OUTSIDE_ROOT


def test_absolute_path_outside_root_blocked(root: Path) -> None:
    assert _code(root, str(root.parent / "secret.mzML")) == ErrorCode.PATH_OUTSIDE_ROOT


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need admin rights on Windows")
def test_symlink_escape_blocked(root: Path) -> None:
    os.symlink(root.parent / "secret.mzML", root / "link.mzML")
    assert _code(root, "link.mzML") == ErrorCode.PATH_OUTSIDE_ROOT
    os.symlink(root.parent, root / "dirlink")
    assert _code(root, "dirlink/secret.mzML") == ErrorCode.PATH_OUTSIDE_ROOT


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need admin rights on Windows")
def test_symlink_inside_root_allowed(root: Path) -> None:
    os.symlink(root / "sub" / "a.mzML", root / "inner.mzML")
    assert resolve_data_path(root, "inner.mzML", LIM) == (root / "sub" / "a.mzML").resolve()


@pytest.mark.parametrize(
    "p", ["run.raw", "run.RAW", "run.d", "run.d/", "x.wiff", "x.wiff2", "x.lcd"]
)
def test_vendor_formats_refused_with_msconvert(root: Path, p: str) -> None:
    with pytest.raises(SimplyMZError) as ei:
        resolve_data_path(root, p, LIM)
    assert ei.value.code == ErrorCode.VENDOR_FORMAT
    assert "msconvert" in ei.value.hint


def test_missing_and_directory_and_extension(root: Path) -> None:
    assert _code(root, "nope.mzML") == ErrorCode.FILE_NOT_FOUND
    assert _code(root, "sub") == ErrorCode.INVALID_ARGUMENT
    (root / "notes.txt").write_text("x")
    assert _code(root, "notes.txt") == ErrorCode.UNSUPPORTED_FORMAT


@pytest.mark.parametrize("bad", ["", "a\x00b.mzML"])
def test_empty_or_nul_path(root: Path, bad: str) -> None:
    assert _code(root, bad) == ErrorCode.INVALID_ARGUMENT


def test_oversize_refused(root: Path) -> None:
    big = root / "big.mzML"
    big.write_bytes(b"0" * (2 * 1024 * 1024))
    assert _code(root, "big.mzML", Limits(max_file_mb=1)) == ErrorCode.FILE_TOO_LARGE


@pytest.mark.parametrize(
    ("name", "ext"),
    [("a.mzML", ".mzml"), ("a.mzML.gz", ".mzml.gz"), ("a.gz", ".gz"), ("a", "")],
)
def test_compound_suffix(name: str, ext: str) -> None:
    assert compound_suffix(Path(name)) == ext
