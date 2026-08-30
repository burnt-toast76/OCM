# SPDX-License-Identifier: AGPL-3.0-or-later
"""ADR-0028 D3 retrofit: a cell-supplied joint_state value is checked against
the joint's own <limit> in scene build, the same class of claim as an
actuation target. Fragments are inline synthetic fixtures (ADR-0014: real
joint limits are the module owner's to state)."""

from __future__ import annotations

import pytest

from ocm_core.cell import Cell
from ocm_generator.scene import SceneBuildError, build_scene
from ocm_resolve import resolve_cell

from .conftest import (
    base_fragment_xml,
    build_cell_dict,
    fragment_xml,
    minimal_base_manifest,
    minimal_robot_manifest,
    minimal_tool_manifest,
    write_module,
)

# A robot fragment with a flange (for tool1's mount.on), one limited revolute
# joint, one continuous joint (no limits by definition), one revolute with NO
# <limit> (malformed URDF), and one with only a lower bound (incomplete).
_ROBOT_FRAGMENT = """<?xml version="1.0"?>
<robot name="frag">
  <link name="origin"><collision><geometry><box size="0.05 0.05 0.05"/></geometry></collision></link>
  <link name="flange"><collision><geometry><box size="0.02 0.02 0.02"/></geometry></collision></link>
  <link name="wrist"/>
  <link name="spinner"/>
  <link name="bad_arm"/>
  <link name="half_arm"/>
  <joint name="mount_flange" type="fixed">
    <parent link="origin"/><child link="flange"/>
  </joint>
  <joint name="wrist_pitch" type="revolute">
    <parent link="flange"/><child link="wrist"/>
    <axis xyz="0 0 1"/>
    <limit lower="-1.0" upper="1.0" effort="10" velocity="1"/>
  </joint>
  <joint name="spin" type="continuous">
    <parent link="wrist"/><child link="spinner"/>
    <axis xyz="0 0 1"/>
  </joint>
  <joint name="bad_pitch" type="revolute">
    <parent link="wrist"/><child link="bad_arm"/>
    <axis xyz="0 0 1"/>
  </joint>
  <joint name="half_pitch" type="revolute">
    <parent link="wrist"/><child link="half_arm"/>
    <axis xyz="0 0 1"/>
    <limit lower="-1.0" effort="10" velocity="1"/>
  </joint>
</robot>"""


def _resolved(tmp_path, joint_state):
    root = tmp_path / "modules"
    write_module(root, minimal_base_manifest(), "base.urdf", base_fragment_xml("origin"))
    write_module(root, minimal_robot_manifest(), "robot.urdf", _ROBOT_FRAGMENT)
    write_module(root, minimal_tool_manifest(), "tool.urdf", fragment_xml("origin"))
    cell_dict = build_cell_dict()
    robot = next(m for m in cell_dict["modules"] if m["instance"] == "robot1")
    robot["joint_state"] = joint_state
    cell = Cell.from_dict(cell_dict)
    return resolve_cell(cell, root), root


def test_joint_state_within_limit_builds(tmp_path):
    resolved, root = _resolved(tmp_path, {"wrist_pitch": 0.5})
    scene = build_scene(resolved, root)
    assert scene.joint_state["robot1__wrist_pitch"] == 0.5


def test_joint_state_beyond_limit_is_refused(tmp_path):
    resolved, root = _resolved(tmp_path, {"wrist_pitch": 2.5})  # limit is [-1.0, 1.0]

    with pytest.raises(SceneBuildError) as exc:
        build_scene(resolved, root)

    # No embedded code prefix (Erratum 1 fix D): translate.py's
    # scene_error_to_refusal owns the OCM_JOINT_STATE_OUT_OF_LIMIT mapping.
    assert any(
        "joint_state drives 'wrist_pitch' to 2.5, outside its declared limit [-1.0, 1.0]" in e
        for e in exc.value.errors
    ), exc.value.errors


def test_continuous_joint_is_exempt_from_limit_checking(tmp_path):
    resolved, root = _resolved(tmp_path, {"spin": 100.0})  # any value is legal on continuous
    scene = build_scene(resolved, root)
    assert scene.joint_state["robot1__spin"] == 100.0


def test_revolute_joint_with_no_limit_is_refused_not_silently_passed(tmp_path):
    # Erratum 1 fix A: before it, `limit_el is None` short-circuited to the
    # assignment and a 9999.0-radian joint_state sailed through.
    resolved, root = _resolved(tmp_path, {"bad_pitch": 9999.0})

    with pytest.raises(SceneBuildError) as exc:
        build_scene(resolved, root)

    assert any(
        "joint_state drives 'bad_pitch' but the revolute joint declares no <limit>" in e
        for e in exc.value.errors
    ), exc.value.errors


def test_joint_with_incomplete_limit_is_refused(tmp_path):
    # `lower` without `upper` is as uncheckable as no <limit> at all.
    resolved, root = _resolved(tmp_path, {"half_pitch": 0.0})

    with pytest.raises(SceneBuildError) as exc:
        build_scene(resolved, root)

    assert any(
        "joint_state drives 'half_pitch' but the revolute joint declares no <limit>" in e
        for e in exc.value.errors
    ), exc.value.errors


def test_collect_all_behaviour_still_holds(tmp_path):
    # One out-of-limit value AND one unknown joint: both violations reported
    # in a single raise, not first-error-only.
    resolved, root = _resolved(tmp_path, {"wrist_pitch": -3.0, "ghost": 1.0})

    with pytest.raises(SceneBuildError) as exc:
        build_scene(resolved, root)

    assert any("outside its declared limit" in e for e in exc.value.errors)
    assert any("unknown joint 'ghost'" in e for e in exc.value.errors)
