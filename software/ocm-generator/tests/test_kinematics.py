# SPDX-License-Identifier: AGPL-3.0-or-later
"""ocm_generator.scene.kinematics: forward kinematics with an optional
joint_state, and multi-collision-per-link geometry extraction. Kept as
plain ElementTree fixtures (no ocm_core/ocm_resolve/Tesseract involved) so
these stay fast, isolated unit tests of the FK/geometry logic itself.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET

import pytest

from ocm_generator.scene.kinematics import (
    GeometryPrimitive,
    compute_world_poses,
    list_collision_primitives,
    world_aabb,
)
from ocm_generator.scene.transforms import Pose


def _parse(xml_text: str) -> ET.Element:
    return ET.fromstring(xml_text)


# ---------------------------------------------------------------------------
# Multi-collision parsing
# ---------------------------------------------------------------------------

_THREE_BOX_LINK = """<?xml version="1.0"?>
<robot name="frag">
  <link name="world"/>
  <link name="deck">
    <collision>
      <origin xyz="0 0 0" rpy="0 0 0"/>
      <geometry><box size="1.0 1.0 0.1"/></geometry>
    </collision>
    <collision>
      <origin xyz="0.5 0 0.5" rpy="0 0 0"/>
      <geometry><box size="0.05 1.0 1.0"/></geometry>
    </collision>
    <collision>
      <origin xyz="-0.5 0 0.5" rpy="0 0 0"/>
      <geometry><box size="0.05 1.0 1.0"/></geometry>
    </collision>
  </link>
  <joint name="mount" type="fixed">
    <parent link="world"/>
    <child link="deck"/>
    <origin xyz="0 0 0" rpy="0 0 0"/>
  </joint>
</robot>"""


def test_link_carrying_three_collision_boxes_yields_three_primitives():
    root = _parse(_THREE_BOX_LINK)
    link = root.find("link[@name='deck']")

    primitives = list_collision_primitives(link, Pose.identity())

    assert len(primitives) == 3
    assert all(p.kind == "box" for p in primitives)
    assert {tuple(sorted(p.dims.items())) for p in primitives} == {
        (("x", 1.0), ("y", 1.0), ("z", 0.1)),
        (("x", 0.05), ("y", 1.0), ("z", 1.0)),
    }


def test_each_collision_keeps_its_own_local_origin_offset():
    root = _parse(_THREE_BOX_LINK)
    link = root.find("link[@name='deck']")

    primitives = list_collision_primitives(link, Pose.identity())

    positions = {p.world.translation for p in primitives}
    assert (0.0, 0.0, 0.0) in positions
    assert (0.5, 0.0, 0.5) in positions
    assert (-0.5, 0.0, 0.5) in positions


def test_link_with_no_collision_yields_no_primitives():
    root = _parse('<robot name="frag"><link name="a"/></robot>')
    link = root.find("link")

    assert list_collision_primitives(link, Pose.identity()) == []


# ---------------------------------------------------------------------------
# joint_state-aware forward kinematics
# ---------------------------------------------------------------------------

_REVOLUTE_CHAIN = """<?xml version="1.0"?>
<robot name="frag">
  <link name="world"/>
  <link name="a"/>
  <link name="b"/>
  <joint name="fixed_mount" type="fixed">
    <parent link="world"/>
    <child link="a"/>
    <origin xyz="1 0 0" rpy="0 0 0"/>
  </joint>
  <joint name="shoulder" type="revolute">
    <parent link="a"/>
    <child link="b"/>
    <origin xyz="0 0 0" rpy="0 0 0"/>
    <axis xyz="0 0 1"/>
    <limit lower="-6.28" upper="6.28" effort="10" velocity="1"/>
  </joint>
</robot>"""


def test_revolute_joint_defaults_to_zero_without_a_joint_state():
    root = _parse(_REVOLUTE_CHAIN)

    poses = compute_world_poses(root)

    assert poses["b"].translation == pytest.approx((1.0, 0.0, 0.0), abs=1e-9)


def test_fk_with_a_nonzero_joint_state_matches_an_independently_computed_pose():
    # Link "a" sits at world (1,0,0) via a fixed mount. Link "b" hangs off
    # a revolute joint at "a" with an identity <origin> and axis +Z. Set
    # that joint to pi/2 -- since the joint's own origin is identity, the
    # joint's rotation IS "a"'s world pose composed with a pure Z rotation,
    # which composed with a's translation is just... "a"'s own position (a
    # rotation about a point doesn't move that point). What it DOES do is
    # rotate "b"'s downstream frame -- checked here by transforming a point
    # offset from b's origin and comparing against a hand-rotated answer,
    # computed independently of compute_world_poses via Pose.from_axis_angle
    # directly (the same primitive the FK uses internally, but composed by
    # hand here rather than via the BFS walk, so this is a genuine
    # cross-check of the whole pipeline, not a tautology).
    root = _parse(_REVOLUTE_CHAIN)
    angle = math.pi / 2

    poses = compute_world_poses(root, {"shoulder": angle})

    # b's own origin: unaffected (joint origin AND rotation both act at a's
    # location, which is where b's frame starts).
    assert poses["b"].translation == pytest.approx((1.0, 0.0, 0.0), abs=1e-9)

    # A point 1m along b's local +X should now read out along world +Y
    # (rotated by the joint), offset by a's world position -- computed
    # independently: world_a (identity rotation, translation (1,0,0))
    # composed with a pure Z rotation by pi/2, composed with local (1,0,0).
    independent = Pose((1.0, 0.0, 0.0)).compose(Pose.from_axis_angle((0, 0, 1), angle))
    expected_point = independent.transform_point((1.0, 0.0, 0.0))

    fk_point = poses["b"].transform_point((1.0, 0.0, 0.0))
    assert fk_point == pytest.approx(expected_point, abs=1e-9)
    assert fk_point == pytest.approx((1.0, 1.0, 0.0), abs=1e-9)


def test_joint_state_is_ignored_for_fixed_joints():
    xml_text = """<?xml version="1.0"?>
<robot name="frag">
  <link name="world"/>
  <link name="a"/>
  <joint name="j" type="fixed">
    <parent link="world"/>
    <child link="a"/>
    <origin xyz="1 0 0" rpy="0 0 0"/>
  </joint>
</robot>"""
    root = _parse(xml_text)

    # A fixed joint has no configurable position -- a joint_state entry
    # for it must not perturb the result.
    poses = compute_world_poses(root, {"j": 1.2345})

    assert poses["a"].translation == pytest.approx((1.0, 0.0, 0.0), abs=1e-9)


def test_prismatic_joint_translates_along_its_axis():
    xml_text = """<?xml version="1.0"?>
<robot name="frag">
  <link name="world"/>
  <link name="a"/>
  <joint name="slide" type="prismatic">
    <parent link="world"/>
    <child link="a"/>
    <origin xyz="0 0 0" rpy="0 0 0"/>
    <axis xyz="0 0 1"/>
    <limit lower="0" upper="1" effort="10" velocity="1"/>
  </joint>
</robot>"""
    root = _parse(xml_text)

    poses = compute_world_poses(root, {"slide": 0.4})

    assert poses["a"].translation == pytest.approx((0.0, 0.0, 0.4), abs=1e-9)


# ---------------------------------------------------------------------------
# world_aabb
# ---------------------------------------------------------------------------


def test_world_aabb_of_an_axis_aligned_box():
    prim = GeometryPrimitive("box", {"x": 2.0, "y": 4.0, "z": 1.0}, Pose((1.0, 1.0, 1.0)), False)

    lo, hi = world_aabb(prim)

    assert lo == pytest.approx((0.0, -1.0, 0.5))
    assert hi == pytest.approx((2.0, 3.0, 1.5))


def test_world_aabb_of_a_45deg_rotated_box_is_larger_than_unrotated():
    pose = Pose.from_xyz_rpy((0.0, 0.0, 0.0), (0.0, 0.0, math.pi / 4))
    prim = GeometryPrimitive("box", {"x": 1.0, "y": 1.0, "z": 1.0}, pose, False)

    lo, hi = world_aabb(prim)

    half_diag = math.sqrt(2) / 2
    assert lo == pytest.approx((-half_diag, -half_diag, -0.5), abs=1e-9)
    assert hi == pytest.approx((half_diag, half_diag, 0.5), abs=1e-9)


def test_world_aabb_of_a_sphere_ignores_rotation():
    pose = Pose.from_xyz_rpy((2.0, 0.0, 0.0), (0.3, 0.7, 1.1))
    prim = GeometryPrimitive("sphere", {"radius": 0.5}, pose, False)

    lo, hi = world_aabb(prim)

    assert lo == pytest.approx((1.5, -0.5, -0.5))
    assert hi == pytest.approx((2.5, 0.5, 0.5))


def test_world_aabb_of_a_cylinder_uses_its_circumscribing_box():
    prim = GeometryPrimitive("cylinder", {"radius": 0.3, "length": 2.0}, Pose.identity(), False)

    lo, hi = world_aabb(prim)

    assert lo == pytest.approx((-0.3, -0.3, -1.0))
    assert hi == pytest.approx((0.3, 0.3, 1.0))
