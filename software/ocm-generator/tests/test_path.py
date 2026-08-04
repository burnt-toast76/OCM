# SPDX-License-Identifier: AGPL-3.0-or-later
"""planner/path's segment checkers -- check_actuation_segment (ADR-0029
D6) alongside check_joint_segment. The interpolation/raising machinery is
tested everywhere with the Bullet backend stubbed (`no_collision_backend`
or a planted-violation stand-in); the one test of REAL contact math is
tesseract-gated, because CI never installs the extra."""

from __future__ import annotations

from pathlib import Path

import pytest

from ocm_core.cell import Cell
from ocm_generator.planner.errors import PathCollisionError
from ocm_generator.planner.path import check_actuation_segment
from ocm_generator.scene import build_scene
from ocm_resolve import resolve_cell

from .conftest import base_fragment_xml, build_cell_dict, fragment_xml, minimal_base_manifest, minimal_robot_manifest, write_module

# Two independently-driven prismatic joints (obviously-synthetic values;
# ADR-0014 -- a real module's strokes are the owner's to state).
_JAWS_FRAGMENT = """<?xml version="1.0"?>
<robot name="frag">
  <link name="origin"><collision><geometry><box size="0.05 0.05 0.05"/></geometry></collision></link>
  <link name="jaw_a"><collision><geometry><box size="0.02 0.02 0.02"/></geometry></collision></link>
  <link name="jaw_b"><collision><geometry><box size="0.02 0.02 0.02"/></geometry></collision></link>
  <joint name="slide_a" type="prismatic">
    <parent link="origin"/><child link="jaw_a"/>
    <axis xyz="1 0 0"/>
    <limit lower="0.0" upper="0.2" effort="10" velocity="0.1"/>
  </joint>
  <joint name="slide_b" type="prismatic">
    <parent link="origin"/><child link="jaw_b"/>
    <axis xyz="0 1 0"/>
    <limit lower="0.0" upper="0.2" effort="10" velocity="0.1"/>
  </joint>
</robot>"""


def _jaws_manifest() -> dict:
    return {
        "ocm_version": "1.1",
        "id": "com.example.fixture.twoslide",
        "revision": "1.0.0",
        "kind": "fixture",
        "license": "CERN-OHL-S-2.0",
        "name": "Two-slide Test Fixture",
        "mechanical": {
            "mount": {"interface": "custom"},
            "frames": {"origin": {"xyz_mm": [0, 0, 0]}},
            "geometry": {"urdf_fragment": "fix.urdf"},
            "mass_kg": 3.0,
        },
        "state_machine": {"model": "packml", "abort_safe": True},
    }


def _scene(tmp_path: Path, fix_pose_xyz_mm=(600, 300, 0), extra_modules=None):
    root = tmp_path / "modules"
    write_module(root, minimal_base_manifest(), "base.urdf", base_fragment_xml("origin"))
    write_module(root, minimal_robot_manifest(), "robot.urdf", fragment_xml("origin", extra_link="flange", extra_xyz=(0.0, 0.0, 0.4)))
    write_module(root, _jaws_manifest(), "fix.urdf", _JAWS_FRAGMENT)
    modules = [
        {"instance": "robot1", "module": "com.example.robot.tiny@1.0.0", "mount": {"pose": {"xyz_mm": [400, 300, 0], "rpy_deg": [0, 0, 0]}}},
        {"instance": "fix1", "module": "com.example.fixture.twoslide@1.0.0", "mount": {"pose": {"xyz_mm": list(fix_pose_xyz_mm), "rpy_deg": [0, 0, 0]}}},
    ]
    modules.extend(extra_modules or [])
    cell = Cell.from_dict(build_cell_dict(modules=modules))
    resolved = resolve_cell(cell, root)
    return build_scene(resolved, root)


def test_all_actuated_joints_interpolate_together(tmp_path: Path, no_collision_backend: None):
    scene = _scene(tmp_path)
    frames = check_actuation_segment(
        scene,
        label="fix1.clamp",
        start={"fix1__slide_a": 0.0, "fix1__slide_b": 0.0},
        end={"fix1__slide_a": 0.1, "fix1__slide_b": 0.2},
        samples=5,
    )

    # One verb, one sweep: both joints move across the SAME sample set.
    assert len(frames) == 5
    assert [f["fix1__slide_a"] for f in frames] == pytest.approx([0.0, 0.025, 0.05, 0.075, 0.1])
    assert [f["fix1__slide_b"] for f in frames] == pytest.approx([0.0, 0.05, 0.1, 0.15, 0.2])
    # Each frame is the FULL namespaced state, not just the actuated pair
    # -- same contract as check_joint_segment.
    for frame in frames:
        for key, value in scene.joint_state.items():
            assert frame[key] == value


def test_a_planted_violation_raises_naming_the_rows_label(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from ocm_generator.scene.collision import CollisionCheckResult, Contact

    scene = _scene(tmp_path)

    def backend(sample_scene, contact_distance_mm=1.0):
        # The backend stand-in reports contact once the jaw passes 60 mm --
        # the checker's job (walk, raise, name the label) is what's under test.
        if sample_scene.joint_state.get("fix1__slide_a", 0.0) > 0.06:
            contact = Contact(
                instance_a="fix1", instance_b="robot1",
                link_a="fix1__jaw_a", link_b="robot1__origin",
                distance_mm=-2.0, is_violation=True,
            )
            return CollisionCheckResult(contacts=(contact,), margin_mm=contact_distance_mm)
        return CollisionCheckResult(contacts=(), margin_mm=contact_distance_mm)

    monkeypatch.setattr("ocm_generator.planner.path.check_collisions", backend)

    with pytest.raises(PathCollisionError) as exc:
        check_actuation_segment(
            scene,
            label="fix1.clamp",
            start={"fix1__slide_a": 0.0},
            end={"fix1__slide_a": 0.1},
            samples=11,
        )

    assert exc.value.segment == "fix1.clamp"
    assert {exc.value.instance_a, exc.value.instance_b} == {"fix1", "robot1"}
    assert 0.0 < exc.value.fraction < 1.0


def test_a_real_sweep_into_another_instance_is_refused(tmp_path: Path):
    # The one REAL-contact test (tesseract-gated; CI skips it): fix1's
    # jaw_a slides +X toward a block 100 mm away and punches into it.
    pytest.importorskip("tesseract_robotics")

    obstacle_manifest = {
        "ocm_version": "1.0",
        "id": "com.example.obstacle.block",
        "revision": "1.0.0",
        "kind": "fixture",
        "license": "CERN-OHL-S-2.0",
        "name": "Test obstacle block",
        "mechanical": {
            "mount": {"interface": "custom"},
            "frames": {"origin": {"xyz_mm": [0, 0, 0]}},
            "geometry": {"urdf_fragment": "block.urdf"},
            "mass_kg": 1.0,
        },
        "state_machine": {"model": "packml", "abort_safe": True},
    }
    root = tmp_path / "modules"
    write_module(root, obstacle_manifest, "block.urdf", fragment_xml("origin"))
    obstacle = {"instance": "blocker", "module": "com.example.obstacle.block@1.0.0", "mount": {"pose": {"xyz_mm": [700, 300, 0], "rpy_deg": [0, 0, 0]}}}
    scene = _scene(tmp_path, extra_modules=[obstacle])

    # Clear at 0, colliding by 100 mm of travel (the block sits 100 mm +X
    # of fix1's origin; jaw_a's own box is 20 mm wide, the block 50 mm).
    with pytest.raises(PathCollisionError) as exc:
        check_actuation_segment(
            scene,
            label="fix1.grab",
            start={"fix1__slide_a": 0.0},
            end={"fix1__slide_a": 0.12},
            samples=13,
        )

    assert exc.value.segment == "fix1.grab"
    assert {exc.value.instance_a, exc.value.instance_b} == {"fix1", "blocker"}
