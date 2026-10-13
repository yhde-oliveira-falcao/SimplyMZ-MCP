"""Instructive error codes. Every error tells the client what went wrong and what to try."""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    PATH_OUTSIDE_ROOT = "PATH_OUTSIDE_ROOT"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    VENDOR_FORMAT = "VENDOR_FORMAT"
    MALFORMED_FILE = "MALFORMED_FILE"
    UNKNOWN_HANDLE = "UNKNOWN_HANDLE"
    POLARITY_MISMATCH = "POLARITY_MISMATCH"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    INTERNAL = "INTERNAL"


class SimplyMZError(Exception):
    """Raised by analytics/io code; converted to an error envelope at the tool boundary."""

    def __init__(self, code: ErrorCode, message: str, hint: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
