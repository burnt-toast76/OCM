# SPDX-License-Identifier: AGPL-3.0-or-later
"""Analytic UR inverse kinematics via tesseract_kinematics's URInvKinFactory.

Lazily imports tesseract_robotics (same reasoning as .scene.collision): only
reached from `ocm plan --emit-urscript`, so the base ocm-generator install
doesn't need the `tesseract` extra.

## A second packaging workaround

Same shape as .scene.collision's Bullet one, a different plugin family: the
default kinematics plugin factory has no inv-kin plugin registered either,
and the working backend DLL (`tesseract_kinematics_ur_factory-<hash>.dll`)
lives in the same content-hashed `tesseract_robotics.libs/` sibling
directory a delvewheel Windows build bundles it in. Found at runtime the
same way, for the same reason (the hash isn't stable across builds).

The plugin config's root key is `kinematic_plugins` -- singular
"kinematic", not "kinematics_plugins" as the analogous
`contact_manager_plugins` key might suggest by pattern-matching. That
spelling came from extracting the DLL's own embedded strings, not from any
published schema doc: a misconfigured key here doesn't raise -- it hands
back an `InverseKinematics` object that SEGFAULTS the moment any method is
called on it, which is exactly why the spelling matters enough to call out.

## Frame convention

`URInvKinFactory`'s working frame is the solver's own `base_link` (see
`getWorkingFrame()`), confirmed empirically -- NOT world. Every pose passed
to `solve_ur_ik` must already be expressed relative to that link.

## Solution vectors

`calcInvKin` returns up to 8 analytic solutions (UR's closed-form IK), or
zero for an unreachable target -- never a crash either way. Its return
value doesn't support Python iteration or `len()` reliably (a SWIG binding
quirk seen elsewhere in this package too -- see .scene.collision's own
notes on similar issues), so solutions are collected by indexing until an
IndexError, capped well above the 8 the solver can ever actually return.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ocm_generator.scene.transforms import Pose

from .errors import PlanningUnavailable, PoseUnreachableError

UR_JOINT_ORDER = (
    "shoulder_pan_joint",
    "shoulder_lift_joint",
    "elbow_joint",
    "wrist_1_joint",
    "wrist_2_joint",
    "wrist_3_joint",
)

_MAX_SOLUTIONS_PROBED = 16  # the UR analytic solver never returns more than 8 -- a hard stop, not a real limit


def _find_ur_kinematics_library() -> Optional[str]:
    """Absolute path (no extension) to the bundled UR kinematics factory
    library, or None if it can't be found this way. See module docstring.
    """
    try:
        import tesseract_robotics
    except ImportError:
        return None

    package_dir = Path(tesseract_robotics.__file__).resolve().parent
    libs_dir = package_dir.parent / f"{package_dir.name}.libs"
    if not libs_dir.is_dir():
        return None

    for pattern in (
        "*tesseract_kinematics_ur_factory*.dll",
        "*tesseract_kinematics_ur_factory*.so*",
        "*tesseract_kinematics_ur_factory*.dylib",
    ):
        matches = sorted(libs_dir.glob(pattern))
        if matches:
            return str(matches[0].with_suffix(""))
    return None


def solve_ur_ik(
    urdf_xml: str,
    base_link: str,
    tip_link: str,
    target_base_t_tip: Pose,
    seed: tuple[float, ...],
    pose_name: str,
) -> tuple[float, ...]:
    """The IK solution (radians, UR_JOINT_ORDER) closest to `seed` for
    `target_base_t_tip` (already expressed relative to `base_link`).

    Raises PoseUnreachableError, naming `pose_name`, if the UR analytic
    solver finds no solution at all -- that target is simply out of reach,
    not a bug to retry around. Raises PlanningUnavailable if
    tesseract-robotics isn't installed or its plugin backend can't be
    loaded (same shape as scene.collision.CollisionCheckUnavailable).
    """
    try:
        import numpy as np
        from tesseract_robotics.tesseract_common import GeneralResourceLocator, TransformMap, VectorIsometry3d
        from tesseract_robotics.tesseract_environment import Environment
        from tesseract_robotics.tesseract_kinematics import KinematicsPluginFactory
    except ImportError as e:
        raise PlanningUnavailable(
            "IK solving requires the 'tesseract' extra (tesseract-robotics is not installed): "
            "pip install ocm-generator[tesseract]"
        ) from e

    locator = GeneralResourceLocator()
    env = Environment()
    if not env.init(urdf_xml, locator):
        raise PlanningUnavailable(
            "tesseract Environment.init() rejected the composed URDF -- this should not happen "
            "if build_scene() already succeeded"
        )

    library = _find_ur_kinematics_library()
    if library is None:
        raise PlanningUnavailable(
            "tesseract-robotics has no UR kinematics plugin registered, and the bundled "
            "tesseract_kinematics_ur_factory library could not be located to work around it -- "
            "see ocm_generator/planner/ik.py's module docstring"
        )

    yaml_cfg = f"""
kinematic_plugins:
  search_libraries:
    - {library}
  inv_kin_plugins:
    manipulator:
      default: URInvKin
      plugins:
        URInvKin:
          class: URInvKinFactory
          config:
            base_link: {base_link}
            tip_link: {tip_link}
            model: UR5e
"""
    factory = KinematicsPluginFactory(yaml_cfg, locator)
    invkin = factory.createInvKin("manipulator", "URInvKin", env.getSceneGraph(), env.getState())
    if invkin is None:
        raise PlanningUnavailable("failed to create the URInvKin inverse kinematics solver")

    matrix = np.eye(4)
    matrix[:3, :3] = np.array(target_base_t_tip.rotation)
    matrix[0, 3], matrix[1, 3], matrix[2, 3] = target_base_t_tip.translation

    isometries = VectorIsometry3d(1)
    isometries[0].setMatrix(matrix)

    transforms = TransformMap()
    transforms[tip_link] = isometries[0]

    solutions = invkin.calcInvKin(transforms, np.array(seed, dtype=float))

    found: list = []
    i = 0
    while i < _MAX_SOLUTIONS_PROBED:
        try:
            sol = solutions[i]
        except (IndexError, RuntimeError):
            break
        found.append(np.array(sol).flatten())
        i += 1

    if not found:
        raise PoseUnreachableError(pose_name, f"no IK solution ({base_link} -> {tip_link})")

    seed_arr = np.array(seed, dtype=float)
    best = min(found, key=lambda s: float(np.sum((s - seed_arr) ** 2)))
    return tuple(float(v) for v in best)
