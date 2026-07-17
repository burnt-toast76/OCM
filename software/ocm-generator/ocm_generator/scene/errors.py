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


class CollisionCheckUnavailable(OcmGeneratorError):
    """tesseract-robotics isn't installed, or no working discrete contact
    manager backend could be loaded from it. Building a Scene never raises
    this -- only ocm_generator.scene.collision.check_collisions does,
    which is reached only via `ocm scene --collision`.
    """


class CollisionCheckError(OcmGeneratorError):
    """The collision check itself couldn't complete for a reason other than
    "Tesseract isn't available" -- e.g. Tesseract rejected the composed
    URDF, which build_scene's own validation should already have ruled out.
    """
