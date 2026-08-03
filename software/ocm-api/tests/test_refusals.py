# SPDX-License-Identifier: AGPL-3.0-or-later
"""One test per refusal code the envelope can carry (spec/09's own two --
PARAM_OUT_OF_BOUNDS, HUMAN_SIGNATURE_REQUIRED -- plus every scenario the
spec describes narratively without naming a literal code: unknown module,
dangling mount.on, workspace overhang, ...), the verified_by hard rule,
and draft-vs-published resolution.

Every refusal asserted here checks the FULL envelope shape (ok=False,
`refusals` non-empty, each with code/path/message), not just the code --
spec/09 design principle #1 is the shape, not any one field of it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ocm_api import Codes, OcmApi

from .conftest import build_two_hole_cell_with_obstacle, write_obstacle_module


def _assert_envelope_shape(envelope, code: str) -> None:
    assert envelope.ok is False
    assert envelope.refusals, "expected at least one refusal"
    assert all(r.code and r.path and r.message for r in envelope.refusals)
    assert any(r.code == code for r in envelope.refusals), [(r.code, r.message) for r in envelope.refusals]
    d = envelope.to_dict()
    assert d["ok"] is False
    assert isinstance(d["refusals"], list) and d["refusals"]
    assert isinstance(d["warnings"], list)
    assert d["data"] is None


# ---------------------------------------------------------------------------
# spec/09's own two named codes
# ---------------------------------------------------------------------------


def test_param_out_of_bounds(api: OcmApi):
    api.create_cell("c1", "com.accelsolutions.base.frame1200@2.0.0")
    api.place_instance("c1", "robot1", "com.universal-robots.ur5e@3.1.0", {"pose": {"xyz_mm": [400, 300, 0], "rpy_deg": [0, 0, 0]}})
    api.place_instance("c1", "sd1", "com.accelsolutions.screwdriver.sd50@1.2.0", {"on": "robot1.flange"})

    e = api.set_plan("c1", [{"step": "fasten", "module": "sd1", "op": "drive_screw", "params": {"torque_nm": 6.0}}])
    _assert_envelope_shape(e, Codes.PARAM_OUT_OF_BOUNDS)
    refusal = next(r for r in e.refusals if r.code == Codes.PARAM_OUT_OF_BOUNDS)
    assert refusal.path == "plan[0].params.torque_nm"
    assert refusal.allowed == {"max": 5.0}


def test_human_signature_required_verified_by(api: OcmApi, workspace_root: Path):
    api.create_module_draft("com.example.pickhead.sig1", "end_effector")
    manifest = api.describe_module("com.example.pickhead.sig1").data["manifest"]
    manifest["safety"] = {"verified_by": "Jane Doe, PE"}

    e = api.update_module("com.example.pickhead.sig1", manifest=manifest)
    _assert_envelope_shape(e, Codes.HUMAN_SIGNATURE_REQUIRED)
    refusal = next(r for r in e.refusals if r.code == Codes.HUMAN_SIGNATURE_REQUIRED)
    assert refusal.path == "safety.verified_by"

    # The hard guarantee: the signature never lands on disk, regardless of
    # how the rest of the document validates.
    on_disk = (workspace_root / "modules" / "com.example.pickhead.sig1" / "module.yaml").read_text(encoding="utf-8")
    assert "Jane Doe" not in on_disk
    assert api.describe_module("com.example.pickhead.sig1").data["manifest"].get("safety", {}).get("verified_by") is None


# ---------------------------------------------------------------------------
# Module authoring refusals
# ---------------------------------------------------------------------------


def test_schema_invalid(api: OcmApi):
    e = api.update_module("com.example.pickhead.bad1", manifest={"ocm_version": "1.1", "id": "com.example.pickhead.bad1"})
    _assert_envelope_shape(e, Codes.SCHEMA_INVALID)
    # write-anyway: the invalid attempt still landed on disk (spec/09: "so
    # iteration is cheap and the diff shows the attempt").
    assert api.describe_module("com.example.pickhead.bad1").refusals  # still invalid, but readable back


def test_schema_invalid_name_pattern_hint_suggests_snake_case(api: OcmApi):
    api.create_module_draft("com.example.pickhead.bad2", "end_effector")
    manifest = api.describe_module("com.example.pickhead.bad2").data["manifest"]
    manifest["comms"]["signals"] = [{"name": "IN_3", "direction": "input", "type": "bool"}]

    e = api.update_module("com.example.pickhead.bad2", manifest=manifest)
    assert not e.ok
    violation = next(r for r in e.refusals if "IN_3" in r.message)
    assert violation.code == Codes.SCHEMA_INVALID
    assert "snake_case" in violation.hint
    assert "in_3" in violation.hint


def test_not_found_describe_module(api: OcmApi):
    e = api.describe_module("com.example.does-not-exist")
    _assert_envelope_shape(e, Codes.NOT_FOUND)


def test_already_exists_create_module_draft(api: OcmApi):
    api.create_module_draft("com.example.pickhead.dup1", "end_effector")
    e = api.create_module_draft("com.example.pickhead.dup1", "end_effector")
    _assert_envelope_shape(e, Codes.ALREADY_EXISTS)


def test_draft_not_publishable(api: OcmApi):
    api.create_module_draft("com.example.pickhead.pub1", "end_effector")
    api.generate_geometry_stub("com.example.pickhead.pub1", (80, 60), 40)
    e = api.publish_module("com.example.pickhead.pub1", "0.2.0")
    _assert_envelope_shape(e, Codes.DRAFT_NOT_PUBLISHABLE)


def test_invalid_argument_publish_bad_semver(api: OcmApi):
    api.create_module_draft("com.example.pickhead.pub2", "end_effector")
    e = api.publish_module("com.example.pickhead.pub2", "not-a-version")
    _assert_envelope_shape(e, Codes.INVALID_ARGUMENT)


def test_invalid_argument_update_module_needs_exactly_one_of_manifest_or_patch(api: OcmApi):
    api.create_module_draft("com.example.pickhead.pub3", "end_effector")
    e = api.update_module("com.example.pickhead.pub3")
    _assert_envelope_shape(e, Codes.INVALID_ARGUMENT)

    e = api.update_module("com.example.pickhead.pub3", manifest={"a": 1}, patch=[{"op": "replace", "path": "/a", "value": 2}])
    _assert_envelope_shape(e, Codes.INVALID_ARGUMENT)


# ---------------------------------------------------------------------------
# Cell composition refusals
# ---------------------------------------------------------------------------


def test_unknown_module_place_instance(api: OcmApi):
    api.create_cell("c2", "com.accelsolutions.base.frame1200@2.0.0")
    e = api.place_instance("c2", "robot1", "com.example.totally-unknown@1.0.0", {"pose": {"xyz_mm": [0, 0, 0], "rpy_deg": [0, 0, 0]}})
    _assert_envelope_shape(e, Codes.UNKNOWN_MODULE)


def test_revision_mismatch_place_instance(api: OcmApi):
    api.create_cell("c3", "com.accelsolutions.base.frame1200@2.0.0")
    e = api.place_instance("c3", "robot1", "com.universal-robots.ur5e@9.9.9", {"pose": {"xyz_mm": [0, 0, 0], "rpy_deg": [0, 0, 0]}})
    _assert_envelope_shape(e, Codes.REVISION_MISMATCH)


def test_dangling_mount(api: OcmApi):
    api.create_cell("c4", "com.accelsolutions.base.frame1200@2.0.0")
    e = api.place_instance("c4", "sd1", "com.accelsolutions.screwdriver.sd50@1.2.0", {"on": "no_such_instance.flange"})
    _assert_envelope_shape(e, Codes.DANGLING_MOUNT)


def test_already_exists_place_instance_duplicate(api: OcmApi):
    api.create_cell("c5", "com.accelsolutions.base.frame1200@2.0.0")
    api.place_instance("c5", "robot1", "com.universal-robots.ur5e@3.1.0", {"pose": {"xyz_mm": [400, 300, 0], "rpy_deg": [0, 0, 0]}})
    e = api.place_instance("c5", "robot1", "com.universal-robots.ur5e@3.1.0", {"pose": {"xyz_mm": [0, 0, 0], "rpy_deg": [0, 0, 0]}})
    _assert_envelope_shape(e, Codes.ALREADY_EXISTS)


def test_not_found_move_and_remove_unknown_instance(api: OcmApi):
    api.create_cell("c6", "com.accelsolutions.base.frame1200@2.0.0")
    e = api.move_instance("c6", "ghost", {"pose": {"xyz_mm": [0, 0, 0], "rpy_deg": [0, 0, 0]}})
    _assert_envelope_shape(e, Codes.NOT_FOUND)
    e = api.remove_instance("c6", "ghost")
    _assert_envelope_shape(e, Codes.NOT_FOUND)


def test_workspace_overhang(api: OcmApi):
    api.create_cell("c7", "com.accelsolutions.base.frame1200@2.0.0")
    e = api.place_instance(
        "c7", "nest1", "com.accelsolutions.fixture.pneumatic-nest@1.1.0",
        {"pose": {"xyz_mm": [5000, 300, 0], "rpy_deg": [0, 0, 90]}},
    )
    _assert_envelope_shape(e, Codes.WORKSPACE_OVERHANG)
    refusal = next(r for r in e.refusals if r.code == Codes.WORKSPACE_OVERHANG)
    assert "+X by" in refusal.message
    assert "footprint" in refusal.allowed


def test_unknown_op(api: OcmApi):
    api.create_cell("c8", "com.accelsolutions.base.frame1200@2.0.0")
    api.place_instance("c8", "sd1", "com.accelsolutions.screwdriver.sd50@1.2.0", {"pose": {"xyz_mm": [0, 0, 0], "rpy_deg": [0, 0, 0]}})
    e = api.set_plan("c8", [{"step": "x", "module": "sd1", "op": "levitate"}])
    _assert_envelope_shape(e, Codes.UNKNOWN_OP)
    refusal = next(r for r in e.refusals if r.code == Codes.UNKNOWN_OP)
    assert "values" in refusal.allowed


def test_unknown_param(api: OcmApi):
    api.create_cell("c9", "com.accelsolutions.base.frame1200@2.0.0")
    api.place_instance("c9", "sd1", "com.accelsolutions.screwdriver.sd50@1.2.0", {"pose": {"xyz_mm": [0, 0, 0], "rpy_deg": [0, 0, 0]}})
    e = api.set_plan("c9", [{"step": "x", "module": "sd1", "op": "drive_screw", "params": {"torque_nm": 2.4, "made_up": 1}}])
    _assert_envelope_shape(e, Codes.UNKNOWN_PARAM)


def test_cell_invalid_structurally_broken_document(api: OcmApi, ws):
    from ocm_api.workspace import write_yaml

    api.create_cell("c10", "com.accelsolutions.base.frame1200@2.0.0")
    write_yaml(ws.cell_path("c10"), {"ocm_version": "1.0", "id": "x", "license": "CERN-OHL-S-2.0"})  # missing base/modules
    e = api.build_scene("c10")
    _assert_envelope_shape(e, Codes.CELL_INVALID)


# ---------------------------------------------------------------------------
# Draft-vs-published resolution: a draft module must not resolve into a cell
# ---------------------------------------------------------------------------


def test_draft_module_referenced_blocks_placement(api: OcmApi):
    # dh200 is a real, pre-existing draft in this repo (revision 0.9.1).
    api.create_cell("c11", "com.accelsolutions.base.frame1200@2.0.0")
    e = api.place_instance("c11", "dispense1", "com.accelsolutions.dispense.dh200@0.9.1", {"pose": {"xyz_mm": [0, 0, 0], "rpy_deg": [0, 0, 0]}})
    _assert_envelope_shape(e, Codes.DRAFT_MODULE_REFERENCED)


def test_draft_module_becomes_resolvable_once_published(api: OcmApi):
    api.create_module_draft("com.example.pickhead.dr1", "end_effector")
    api.generate_geometry_stub("com.example.pickhead.dr1", (80, 60), 40)

    api.create_cell("c12", "com.accelsolutions.base.frame1200@2.0.0")
    e = api.place_instance("c12", "pk1", "com.example.pickhead.dr1@0.1.0", {"pose": {"xyz_mm": [0, 0, 0], "rpy_deg": [0, 0, 0]}})
    _assert_envelope_shape(e, Codes.DRAFT_MODULE_REFERENCED)

    published = api.publish_module("com.example.pickhead.dr1", "1.0.0")
    assert published.ok, published.refusals

    # The failed attempt above still wrote a (dangling) placement --
    # composition verbs always write (design principle #3) -- so fix it
    # the same way an agent would: remove, then re-place at the now-real
    # revision.
    api.remove_instance("c12", "pk1")
    e = api.place_instance("c12", "pk1", "com.example.pickhead.dr1@1.0.0", {"pose": {"xyz_mm": [0, 0, 0], "rpy_deg": [0, 0, 0]}})
    assert e.ok, e.refusals


def test_draft_base_module_also_blocks_resolution(api: OcmApi):
    # Same rule applies to the base, not just placed instances.
    e = api.create_cell("c13", "com.accelsolutions.dispense.dh200@0.9.1")
    assert e.ok  # create_cell itself doesn't resolve
    e = api.build_scene("c13")
    _assert_envelope_shape(e, Codes.DRAFT_MODULE_REFERENCED)


# ---------------------------------------------------------------------------
# Checking & generation refusals
# ---------------------------------------------------------------------------


def test_no_fastening_step(api: OcmApi):
    # A real, resolvable op (nest1's own "clamp") -- just no for_each
    # fastening step with a drive_screw in it.
    api.create_cell("c14", "com.accelsolutions.base.frame1200@2.0.0")
    api.place_instance("c14", "nest1", "com.accelsolutions.fixture.pneumatic-nest@1.1.0", {"pose": {"xyz_mm": [640, 300, 0], "rpy_deg": [0, 0, 90]}})
    api.set_plan("c14", [{"step": "clamp", "module": "nest1", "op": "clamp", "params": {"force_n": 120}}])

    pytest.importorskip("tesseract_robotics")
    e = api.plan_cell("c14")
    _assert_envelope_shape(e, Codes.NO_FASTENING_STEP)


def test_pose_unreachable(api: OcmApi):
    pytest.importorskip("tesseract_robotics")
    api.create_cell("c15", "com.accelsolutions.base.frame1200@2.0.0")
    api.place_instance("c15", "robot1", "com.universal-robots.ur5e@3.1.0", {"pose": {"xyz_mm": [400, 300, 0], "rpy_deg": [0, 0, 0]}})
    api.set_joint_state("c15", "robot1", {"shoulder_lift_joint": -1.5707963267948966, "elbow_joint": 1.5707963267948966})
    api.place_instance("c15", "sd1", "com.accelsolutions.screwdriver.sd50@1.2.0", {"on": "robot1.flange"})
    api.place_instance("c15", "nest1", "com.accelsolutions.fixture.pneumatic-nest@1.1.0", {"pose": {"xyz_mm": [640, 300, 0], "rpy_deg": [0, 0, 90]}})

    part = {"id": "BRK-TEST", "features": {"hole_1": {"xyz_mm": [9000, 9000, 0], "normal": [0, 0, 1]}}}
    plan = [
        {"step": "clamp", "module": "nest1", "op": "clamp", "params": {"force_n": 120}},
        {"step": "fasten", "for_each": ["hole_1"], "sequence": [
            {"module": "sd1", "op": "load_screw"},
            {"module": "sd1", "op": "drive_screw", "at": "part.features.${item}", "params": {"torque_nm": 2.4, "depth_mm": 8.0}},
        ]},
        {"step": "release", "module": "nest1", "op": "unclamp"},
    ]
    api.set_plan("c15", plan, part=part)

    e = api.plan_cell("c15")
    _assert_envelope_shape(e, Codes.POSE_UNREACHABLE)
    refusal = next(r for r in e.refusals if r.code == Codes.POSE_UNREACHABLE)
    assert "standoff" in refusal.path


def test_path_collision(api: OcmApi, workspace_root: Path):
    pytest.importorskip("tesseract_robotics")
    write_obstacle_module(workspace_root)
    build_two_hole_cell_with_obstacle(api)

    e = api.plan_cell("obstacle-cell")
    _assert_envelope_shape(e, Codes.PATH_COLLISION)
    refusal = next(r for r in e.refusals if r.code == Codes.PATH_COLLISION)
    assert refusal.path == "plan.segments['retract_1 -> standoff_2']"
    assert refusal.allowed["instance_a"] == "blocker" or refusal.allowed["instance_b"] == "blocker"
    assert 0.0 < refusal.allowed["t"] < 1.0


def test_collision_detected(api: OcmApi):
    pytest.importorskip("tesseract_robotics")
    api.create_cell("c16", "com.accelsolutions.base.frame1200@2.0.0")
    api.place_instance("c16", "feed1", "com.accelsolutions.screwfeeder.sf20@1.0.0", {"pose": {"xyz_mm": [300, 300, 0], "rpy_deg": [0, 0, 0]}})
    api.place_instance("c16", "nest1", "com.accelsolutions.fixture.pneumatic-nest@1.1.0", {"pose": {"xyz_mm": [300, 300, 0], "rpy_deg": [0, 0, 0]}})

    e = api.check_collision("c16")
    _assert_envelope_shape(e, Codes.COLLISION_DETECTED)


def test_unavailable_plan_cell(api: OcmApi, monkeypatch: pytest.MonkeyPatch):
    import ocm_api.generation as generation_module
    from ocm_generator.planner import PlanningUnavailable

    def raise_unavailable(*args, **kwargs):
        raise PlanningUnavailable("tesseract-robotics is not installed")

    monkeypatch.setattr(generation_module, "plan_fastening_sequence", raise_unavailable)

    # A genuinely resolvable cell + fastening plan -- the ONLY failure
    # this test wants to exercise is plan_fastening_sequence itself being
    # unavailable, not an earlier resolve-time refusal.
    api.create_cell("c17", "com.accelsolutions.base.frame1200@2.0.0")
    api.place_instance("c17", "robot1", "com.universal-robots.ur5e@3.1.0", {"pose": {"xyz_mm": [400, 300, 0], "rpy_deg": [0, 0, 0]}})
    api.set_joint_state("c17", "robot1", {"shoulder_lift_joint": -1.5707963267948966, "elbow_joint": 1.5707963267948966})
    # nest1 first, so sd1 can bind its workpiece_secured requirement (ADR-0023)
    # to a target that already exists.
    api.place_instance("c17", "nest1", "com.accelsolutions.fixture.pneumatic-nest@1.1.0", {"pose": {"xyz_mm": [640, 300, 0], "rpy_deg": [0, 0, 90]}})
    api.place_instance(
        "c17", "sd1", "com.accelsolutions.screwdriver.sd50@1.2.0", {"on": "robot1.flange"},
        requires={"workpiece_secured": "nest1.clamped"},
    )
    part = {"id": "BRK-TEST", "features": {"hole_1": {"xyz_mm": [12, 12, 0], "normal": [0, 0, 1]}}}
    plan = [
        {"step": "clamp", "module": "nest1", "op": "clamp", "params": {"force_n": 120}},
        {"step": "fasten", "for_each": ["hole_1"], "sequence": [
            {"module": "sd1", "op": "load_screw"},
            {"module": "sd1", "op": "drive_screw", "at": "part.features.${item}", "params": {"torque_nm": 2.4, "depth_mm": 8.0}},
        ]},
        {"step": "release", "module": "nest1", "op": "unclamp"},
    ]
    api.set_plan("c17", plan, part=part)

    e = api.plan_cell("c17")
    _assert_envelope_shape(e, Codes.UNAVAILABLE)


def test_unavailable_check_collision(api: OcmApi, monkeypatch: pytest.MonkeyPatch):
    import ocm_api.generation as generation_module
    from ocm_generator.scene import CollisionCheckUnavailable

    def raise_unavailable(*args, **kwargs):
        raise CollisionCheckUnavailable("tesseract-robotics is not installed")

    monkeypatch.setattr(generation_module, "check_collisions", raise_unavailable)

    e = generation_module.check_collision(api.workspace, "bracket-asm-01")
    _assert_envelope_shape(e, Codes.UNAVAILABLE)
