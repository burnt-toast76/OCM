# SPDX-License-Identifier: AGPL-3.0-or-later
"""ocm_generator.planner / ocm_generator.emitters -- `ocm plan
--emit-urscript`'s pipeline: standoff/contact/retract poses from a part
feature + a capability's motion block, UR analytic IK reachability, a
collision-checked home->standoff joint-space path, and URScript emission.
Guarded by the optional `tesseract` extra, same as test_collision.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("tesseract_robotics")

from ocm_core import load_cell  # noqa: E402
from ocm_core.cell import Cell  # noqa: E402
from ocm_generator.emitters import emit_urscript  # noqa: E402
from ocm_generator.planner import (  # noqa: E402
    UR_JOINT_ORDER,
    PathCollisionError,
    PoseUnreachableError,
    plan_drive_screw,
)
from ocm_generator.scene import build_scene  # noqa: E402
from ocm_resolve import resolve_cell  # noqa: E402


def _planner_cell_dict(hole_xyz_mm: list[float]) -> dict[str, Any]:
    """A minimal cell built from the real UR5e/sd50/pneumatic-nest/frame1200
    modules -- IK is UR5e-specific (URInvKinFactory's `model: UR5e`) and
    part_datum is pneumatic-nest's own frame, so these can't be swapped for
    the tiny synthetic manifests conftest.py uses elsewhere. Deliberately
    has no vision camera (unlike the real bracket-asm-01 cell) -- see
    test_a_reachable_hole_emits a_script's own comment for why.
    """
    return {
        "ocm_version": "1.0",
        "kind": "cell",
        "id": "com.example.cell.planner-test",
        "name": "Planner test cell",
        "license": "CERN-OHL-S-2.0",
        "base": {"module": "com.accelsolutions.base.frame1200@2.0.0", "datum": "cell_origin", "grid": "ocm-base-grid-50"},
        "modules": [
            {
                "instance": "robot1",
                "module": "com.universal-robots.ur5e@3.1.0",
                "mount": {"station": [400, 300], "pose": {"xyz_mm": [400, 300, 0], "rpy_deg": [0, 0, 0]}},
                # Same folded home pose the real bracket-asm-01 cell commits, for the
                # same reason (see cells/bracket-asm-01/cell.yaml's own comment):
                # the all-zero default pokes sd1 through the guard wall.
                "joint_state": {
                    "shoulder_lift_joint": -1.5707963267948966,
                    "elbow_joint": 1.5707963267948966,
                },
            },
            {"instance": "sd1", "module": "com.accelsolutions.screwdriver.sd50@1.2.0", "mount": {"on": "robot1.flange"}},
            {
                "instance": "nest1",
                "module": "com.accelsolutions.fixture.pneumatic-nest@1.1.0",
                "mount": {"pose": {"xyz_mm": [640, 300, 0], "rpy_deg": [0, 0, 90]}},
            },
        ],
        "part": {"id": "BRK-TEST", "cad": "cad/BRK-TEST.step", "features": {"hole_1": {"xyz_mm": hole_xyz_mm, "normal": [0, 0, 1]}}},
        "plan": [
            {"step": "clamp", "module": "nest1", "op": "clamp", "params": {"force_n": 120}},
            {
                "step": "fasten",
                "for_each": ["hole_1"],
                "sequence": [
                    {
                        "module": "sd1",
                        "op": "drive_screw",
                        "at": "part.features.${item}",
                        "params": {"torque_nm": 2.4, "depth_mm": 8.0},
                        "on_fail": [{"module": "sd1", "op": "eject_screw"}, {"action": "reject_part"}],
                    }
                ],
            },
            {"step": "release", "module": "nest1", "op": "unclamp"},
        ],
    }


def _planner_scene(repo_root: Path, hole_xyz_mm: list[float]):
    cell = Cell.from_dict(_planner_cell_dict(hole_xyz_mm))
    resolved = resolve_cell(cell, repo_root / "modules")
    scene = build_scene(resolved, repo_root / "modules")
    return resolved, scene


# ---------------------------------------------------------------------------
# (a) a reachable hole emits a script
# ---------------------------------------------------------------------------


def test_a_reachable_hole_emits_a_script(repo_root: Path):
    # This cell has no vision camera (unlike the real bracket-asm-01 cell,
    # which mounts cam1 directly over the workspace) -- with it present,
    # the straight-line home->standoff joint interpolation for EVERY hole
    # on the real part sweeps robot1's wrist through cam1 (see
    # test_the_real_bracket_cells_straight_line_path_is_refused below);
    # that's this checker doing exactly its job, not a bug to work around
    # here. This variant isolates "a reachable hole with a clear path"
    # instead of also re-proving the camera finding.
    resolved, scene = _planner_scene(repo_root, [12, 12, 0])

    plan = plan_drive_screw(resolved, scene)

    assert plan.tool_instance == "sd1"
    assert plan.hole_id == "hole_1"
    assert len(plan.standoff_joints) == len(UR_JOINT_ORDER) == 6
    assert plan.approach_speed_m_s == pytest.approx(0.020)

    script = emit_urscript(plan)

    lines = script.splitlines()
    assert lines[1].startswith("movej(")
    assert lines[2].startswith("movel(") and "v=0.020000" in lines[2]
    assert lines[3] == "# TODO PLC handshake: drive_screw"
    assert lines[4].startswith("movel(")
    assert lines[5].startswith("movej(")
    for name in UR_JOINT_ORDER:
        assert name in lines[1]
        assert name in lines[5]
    # Every movej/movel call is syntactically closed BEFORE its trailing
    # comment -- regression test for a real bug hit during development,
    # where the joint-names comment landed inside the call and swallowed
    # its closing ')'.
    for line in (lines[1], lines[2], lines[4], lines[5]):
        code = line.split("#")[0].rstrip()
        assert code.endswith(")"), f"line has no real closing paren before its comment: {line!r}"


# ---------------------------------------------------------------------------
# (b) a hole outside the robot's reach is refused
# ---------------------------------------------------------------------------


def test_a_hole_outside_reach_is_refused_naming_the_pose(repo_root: Path):
    # A UR5e's reach is ~850mm; 9m away is unreachable by any stretch.
    resolved, scene = _planner_scene(repo_root, [9000, 9000, 0])

    with pytest.raises(PoseUnreachableError) as exc:
        plan_drive_screw(resolved, scene)

    assert exc.value.pose_name == "standoff"
    assert "standoff" in str(exc.value)


# ---------------------------------------------------------------------------
# (c) a straight-line path that collides is refused, naming the pair
# ---------------------------------------------------------------------------


def test_the_real_bracket_cells_straight_line_path_is_refused(repo_root: Path):
    # The real, committed bracket-asm-01 cell -- no synthetic obstacle
    # needed. cam1 (the vision camera) is mounted directly over the
    # workspace (xyz_mm=[640,300,420]); the straight joint-space line from
    # robot1's folded home pose to hole_1's standoff swings
    # wrist_2_link/wrist_1_link straight through it partway along the path,
    # even though home (parked, clear of everything -- see
    # test_scene_build_real_bracket_cell.py) and the standoff itself
    # (offset 25mm clear of the part) are each individually fine. That's
    # precisely the "refuse a straight line rather than route around it"
    # case this checker exists for -- see .planner.path's module docstring.
    cell = load_cell(repo_root / "cells" / "bracket-asm-01" / "cell.yaml")
    resolved = resolve_cell(cell, repo_root / "modules")
    scene = build_scene(resolved, repo_root / "modules")

    with pytest.raises(PathCollisionError) as exc:
        plan_drive_screw(resolved, scene)

    assert {exc.value.instance_a, exc.value.instance_b} == {"cam1", "robot1"}
    assert 0.0 < exc.value.fraction < 1.0
