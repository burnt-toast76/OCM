# SPDX-License-Identifier: AGPL-3.0-or-later
"""ocm_generator.scene.containment: workspace footprint refusal. Kept
decoupled from ocm_core/ocm_resolve/build.Scene by design (see
containment.py's docstring) -- these tests build the composed URDF and
link-name maps by hand, exactly as build_scene() would hand them over,
without needing a real cell/module fixture tree.
"""

from __future__ import annotations

import math

from ocm_generator.scene.containment import check_workspace_containment


def _box_link(name: str, xyz: tuple[float, float, float], size: tuple[float, float, float]) -> str:
    x, y, z = xyz
    sx, sy, sz = size
    return f"""
  <link name="{name}">
    <collision>
      <origin xyz="{x} {y} {z}" rpy="0 0 0"/>
      <geometry><box size="{sx} {sy} {sz}"/></geometry>
    </collision>
  </link>"""


def _fixed_joint(name: str, parent: str, child: str, xyz: tuple[float, float, float] = (0, 0, 0)) -> str:
    x, y, z = xyz
    return f"""
  <joint name="{name}" type="fixed">
    <parent link="{parent}"/>
    <child link="{child}"/>
    <origin xyz="{x} {y} {z}" rpy="0 0 0"/>
  </joint>"""


def _urdf(*parts: str) -> str:
    return '<?xml version="1.0"?>\n<robot name="t">\n  <link name="world"/>' + "".join(parts) + "\n</robot>"


# A 1.2 x 0.9 m deck, centered at (0.6, 0.45, 0) -- same footprint as
# frame1200's real slab.
_BASE_URDF_PARTS = (
    _box_link("base__deck", (0.6, 0.45, -0.075), (1.2, 0.9, 0.15))
    + _fixed_joint("base__mount", "world", "base__deck")
)


def _base_and(*extra_parts: str) -> str:
    return _urdf(_BASE_URDF_PARTS, *extra_parts)


def test_instance_fully_inside_the_footprint_passes():
    urdf = _base_and(
        _box_link("nest1__origin", (0.6, 0.45, 0.03), (0.1, 0.1, 0.06)) + _fixed_joint("nest1__mount", "world", "nest1__origin"),
    )

    errors = check_workspace_containment(
        cell_id="t",
        urdf_xml=urdf,
        joint_state={},
        base_link_names=frozenset({"base__deck"}),
        instance_link_names={"nest1": frozenset({"nest1__origin"})},
        instance_kinds={"nest1": "fixture"},
    )

    assert errors == []


def test_instance_overhanging_plus_x_is_refused_with_overhang_in_mm():
    # deck spans X:[0, 1.2]. Place a 0.2m box centered at x=1.25 -> it
    # spans X:[1.15, 1.35], overhanging the +X edge by 1.35-1.2 = 0.15m = 150mm.
    urdf = _base_and(
        _box_link("nest1__origin", (1.25, 0.45, 0.03), (0.2, 0.1, 0.06)) + _fixed_joint("nest1__mount", "world", "nest1__origin"),
    )

    errors = check_workspace_containment(
        cell_id="t",
        urdf_xml=urdf,
        joint_state={},
        base_link_names=frozenset({"base__deck"}),
        instance_link_names={"nest1": frozenset({"nest1__origin"})},
        instance_kinds={"nest1": "fixture"},
    )

    assert len(errors) == 1
    assert "nest1" in errors[0]
    assert "+X by 150.0 mm" in errors[0]


def test_instance_overhanging_two_edges_reports_both():
    # Box centered at (-0.1, -0.1, ...) with a 0.2m footprint: spans
    # X:[-0.2,0.0] (deck starts at 0 -> 200mm overhang on -X) and
    # Y:[-0.2,0.0] (deck starts at 0 -> 200mm overhang on -Y).
    urdf = _base_and(
        _box_link("cam1__origin", (-0.1, -0.1, 0.03), (0.2, 0.2, 0.06)) + _fixed_joint("cam1__mount", "world", "cam1__origin"),
    )

    errors = check_workspace_containment(
        cell_id="t",
        urdf_xml=urdf,
        joint_state={},
        base_link_names=frozenset({"base__deck"}),
        instance_link_names={"cam1": frozenset({"cam1__origin"})},
        instance_kinds={"cam1": "sensor"},
    )

    assert len(errors) == 1
    assert "-X by 200.0 mm" in errors[0]
    assert "-Y by 200.0 mm" in errors[0]


def test_robot_kind_is_exempt_even_when_grossly_overhanging():
    urdf = _base_and(
        _box_link("robot1__base_link", (5.0, 5.0, 0.5), (0.3, 0.3, 1.0)) + _fixed_joint("robot1__mount", "world", "robot1__base_link"),
    )

    errors = check_workspace_containment(
        cell_id="t",
        urdf_xml=urdf,
        joint_state={},
        base_link_names=frozenset({"base__deck"}),
        instance_link_names={"robot1": frozenset({"robot1__base_link"})},
        instance_kinds={"robot1": "robot"},
    )

    assert errors == []


def test_non_robot_instance_attached_to_the_robot_is_still_checked():
    # sd1 isn't kind=robot, so even though it's kinematically downstream of
    # a robot, it's checked -- exactly the case joint_state exists for.
    urdf = _base_and(
        _box_link("robot1__base_link", (0.6, 0.45, 0.5), (0.3, 0.3, 1.0)) + _fixed_joint("robot1__mount", "world", "robot1__base_link"),
        _box_link("sd1__origin", (5.0, 5.0, 0.5), (0.1, 0.1, 0.1)) + _fixed_joint("sd1__mount", "robot1__base_link", "sd1__origin"),
    )

    errors = check_workspace_containment(
        cell_id="t",
        urdf_xml=urdf,
        joint_state={},
        base_link_names=frozenset({"base__deck"}),
        instance_link_names={
            "robot1": frozenset({"robot1__base_link"}),
            "sd1": frozenset({"sd1__origin"}),
        },
        instance_kinds={"robot1": "robot", "sd1": "end_effector"},
    )

    assert len(errors) == 1
    assert "sd1" in errors[0]
    assert "robot1" not in errors[0]


def test_instance_exactly_at_the_boundary_does_not_false_positive():
    # deck spans X:[0,1.2]. A box centered at x=0.5 with half-width exactly
    # 0.6 spans X:[-0.1+0.6=0.0... ] -- construct it to land EXACTLY on the
    # boundary: centered at 0.6, size 1.2 -> spans [0.0, 1.2], flush with
    # the deck edges, not beyond them.
    urdf = _base_and(
        _box_link("nest1__origin", (0.6, 0.45, 0.03), (1.2, 0.9, 0.06)) + _fixed_joint("nest1__mount", "world", "nest1__origin"),
    )

    errors = check_workspace_containment(
        cell_id="t",
        urdf_xml=urdf,
        joint_state={},
        base_link_names=frozenset({"base__deck"}),
        instance_link_names={"nest1": frozenset({"nest1__origin"})},
        instance_kinds={"nest1": "fixture"},
    )

    assert errors == []


def test_missing_base_geometry_is_a_clear_error_not_a_crash():
    urdf = _urdf(_box_link("nest1__origin", (0, 0, 0), (0.1, 0.1, 0.1)) + _fixed_joint("nest1__mount", "world", "nest1__origin"))

    errors = check_workspace_containment(
        cell_id="my-cell",
        urdf_xml=urdf,
        joint_state={},
        base_link_names=frozenset({"base__deck"}),  # doesn't exist in this URDF
        instance_link_names={"nest1": frozenset({"nest1__origin"})},
        instance_kinds={"nest1": "fixture"},
    )

    assert len(errors) == 1
    assert "my-cell" in errors[0]
    assert "no collision geometry" in errors[0]


def test_joint_state_moves_where_an_attached_instance_is_checked():
    # sd1 is mounted (identity offset) on a revolute joint sitting at the
    # deck center (0.6, 0.45). At joint angle 0, a 0.5m local-+X offset
    # lands sd1 at world (1.1, 0.45) -- inside the deck (X:[0,1.2],
    # Y:[0,0.9]). Rotating the joint +90 deg about Z swings that same
    # local offset to world +Y, box center (0.6, 0.95); with the box's own
    # 25mm half-width its edge reaches 0.975, 75mm past the deck's Y=0.9
    # edge. Proves the containment check actually uses the joint_state
    # it's given, not a static zero pose.
    urdf = _base_and(
        _fixed_joint("robot1__mount", "world", "robot1__base"),
        f"""
  <link name="robot1__base"/>
  <link name="robot1__arm"/>
  <joint name="robot1__shoulder" type="revolute">
    <parent link="robot1__base"/>
    <child link="robot1__arm"/>
    <origin xyz="0.6 0.45 0.1" rpy="0 0 0"/>
    <axis xyz="0 0 1"/>
    <limit lower="-6.28" upper="6.28" effort="1" velocity="1"/>
  </joint>"""
        + _box_link("sd1__origin", (0.5, 0.0, 0.0), (0.05, 0.05, 0.05))
        + _fixed_joint("sd1__mount", "robot1__arm", "sd1__origin"),
    )
    link_names = {
        "robot1": frozenset({"robot1__base", "robot1__arm"}),
        "sd1": frozenset({"sd1__origin"}),
    }
    kinds = {"robot1": "robot", "sd1": "end_effector"}

    at_zero = check_workspace_containment(
        cell_id="t",
        urdf_xml=urdf,
        joint_state={},
        base_link_names=frozenset({"base__deck"}),
        instance_link_names=link_names,
        instance_kinds=kinds,
    )
    assert at_zero == []

    rotated = check_workspace_containment(
        cell_id="t",
        urdf_xml=urdf,
        joint_state={"robot1__shoulder": math.pi / 2},
        base_link_names=frozenset({"base__deck"}),
        instance_link_names=link_names,
        instance_kinds=kinds,
    )
    assert len(rotated) == 1
    assert "sd1" in rotated[0]
    assert "+Y by 75.0 mm" in rotated[0]
