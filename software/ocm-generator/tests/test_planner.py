# SPDX-License-Identifier: AGPL-3.0-or-later
"""ocm_generator.planner / ocm_generator.emitters -- `ocm plan
--emit-urscript`'s pipeline: standoff/contact/retract poses from a part
feature + a capability's motion block, UR analytic IK reachability
(branch-consistent across the WHOLE for_each fastening sequence, not just
per-pose), a collision-checked joint-space path for every segment of that
sequence, URScript emission, and a cycle-time estimate. Guarded by the
optional `tesseract` extra, same as test_collision.py.
"""

from __future__ import annotations

import math
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

pytest.importorskip("tesseract_robotics")

from ocm_core.cell import Cell  # noqa: E402
from ocm_generator.emitters import emit_urscript, render_cycle_time_table  # noqa: E402
from ocm_generator.planner import (  # noqa: E402
    UR_JOINT_ORDER,
    PathCollisionError,
    PoseUnreachableError,
    estimate_cycle_time,
    find_fastening_plan,
    plan_fastening_sequence,
)
from ocm_generator.scene import build_scene  # noqa: E402
from ocm_resolve import resolve_cell  # noqa: E402

# The same folded home pose the real bracket-asm-01 cell commits, for the
# same reason (see cells/bracket-asm-01/cell.yaml's own comment): the
# all-zero default pokes sd1 through the guard wall.
_HOME_JOINT_STATE = {"shoulder_lift_joint": -1.5707963267948966, "elbow_joint": 1.5707963267948966}


def _planner_cell_dict(
    features: dict[str, list[float]],
    for_each: list[str],
    extra_modules: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """A cell built from the real UR5e/sd50/pneumatic-nest/frame1200
    modules -- IK is UR5e-specific (URInvKinFactory's `model: UR5e`) and
    part_datum is pneumatic-nest's own frame, so these can't be swapped for
    the tiny synthetic manifests conftest.py uses elsewhere. Deliberately
    has no vision camera (unlike the real bracket-asm-01 cell) -- with one
    present, the straight-line home->standoff joint interpolation for
    every hole on the real part sweeps robot1's wrist through it (an
    empirically real finding, not a bug -- see the module docstring of
    .planner.path), which would make every test here about the camera
    instead of about what it's actually testing.
    """
    modules = [
        {
            "instance": "robot1",
            "module": "com.universal-robots.ur5e@3.1.0",
            "mount": {"station": [400, 300], "pose": {"xyz_mm": [400, 300, 0], "rpy_deg": [0, 0, 0]}},
            "joint_state": dict(_HOME_JOINT_STATE),
        },
        {"instance": "sd1", "module": "com.accelsolutions.screwdriver.sd50@1.2.0", "mount": {"on": "robot1.flange"}},
        {
            "instance": "nest1",
            "module": "com.accelsolutions.fixture.pneumatic-nest@1.1.0",
            "mount": {"pose": {"xyz_mm": [640, 300, 0], "rpy_deg": [0, 0, 90]}},
        },
    ]
    modules.extend(extra_modules or [])

    return {
        "ocm_version": "1.0",
        "kind": "cell",
        "id": "com.example.cell.planner-test",
        "name": "Planner test cell",
        "license": "CERN-OHL-S-2.0",
        "base": {"module": "com.accelsolutions.base.frame1200@2.0.0", "datum": "cell_origin", "grid": "ocm-base-grid-50"},
        "modules": modules,
        "part": {
            "id": "BRK-TEST",
            "cad": "cad/BRK-TEST.step",
            "features": {name: {"xyz_mm": xyz, "normal": [0, 0, 1]} for name, xyz in features.items()},
        },
        "plan": [
            {"step": "clamp", "module": "nest1", "op": "clamp", "params": {"force_n": 120}},
            {
                "step": "fasten",
                "for_each": for_each,
                "sequence": [
                    {"module": "sd1", "op": "load_screw"},
                    {
                        "module": "sd1",
                        "op": "drive_screw",
                        "at": "part.features.${item}",
                        "params": {"torque_nm": 2.4, "depth_mm": 8.0},
                        "on_fail": [{"module": "sd1", "op": "eject_screw"}, {"action": "reject_part"}],
                    },
                ],
            },
            {"step": "release", "module": "nest1", "op": "unclamp"},
        ],
    }


def _planner_scene(
    modules_root: Path,
    features: dict[str, list[float]],
    for_each: list[str],
    extra_modules: list[dict[str, Any]] | None = None,
):
    cell = Cell.from_dict(_planner_cell_dict(features, for_each, extra_modules))
    resolved = resolve_cell(cell, modules_root)
    scene = build_scene(resolved, modules_root)
    return resolved, scene


# The three real holes from cells/bracket-asm-01/cell.yaml's own part block
# -- reused here (without the camera in the way) so "the bracket cell's
# three holes" means something concrete and traceable back to the real cell.
_BRACKET_HOLES = {
    "hole_1": [12, 12, 0],
    "hole_2": [12, 88, 0],
    "hole_3": [64, 50, 0],
}


# ---------------------------------------------------------------------------
# (a) a 3-hole cell emits 3 approach groups in order, with direct transits
# ---------------------------------------------------------------------------


def test_three_hole_cell_emits_three_approach_groups_in_order_with_direct_transits(repo_root: Path):
    resolved, scene = _planner_scene(repo_root / "modules", _BRACKET_HOLES, ["hole_1", "hole_2", "hole_3"])

    plan = plan_fastening_sequence(resolved, scene)

    assert [h.hole_id for h in plan.holes] == ["hole_1", "hole_2", "hole_3"]

    # Every hole's own standoff/contact/retract IK-solved and present.
    for hole in plan.holes:
        assert len(hole.standoff_joints) == len(UR_JOINT_ORDER) == 6
        assert len(hole.contact_joints) == len(UR_JOINT_ORDER)
        assert len(hole.retract_joints) == len(UR_JOINT_ORDER)

    # Direct transits: retract_i -> standoff_{i+1}, never back through home.
    transit_labels = [s.label for s in plan.segments if s.kind == "transit"]
    assert transit_labels == [
        "home -> standoff_1",
        "retract_1 -> standoff_2",
        "retract_2 -> standoff_3",
        "retract_3 -> home",
    ]

    script = emit_urscript(plan)
    lines = script.splitlines()

    # Exactly one movej home at the very end -- no home in between holes.
    movej_lines = [ln for ln in lines if ln.startswith("movej(")]
    assert len(movej_lines) == 4  # standoff_1, standoff_2, standoff_3, home
    assert lines[-1].startswith("movej(")

    # Three approach groups, in order: standoff/contact/handshake/retract each.
    for hole_id in ("hole_1", "hole_2", "hole_3"):
        assert f"# TODO PLC handshake: drive_screw @ {hole_id}" in lines
    # load_screw's handshake precedes each hole's own transit movej.
    load_lines = [i for i, ln in enumerate(lines) if ln == "# PLC handshake: load_screw (overlaps following transit)"]
    assert len(load_lines) == 3
    for i in load_lines:
        assert lines[i + 1].startswith("movej(")

    # Every movej/movel call is syntactically closed BEFORE its trailing
    # comment -- regression test for a real bug hit during development,
    # where the joint-names comment landed inside the call and swallowed
    # its closing ')'.
    for ln in lines:
        if ln.startswith("movej(") or ln.startswith("movel("):
            code = ln.split("#")[0].rstrip()
            assert code.endswith(")"), f"line has no real closing paren before its comment: {ln!r}"

    # Cycle-time table renders without error and adds up sanely.
    report = estimate_cycle_time(plan)
    assert report.naive_serial_total_s >= report.overlapped_total_s >= 0
    assert report.savings_s == pytest.approx(report.naive_serial_total_s - report.overlapped_total_s)
    table = render_cycle_time_table(plan, report)
    assert "naive serial total" in table
    assert "overlap savings" in table


# ---------------------------------------------------------------------------
# ${item} substitution
# ---------------------------------------------------------------------------


def test_item_substitution_binds_each_for_each_item_into_at(repo_root: Path):
    cell = Cell.from_dict(_planner_cell_dict(_BRACKET_HOLES, ["hole_2", "hole_3", "hole_1"]))

    fasten = find_fastening_plan(cell)

    assert [s.hole_id for s in fasten.steps] == ["hole_2", "hole_3", "hole_1"]
    assert [s.at_path for s in fasten.steps] == [
        "part.features.hole_2",
        "part.features.hole_3",
        "part.features.hole_1",
    ]
    assert fasten.load_screw_module == "sd1"
    assert fasten.on_fail_summary == "eject_screw, reject_part"


# ---------------------------------------------------------------------------
# Branch consistency across the bracket cell's three holes
# ---------------------------------------------------------------------------


def test_no_consecutive_configuration_swings_more_than_a_branch_flip_would(repo_root: Path):
    # Empirically, home sits exactly on the UR5e's own wrist singularity
    # (wrist_2 = 0 -- the folded pose cell.yaml commits): the two segments
    # touching home (home->standoff_1, retract_3->home) each swing
    # wrist_2 by exactly 90.00 degrees, a real and legitimate consequence
    # of leaving/returning to that singularity, not a branch-selection
    # bug -- every other (hole-to-hole, approach, withdraw) segment stays
    # well under 35 degrees. The threshold below sits comfortably above
    # that genuine 90-degree edge case while still well below the ~180
    # degree swing a real branch flip would produce (a different, wrong
    # solution reachable for the same pose -- see .plan's own module
    # docstring on why every pose is seeded from its immediate
    # predecessor specifically to prevent that).
    resolved, scene = _planner_scene(repo_root / "modules", _BRACKET_HOLES, ["hole_1", "hole_2", "hole_3"])

    plan = plan_fastening_sequence(resolved, scene)

    configs = [plan.home_joints]
    for hole in plan.holes:
        configs += [hole.standoff_joints, hole.contact_joints, hole.retract_joints]
    configs.append(plan.home_joints)

    for a, b in zip(configs, configs[1:]):
        max_delta_deg = math.degrees(max(abs(x - y) for x, y in zip(a, b)))
        assert max_delta_deg < 120.0, f"suspiciously large joint swing ({max_delta_deg:.1f} deg) -- possible branch flip"


# ---------------------------------------------------------------------------
# A hole outside reach is refused, naming the pose (index included)
# ---------------------------------------------------------------------------


def test_a_hole_outside_reach_is_refused_naming_the_pose(repo_root: Path):
    # hole_2 (the second for_each item) is 9m away -- unreachable by any
    # stretch; hole_1 stays reachable, so this also proves the refusal
    # happens mid-chain, not just for a first/only item.
    features = {"hole_1": [12, 12, 0], "hole_2": [9000, 9000, 0]}
    resolved, scene = _planner_scene(repo_root / "modules", features, ["hole_1", "hole_2"])

    with pytest.raises(PoseUnreachableError) as exc:
        plan_fastening_sequence(resolved, scene)

    assert exc.value.pose_name == "standoff_2"
    assert "standoff_2" in str(exc.value)


# ---------------------------------------------------------------------------
# A single-hole cell still plans cleanly (keeps the original single-hole
# behavior working through the new multi-hole API).
# ---------------------------------------------------------------------------


def test_a_single_hole_cell_still_emits_a_clean_script(repo_root: Path):
    resolved, scene = _planner_scene(repo_root / "modules", {"hole_1": [12, 12, 0]}, ["hole_1"])

    plan = plan_fastening_sequence(resolved, scene)

    assert len(plan.holes) == 1
    assert plan.holes[0].hole_id == "hole_1"
    assert plan.approach_speed_m_s == pytest.approx(0.020)

    script = emit_urscript(plan)
    lines = script.splitlines()
    # header, on_fail note, load_screw handshake, movej standoff, movel
    # contact, drive_screw handshake, movel retract, movej home.
    assert lines[3].startswith("movej(")
    assert lines[4].startswith("movel(") and "v=0.020000" in lines[4]
    assert lines[5] == "# TODO PLC handshake: drive_screw @ hole_1"
    assert lines[6].startswith("movel(")
    assert lines[7].startswith("movej(")


# ---------------------------------------------------------------------------
# A fixture where a transit collides is refused, naming the segment
# ---------------------------------------------------------------------------


@pytest.fixture
def modules_root_with_obstacle(tmp_path: Path, repo_root: Path) -> Path:
    """A copy of the real modules/ directory (needed since IK/part_datum
    are tied to the real UR5e/pneumatic-nest modules -- see
    _planner_cell_dict's own docstring) plus one extra synthetic module: a
    100mm collision box with no capabilities, mountable anywhere via
    mount.pose like any other fixture.
    """
    modules_root = tmp_path / "modules"
    shutil.copytree(repo_root / "modules", modules_root)

    obstacle_dir = modules_root / "com.example.obstacle.block"
    obstacle_dir.mkdir()
    manifest = {
        "ocm_version": "1.0",
        "id": "com.example.obstacle.block",
        "revision": "1.0.0",
        "kind": "fixture",
        "license": "CERN-OHL-S-2.0",
        "name": "Test obstacle block",
        "mechanical": {
            "mount": {"interface": "custom"},
            "frames": {"origin": {"xyz_mm": [0, 0, 0]}},
            "geometry": {"collision": "meshes/block.stl", "urdf_fragment": "block.urdf"},
            "mass_kg": 1.0,
        },
        "state_machine": {"model": "packml", "abort_safe": True},
    }
    (obstacle_dir / "module.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    (obstacle_dir / "block.urdf").write_text(
        """<?xml version="1.0"?>
<robot name="frag">
  <link name="origin">
    <collision><geometry><box size="0.1 0.1 0.1"/></geometry></collision>
  </link>
</robot>""",
        encoding="utf-8",
    )
    return modules_root


def test_a_transit_that_collides_is_refused_naming_the_segment(modules_root_with_obstacle: Path):
    # hole_1 and hole_2 are placed far apart specifically so their
    # retract_1 -> standoff_2 transit sweeps through open space distinct
    # from every other segment (found empirically, the same way this
    # project's folded home joint_state was -- see
    # cells/bracket-asm-01/cell.yaml's own comment on that). The obstacle
    # sits squarely in that swept corridor (~160mm clearance to every
    # other segment at its closest point) but nowhere near home,
    # standoff_1, or standoff_2 themselves -- individually, both endpoints
    # are clear; only the straight line between them punches through it.
    features = {"hole_1": [12, 12, 0], "hole_2": [300, 200, 0]}
    obstacle = {
        "instance": "blocker",
        "module": "com.example.obstacle.block@1.0.0",
        "mount": {"pose": {"xyz_mm": [598.5, 473.9, 281.8], "rpy_deg": [0, 0, 0]}},
    }
    resolved, scene = _planner_scene(modules_root_with_obstacle, features, ["hole_1", "hole_2"], extra_modules=[obstacle])

    with pytest.raises(PathCollisionError) as exc:
        plan_fastening_sequence(resolved, scene)

    assert exc.value.segment == "retract_1 -> standoff_2"
    assert {exc.value.instance_a, exc.value.instance_b} == {"blocker", "robot1"}
    assert 0.0 < exc.value.fraction < 1.0
