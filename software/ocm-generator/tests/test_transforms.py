# SPDX-License-Identifier: AGPL-3.0-or-later
"""Transform-composition correctness. This matters more than it looks --
a sign or ordering bug here would silently poison every world pose this
viewer computes, and the same math is what any future planner debugging
will lean on. Kept independent of URDF parsing and Tesseract entirely.
"""

from __future__ import annotations

import math

import pytest

from ocm_generator.scene.transforms import Pose


def test_two_link_chain_with_a_rotated_joint_lands_at_a_known_world_pose():
    # parent at the world origin (identity). A joint from parent to child
    # at xyz=(1,0,0), rpy=(0,0,pi/2) -- a 90 degree yaw. The child itself
    # sits at (0,1,0) in ITS OWN frame, unrotated.
    #
    # Rotating local (0,1,0) by +90 deg about Z gives (-1,0,0); translating
    # by the joint's (1,0,0) origin lands the child's world position
    # exactly on the world origin. Neither input is (0,0,0), so a
    # sign/order bug in the rotation math produces a wrong answer here,
    # not a suspiciously-convenient right one by accident.
    world_to_parent = Pose.identity()
    parent_to_joint = Pose.from_xyz_rpy((1.0, 0.0, 0.0), (0.0, 0.0, math.pi / 2))
    joint_to_child = Pose.from_xyz_rpy((0.0, 1.0, 0.0), (0.0, 0.0, 0.0))

    world_to_child = world_to_parent.compose(parent_to_joint).compose(joint_to_child)

    assert world_to_child.translation == pytest.approx((0.0, 0.0, 0.0), abs=1e-9)

    qx, qy, qz, qw = world_to_child.quaternion_xyzw()
    expected = (0.0, 0.0, math.sin(math.pi / 4), math.cos(math.pi / 4))
    assert (qx, qy, qz, qw) == pytest.approx(expected, abs=1e-9)


def test_rotation_is_applied_before_translating_into_the_parent_frame():
    # A 90 degree yaw, then a 1m offset along the LOCAL +X axis, should
    # land at world (0,1,0): local +X has been rotated to point along
    # world +Y before the offset is added. Pins down that rotation
    # composes before translation, not the other way around.
    joint = Pose.from_xyz_rpy((0.0, 0.0, 0.0), (0.0, 0.0, math.pi / 2))
    local_offset = Pose.from_xyz_rpy((1.0, 0.0, 0.0), (0.0, 0.0, 0.0))

    result = joint.compose(local_offset)

    assert result.translation == pytest.approx((0.0, 1.0, 0.0), abs=1e-9)


def test_identity_is_neutral_on_both_sides():
    p = Pose.from_xyz_rpy((1.0, 2.0, 3.0), (0.3, -0.4, 0.5))

    assert p.compose(Pose.identity()).translation == pytest.approx(p.translation)
    assert Pose.identity().compose(p).translation == pytest.approx(p.translation)
    assert p.compose(Pose.identity()).quaternion_xyzw() == pytest.approx(p.quaternion_xyzw())


def test_pure_translation_chain_just_adds():
    a = Pose.from_xyz_rpy((1.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    b = Pose.from_xyz_rpy((0.0, 2.0, 0.0), (0.0, 0.0, 0.0))

    c = a.compose(b)

    assert c.translation == pytest.approx((1.0, 2.0, 0.0))


def test_three_link_chain_composes_associatively():
    a = Pose.from_xyz_rpy((0.5, 0.0, 0.0), (0.0, 0.0, math.pi / 2))
    b = Pose.from_xyz_rpy((0.0, 0.3, 0.0), (0.0, math.pi / 4, 0.0))
    c = Pose.from_xyz_rpy((0.0, 0.0, 0.2), (0.0, 0.0, 0.0))

    left = a.compose(b).compose(c)
    right = a.compose(b.compose(c))

    assert left.translation == pytest.approx(right.translation, abs=1e-9)
    assert left.quaternion_xyzw() == pytest.approx(right.quaternion_xyzw(), abs=1e-9)


def test_quaternion_from_matrix_matches_known_axis_rotations():
    half = math.pi / 4
    assert Pose.from_xyz_rpy((0, 0, 0), (math.pi / 2, 0, 0)).quaternion_xyzw() == pytest.approx(
        (math.sin(half), 0.0, 0.0, math.cos(half)), abs=1e-9
    )
    assert Pose.from_xyz_rpy((0, 0, 0), (0, math.pi / 2, 0)).quaternion_xyzw() == pytest.approx(
        (0.0, math.sin(half), 0.0, math.cos(half)), abs=1e-9
    )
    assert Pose.from_xyz_rpy((0, 0, 0), (0, 0, 0)).quaternion_xyzw() == pytest.approx(
        (0.0, 0.0, 0.0, 1.0), abs=1e-9
    )


def test_axis_angle_matches_rpy_for_each_principal_axis():
    # Two independent ways to build "rotate pi/3 about a principal axis"
    # must agree -- this is what a revolute joint's <axis> + joint value
    # needs to match the fixed-axis rpy convention everything else uses.
    angle = math.pi / 3
    for axis, rpy in (
        ((1.0, 0.0, 0.0), (angle, 0.0, 0.0)),
        ((0.0, 1.0, 0.0), (0.0, angle, 0.0)),
        ((0.0, 0.0, 1.0), (0.0, 0.0, angle)),
    ):
        from_axis = Pose.from_axis_angle(axis, angle)
        from_rpy = Pose.from_xyz_rpy((0.0, 0.0, 0.0), rpy)
        assert from_axis.quaternion_xyzw() == pytest.approx(from_rpy.quaternion_xyzw(), abs=1e-9)


def test_axis_angle_rotation_of_a_perpendicular_point_is_rodrigues_textbook():
    # Rotating (1,0,0) by +90 deg about +Z should land at (0,1,0) -- the
    # textbook right-hand-rule case, independent of the rpy machinery.
    pose = Pose.from_axis_angle((0.0, 0.0, 1.0), math.pi / 2)

    result = pose.transform_point((1.0, 0.0, 0.0))

    assert result == pytest.approx((0.0, 1.0, 0.0), abs=1e-9)


def test_axis_angle_normalizes_a_non_unit_axis():
    a = Pose.from_axis_angle((0.0, 0.0, 1.0), math.pi / 2)
    b = Pose.from_axis_angle((0.0, 0.0, 5.0), math.pi / 2)  # same direction, not unit length

    assert a.quaternion_xyzw() == pytest.approx(b.quaternion_xyzw(), abs=1e-9)


def test_transform_point_matches_compose_with_a_translation_only_pose():
    pose = Pose.from_xyz_rpy((1.0, 2.0, 3.0), (0.1, -0.2, 0.3))
    point = (0.5, -0.5, 0.25)

    via_transform_point = pose.transform_point(point)
    via_compose = pose.compose(Pose(point)).translation

    assert via_transform_point == pytest.approx(via_compose, abs=1e-9)


# ---------------------------------------------------------------------------
# from_z_axis / inverse / axis_angle / rotate_vector -- added for the
# planner (standoff/contact pose construction, IK targets, URScript's own
# p[x,y,z,rx,ry,rz] pose convention).
# ---------------------------------------------------------------------------


def test_from_z_axis_points_its_local_z_along_the_given_direction():
    # A pose whose +Z axis points straight along world -X: rotating the
    # local +Z unit vector by the pose's own rotation must land on -X.
    pose = Pose.from_z_axis((1.0, 2.0, 3.0), (-1.0, 0.0, 0.0))

    assert pose.translation == (1.0, 2.0, 3.0)
    assert pose.rotate_vector((0.0, 0.0, 1.0)) == pytest.approx((-1.0, 0.0, 0.0), abs=1e-9)


def test_from_z_axis_normalizes_a_non_unit_direction():
    a = Pose.from_z_axis((0.0, 0.0, 0.0), (0.0, 0.0, 2.0))
    b = Pose.from_z_axis((0.0, 0.0, 0.0), (0.0, 0.0, 7.0))

    assert a.quaternion_xyzw() == pytest.approx(b.quaternion_xyzw(), abs=1e-9)


def test_from_z_axis_falls_back_to_a_different_reference_when_up_hint_is_parallel():
    # The default up_hint is +Z; asking for local +Z to point along world +Z
    # too would leave the look-at basis undefined unless the fallback
    # reference kicks in. Just needs to not raise and produce a valid
    # (orthonormal, right-handed) basis.
    pose = Pose.from_z_axis((0.0, 0.0, 0.0), (0.0, 0.0, 1.0))

    x_axis = pose.rotate_vector((1.0, 0.0, 0.0))
    y_axis = pose.rotate_vector((0.0, 1.0, 0.0))
    z_axis = pose.rotate_vector((0.0, 0.0, 1.0))
    assert z_axis == pytest.approx((0.0, 0.0, 1.0), abs=1e-9)
    # right-handed and orthonormal: x cross y == z
    cross = (
        x_axis[1] * y_axis[2] - x_axis[2] * y_axis[1],
        x_axis[2] * y_axis[0] - x_axis[0] * y_axis[2],
        x_axis[0] * y_axis[1] - x_axis[1] * y_axis[0],
    )
    assert cross == pytest.approx(z_axis, abs=1e-9)


def test_inverse_composed_with_self_is_identity():
    pose = Pose.from_xyz_rpy((1.0, -2.0, 0.5), (0.3, -0.7, 1.1))

    identity = pose.compose(pose.inverse())

    assert identity.translation == pytest.approx((0.0, 0.0, 0.0), abs=1e-9)
    assert identity.quaternion_xyzw() == pytest.approx((0.0, 0.0, 0.0, 1.0), abs=1e-9)


def test_inverse_undoes_transform_point():
    pose = Pose.from_xyz_rpy((2.0, 3.0, -1.0), (0.2, 0.4, -0.6))
    point = (5.0, -1.0, 2.0)

    round_tripped = pose.inverse().transform_point(pose.transform_point(point))

    assert round_tripped == pytest.approx(point, abs=1e-9)


def test_axis_angle_round_trips_through_from_axis_angle():
    axis = (0.0, 1.0, 0.0)
    angle = math.pi / 3
    pose = Pose.from_axis_angle(axis, angle)

    rx, ry, rz = pose.axis_angle()

    assert (rx, ry, rz) == pytest.approx((0.0, angle, 0.0), abs=1e-9)


def test_axis_angle_of_identity_is_zero():
    assert Pose.identity().axis_angle() == pytest.approx((0.0, 0.0, 0.0), abs=1e-9)


def test_axis_angle_handles_a_180_degree_rotation():
    # The near-pi branch of _axis_angle_from_matrix -- the usual
    # off-diagonal-difference formula divides by ~0 right here.
    pose = Pose.from_axis_angle((0.0, 0.0, 1.0), math.pi)

    rx, ry, rz = pose.axis_angle()

    angle = math.sqrt(rx * rx + ry * ry + rz * rz)
    assert angle == pytest.approx(math.pi, abs=1e-9)
    assert (rx / angle, ry / angle, rz / angle) == pytest.approx((0.0, 0.0, 1.0), abs=1e-6)


def test_rotate_vector_ignores_translation():
    pose = Pose.from_xyz_rpy((100.0, -50.0, 3.0), (0.0, 0.0, math.pi / 2))

    rotated = pose.rotate_vector((1.0, 0.0, 0.0))

    assert rotated == pytest.approx((0.0, 1.0, 0.0), abs=1e-9)
