# SPDX-License-Identifier: AGPL-3.0-or-later
"""ocm_generator.scene -- compose a ResolvedCell into a single combined URDF
(a Scene), independent of Tesseract. Building a real Tesseract Environment
or running a discrete collision check from one is .collision's job,
imported here too but guarded internally (see collision.py) so importing
this package never requires the `tesseract` extra -- only calling
check_collisions() does.
"""

from .build import Scene, SceneInstance, build_scene
from .collision import Contact, CollisionCheckResult, check_collisions
from .containment import base_footprint_mm, check_workspace_containment
from .errors import CollisionCheckError, CollisionCheckUnavailable, FragmentError, SceneBuildError
from .kinematics import GeometryPrimitive, compute_world_poses, list_collision_primitives, world_aabb
from .transforms import Pose
from .viewer import render_html, scene_to_payload

__all__ = [
    "CollisionCheckError",
    "CollisionCheckResult",
    "CollisionCheckUnavailable",
    "Contact",
    "FragmentError",
    "GeometryPrimitive",
    "Pose",
    "Scene",
    "SceneBuildError",
    "SceneInstance",
    "base_footprint_mm",
    "build_scene",
    "check_collisions",
    "check_workspace_containment",
    "compute_world_poses",
    "list_collision_primitives",
    "render_html",
    "scene_to_payload",
    "world_aabb",
]
