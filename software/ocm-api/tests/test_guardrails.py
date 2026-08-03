# SPDX-License-Identifier: AGPL-3.0-or-later
"""Two cell-editing guardrails found by cold-testing the composition
verbs: place_instance never evicts/swaps onto an already-occupied tool
mount (TOOL_SLOT_OCCUPIED), and a mutation that orphans a plan step or a
stale `tool:` cross-reference says so in `warnings[]`, on the same call
that causes it -- whether or not that call also ends up refused for
other, harder reasons.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from ocm_api import Codes, OcmApi


def _place_robot_and_sd1(api: OcmApi, cell_id: str) -> None:
    api.create_cell(cell_id, "com.accelsolutions.base.frame1200@2.0.0")
    api.place_instance(cell_id, "robot1", "com.universal-robots.ur5e@3.1.0", {"pose": {"xyz_mm": [400, 300, 0], "rpy_deg": [0, 0, 0]}})
    api.set_joint_state(cell_id, "robot1", {"shoulder_lift_joint": -1.5707963267948966, "elbow_joint": 1.5707963267948966})
    # ADR-0023: sd50's drive_screw declares requires.workpiece_secured, so
    # the cell must bind it or resolve refuses REQUIREMENT_UNBOUND. These
    # fixtures exercise mount-slot / orphan guardrails, not the interlock
    # itself, and don't place a holding fixture -- bind to sd1's own
    # screw_present (an input bool that exists here) so resolve is satisfied.
    e = api.place_instance(
        cell_id,
        "sd1",
        "com.accelsolutions.screwdriver.sd50@1.2.0",
        {"on": "robot1.flange"},
        requires={"workpiece_secured": "sd1.screw_present"},
    )
    assert e.ok, e.refusals


# ---------------------------------------------------------------------------
# TOOL_SLOT_OCCUPIED
# ---------------------------------------------------------------------------


def test_place_instance_onto_occupied_mount_is_refused(api: OcmApi):
    _place_robot_and_sd1(api, "c-slot1")

    e = api.place_instance("c-slot1", "grip1", "com.acme.gripper.vg25@1.0.0", {"on": "robot1.flange"})

    assert not e.ok
    assert e.refusals[0].code == Codes.TOOL_SLOT_OCCUPIED
    assert "'sd1'" in e.refusals[0].hint  # names the incumbent
    assert "robot1.flange" in e.refusals[0].message
    assert e.refusals[0].allowed == {"incumbent": "sd1", "mount_on": "robot1.flange"}


def test_place_instance_onto_occupied_mount_does_not_evict_the_incumbent(api: OcmApi, workspace_root: Path):
    _place_robot_and_sd1(api, "c-slot2")
    api.place_instance("c-slot2", "grip1", "com.acme.gripper.vg25@1.0.0", {"on": "robot1.flange"})

    cell_doc = yaml.safe_load((workspace_root / "cells" / "c-slot2" / "cell.yaml").read_text(encoding="utf-8"))
    instances = {m["instance"] for m in cell_doc["modules"]}
    assert "sd1" in instances  # still there, untouched
    assert "grip1" not in instances  # never landed


def test_move_instance_onto_occupied_mount_is_refused(api: OcmApi):
    _place_robot_and_sd1(api, "c-slot3")
    api.place_instance("c-slot3", "cam1", "com.lmi.gocator.2350@1.0.0", {"pose": {"xyz_mm": [640, 300, 900], "rpy_deg": [180, 0, 0]}})

    e = api.move_instance("c-slot3", "cam1", {"on": "robot1.flange"})

    assert not e.ok
    assert e.refusals[0].code == Codes.TOOL_SLOT_OCCUPIED
    assert "'sd1'" in e.refusals[0].hint


def test_move_instance_can_still_reposition_its_own_occupied_slot(api: OcmApi):
    # Moving an instance that's ALREADY the incumbent of a mount to a new
    # pose on that same mount.on string is not a conflict with itself.
    _place_robot_and_sd1(api, "c-slot4")

    e = api.move_instance("c-slot4", "sd1", {"on": "robot1.flange"})

    assert e.ok, e.refusals


# ---------------------------------------------------------------------------
# Orphaned plan steps / stale tool: references
# ---------------------------------------------------------------------------


def test_remove_instance_orphans_plan_steps_warning_appears_on_the_same_call(api: OcmApi):
    _place_robot_and_sd1(api, "c-orphan1")
    api.place_instance("c-orphan1", "nest1", "com.accelsolutions.fixture.pneumatic-nest@1.1.0", {"pose": {"xyz_mm": [640, 300, 0], "rpy_deg": [0, 0, 90]}})
    plan = [
        {"step": "clamp", "module": "nest1", "op": "clamp", "params": {"force_n": 120}},
        {
            "step": "fasten",
            "for_each": ["hole_1", "hole_2", "hole_3"],
            "sequence": [
                {"module": "sd1", "op": "load_screw"},
                {"module": "sd1", "op": "drive_screw", "at": "part.features.${item}", "params": {"torque_nm": 2.4, "depth_mm": 8.0}},
            ],
        },
    ]
    set_plan_result = api.set_plan(
        "c-orphan1", plan,
        part={"id": "P1", "features": {"hole_1": {"xyz_mm": [0, 0, 0], "normal": [0, 0, 1]}, "hole_2": {"xyz_mm": [10, 0, 0], "normal": [0, 0, 1]}, "hole_3": {"xyz_mm": [20, 0, 0], "normal": [0, 0, 1]}}},
    )
    assert set_plan_result.ok, set_plan_result.refusals

    e = api.remove_instance("c-orphan1", "sd1")

    # Removing sd1 leaves 3 plan steps (load_screw + drive_screw x3 = 6
    # sequence entries total, but only the ones naming sd1) referencing a
    # module instance that no longer exists -- resolve_cell's own
    # UNKNOWN_MODULE check correctly refuses this (the plan genuinely
    # can't resolve any more), but the SAME call also carries the
    # human-readable summary of what just broke, not just six separate
    # per-step errors.
    assert not e.ok
    assert any(r.code == Codes.UNKNOWN_MODULE for r in e.refusals)
    assert any("orphans" in w and "sd1" in w for w in e.warnings)


def test_remove_instance_with_no_plan_reference_has_no_orphan_warning(api: OcmApi):
    _place_robot_and_sd1(api, "c-orphan2")
    api.place_instance("c-orphan2", "cam1", "com.lmi.gocator.2350@1.0.0", {"pose": {"xyz_mm": [640, 300, 900], "rpy_deg": [180, 0, 0]}})
    # No plan references cam1 at all.

    e = api.remove_instance("c-orphan2", "cam1")

    assert e.ok, e.refusals
    assert e.warnings == ()


def test_remove_instance_orphans_a_stale_tool_field_even_when_ok_true(api: OcmApi, workspace_root: Path):
    # robot1's `tool:` field (spec/02's "which end effector is currently
    # mounted" convention, e.g. the real bracket-asm-01's `tool: grip1`)
    # is metadata resolve_cell never cross-checks -- removing the
    # instance it names would silently succeed with a now-dangling
    # reference if nothing else flagged it.
    _place_robot_and_sd1(api, "c-orphan3")
    cell_path = workspace_root / "cells" / "c-orphan3" / "cell.yaml"
    cell_doc = yaml.safe_load(cell_path.read_text(encoding="utf-8"))
    robot1 = next(m for m in cell_doc["modules"] if m["instance"] == "robot1")
    robot1["tool"] = "sd1"
    cell_path.write_text(yaml.safe_dump(cell_doc, sort_keys=False), encoding="utf-8")

    e = api.remove_instance("c-orphan3", "sd1")

    assert e.ok, e.refusals  # nothing else references sd1 -- resolves fine
    assert any("robot1.tool" in w and "sd1" in w for w in e.warnings)
