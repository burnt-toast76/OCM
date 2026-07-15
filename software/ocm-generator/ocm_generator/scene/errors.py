# SPDX-License-Identifier: AGPL-3.0-or-later
"""Errors raised by ocm_generator.scene."""

from __future__ import annotations

from ocm_generator.errors import OcmGeneratorError


class FragmentError(OcmGeneratorError):
    """A single module's urdf_fragment is missing, unparseable, or not a
    single-root tree. Raised while loading one fragment; build_scene catches
    these and folds them into a SceneBuildError alongside everything else.
    """


class SceneBuildError(OcmGeneratorError):
    """A cell's combined scene failed to build.

    Carries every violation found (missing/malformed urdf_fragments,
    unplaceable instances, dangling mount.on attachment links) -- not just
    the first one. Matches ManifestValidationError / CellResolutionError.
    """

    def __init__(self, cell_id: str, errors: list[str]):
        self.cell_id = cell_id
        self.errors = errors
        joined = "\n".join(f"  - {e}" for e in errors)
        super().__init__(f"{cell_id}: scene failed to build:\n{joined}")
