# SPDX-License-Identifier: AGPL-3.0-or-later
"""Workspace containment: does every non-base, non-robot module's world
AABB stay within the base module's own physical footprint (X/Y only)?

Per spec/02's datum convention and frame1200's own module comment: the
base module (kind=base) IS the workspace boundary. Its collision geometry
-- deck slab plus guard walls -- defines the footprint everything else has
to stay inside; the walls are collision geometry specifically so a real
planner has something concrete to refuse against later. This check is the
same idea, done now, cheaply, without a planner: footprint = the X/Y union
of the base's own collision boxes (deck AND walls together -- not just the
slab -- since the walls are equally real geometry nothing should overlap).

The robot itself (kind=robot) is exempt: its own links sweep a large,
joint-state-dependent volume by design -- keeping THAT inside the walls at
every configuration the planner will ever command is the planner's job,
not something one static snapshot can certify. Anything mounted ON the
robot (e.g. sd1 on robot1.flange) is NOT exempt: given a joint_state (see
cell.yaml's optional per-instance joint_state, applied via the same
kinematics.compute_world_poses this uses), it has a well-defined static
pose that's entirely reasonable to sanity-check now.

Deliberately decoupled from ocm_core/ocm_resolve/build.Scene -- takes
plain link-name sets and a kind lookup, not those richer types -- so it
has no import-cycle risk with build.py (which calls it) and is unit
testable against small hand-built URDF strings alone.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Optional

from .kinematics import JointState, compute_world_poses, list_collision_primitives, world_aabb
from .transforms import Vec3

_EPSILON_M = 1e-6  # ignore sub-micron floating-point noise at an exact boundary


def _union_aabb(
    link_names: frozenset[str], root: ET.Element, world_poses: dict
) -> tuple[Optional[Vec3], Optional[Vec3]]:
    lo: Optional[list[float]] = None
    hi: Optional[list[float]] = None
    for link in root.findall("link"):
        name = link.get("name")
        if not name or name not in link_names or name not in world_poses:
            continue
        for prim in list_collision_primitives(link, world_poses[name]):
            pmin, pmax = world_aabb(prim)
            if lo is None:
                lo, hi = list(pmin), list(pmax)
            else:
                lo = [min(lo[i], pmin[i]) for i in range(3)]
                hi = [max(hi[i], pmax[i]) for i in range(3)]
    if lo is None:
        return None, None
    return (lo[0], lo[1], lo[2]), (hi[0], hi[1], hi[2])  # type: ignore[index]


def base_footprint_mm(
    urdf_xml: str,
    joint_state: JointState,
    base_link_names: frozenset[str],
    world_link: str = "world",
) -> tuple[Vec3, Vec3] | None:
    """The base module's own world AABB, in metres -- the same footprint
    `check_workspace_containment` measures every other instance against.
    Exposed on its own (not just as a violation-message fragment) so a
    caller can show an agent the workspace bounds proactively, before it
    ever tries a placement that overhangs them. None if the base has no
    collision geometry at all.
    """
    root = ET.fromstring(urdf_xml)
    world_poses = compute_world_poses(root, joint_state, world_link)
    return _union_aabb(base_link_names, root, world_poses)


def check_workspace_containment(
    cell_id: str,
    urdf_xml: str,
    joint_state: JointState,
    base_link_names: frozenset[str],
    instance_link_names: dict[str, frozenset[str]],
    instance_kinds: dict[str, str],
    world_link: str = "world",
) -> list[str]:
    """Return every instance whose world AABB (X/Y) extends beyond the
    base's own footprint, as human-readable violation strings naming the
    instance and each overhanging edge in mm. Empty list if everything
    fits.
    """
    root = ET.fromstring(urdf_xml)
    world_poses = compute_world_poses(root, joint_state, world_link)

    base_min, base_max = _union_aabb(base_link_names, root, world_poses)
    if base_min is None:
        return [f"{cell_id}: base module has no collision geometry -- cannot determine the workspace footprint"]

    errors: list[str] = []
    for name, link_names in instance_link_names.items():
        if instance_kinds.get(name) == "robot":
            continue  # exempt -- see module docstring

        inst_min, inst_max = _union_aabb(link_names, root, world_poses)
        if inst_min is None:
            continue  # no collision geometry on this instance at all

        overhangs: list[str] = []
        if base_min[0] - inst_min[0] > _EPSILON_M:
            overhangs.append(f"-X by {(base_min[0] - inst_min[0]) * 1000:.1f} mm")
        if inst_max[0] - base_max[0] > _EPSILON_M:
            overhangs.append(f"+X by {(inst_max[0] - base_max[0]) * 1000:.1f} mm")
        if base_min[1] - inst_min[1] > _EPSILON_M:
            overhangs.append(f"-Y by {(base_min[1] - inst_min[1]) * 1000:.1f} mm")
        if inst_max[1] - base_max[1] > _EPSILON_M:
            overhangs.append(f"+Y by {(inst_max[1] - base_max[1]) * 1000:.1f} mm")

        if overhangs:
            footprint = (
                f"X:[{base_min[0] * 1000:.0f},{base_max[0] * 1000:.0f}] "
                f"Y:[{base_min[1] * 1000:.0f},{base_max[1] * 1000:.0f}] mm"
            )
            errors.append(
                f"module {name}: extends beyond the workspace footprint ({footprint}): " + ", ".join(overhangs)
            )

    return errors
