# SPDX-License-Identifier: AGPL-3.0-or-later
"""ocm_resolve -- resolve a Cell against a module search path into a ResolvedCell.

Second stage of the generator pipeline: ocm_core loads and validates one
manifest at a time; ocm_resolve cross-references a cell's module instances,
mount chain, and plan against those manifests. No geometry, collision, or
Tesseract here -- that's ocm-generator, once a cell resolves cleanly.
"""

from .errors import CellResolutionError, OcmResolveError
from .resolve import ResolvedCarrier, ResolvedCell, ResolvedModuleInstance, resolve_cell, resolve_module
from .search import SearchPath, find_component, find_module

__all__ = [
    "CellResolutionError",
    "OcmResolveError",
    "ResolvedCarrier",
    "ResolvedCell",
    "ResolvedModuleInstance",
    "SearchPath",
    "find_component",
    "find_module",
    "resolve_cell",
    "resolve_module",
]
