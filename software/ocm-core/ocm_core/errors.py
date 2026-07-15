# SPDX-License-Identifier: AGPL-3.0-or-later
"""Errors raised by ocm_core."""

from __future__ import annotations

from pathlib import Path


class OcmCoreError(Exception):
    """Base class for all ocm_core errors."""


class ManifestValidationError(OcmCoreError):
    """A module manifest failed validation against ocm-module-1.0.schema.json."""

    def __init__(self, path: Path, errors: list[str]):
        self.path = path
        self.errors = errors
        joined = "\n".join(f"  - {e}" for e in errors)
        super().__init__(f"{path}: manifest failed schema validation:\n{joined}")


class CellLoadError(OcmCoreError):
    """A cell composition file is structurally invalid.

    There is no published JSON Schema for the cell shape yet, so these are
    structural checks (required keys, unique instance names, parseable
    module refs) rather than full schema validation.
    """

    def __init__(self, path: Path, errors: list[str]):
        self.path = path
        self.errors = errors
        joined = "\n".join(f"  - {e}" for e in errors)
        super().__init__(f"{path}: cell file is invalid:\n{joined}")
