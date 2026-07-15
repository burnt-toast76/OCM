# SPDX-License-Identifier: AGPL-3.0-or-later
"""Errors raised by ocm_resolve."""

from __future__ import annotations


class OcmResolveError(Exception):
    """Base class for all ocm_resolve errors."""


class CellResolutionError(OcmResolveError):
    """A cell failed to resolve against a module search path.

    Carries every violation found (missing modules, unknown ops, out-of-bounds
    params, dangling mount.on references) -- not just the first one.
    """

    def __init__(self, cell_id: str, errors: list[str]):
        self.cell_id = cell_id
        self.errors = errors
        joined = "\n".join(f"  - {e}" for e in errors)
        super().__init__(f"{cell_id}: cell failed to resolve:\n{joined}")
