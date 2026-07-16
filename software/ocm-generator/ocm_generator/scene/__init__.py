# SPDX-License-Identifier: AGPL-3.0-or-later
"""ocm_generator.scene -- compile a ResolvedCell into a tesseract_robotics Environment."""

from .build import Scene, SceneInstance, build_scene
from .containment import check_workspace_containment
from .errors import FragmentError, SceneBuildError
from .kinematics import GeometryPrimitive, compute_world_poses, list_collision_primitives, world_aabb
from .transforms import Pose
from .viewer import render_html, scene_to_payload

__all__ = [
    "FragmentError",
    "GeometryPrimitive",
    "Pose",
    "Scene",
    "SceneBuildError",
    "SceneInstance",
    "build_scene",
    "check_workspace_containment",
    "compute_world_poses",
    "list_collision_primitives",
    "render_html",
    "scene_to_payload",
    "world_aabb",
]
