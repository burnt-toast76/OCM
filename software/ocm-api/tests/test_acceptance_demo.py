# SPDX-License-Identifier: AGPL-3.0-or-later
"""spec/09-ocm-api.md's "acceptance demo" section, scripted as a hardcoded
sequence of tool calls: "this is the test." Runs the exact five beats --
describe/example -> draft -> a trapped first attempt -> corrected ->
published -> placed overhanging -> moved inside -> planned -- and asserts
refusal count > 0 (spec's own bar) with at least two distinct refusals and
a final, successful `plan_cell`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ocm_api import Codes, OcmApi

# 1. The "datasheet" the agent works from (a short fictional prose spec for
# a pneumatic pick head) -- not machine-read by anything in this package;
# ocm-api has no LLM in the loop. It's reproduced here purely to justify
# the manifest values below the same way a real agent session would derive
# them from it.
PK100_DATASHEET = """
PK100 Pneumatic Pick Head -- Preliminary Datasheet

  Stroke:        25 mm
  Vacuum range:  20-80 kPa
  Mount:         ISO 9409-1-A50
  Mass:          0.6 kg
  Electrical:    M12, 2-pin (vacuum_on OUT, part_present IN)

  Ops:
    pick(vacuum_kpa) -- applies vacuum at the commanded level and reports
    the part's picked pose for traceability.
"""

_STATE_MACHINE_STATES = [
    "idle", "starting", "execute", "completing", "complete",
    "resetting", "aborting", "aborted", "clearing", "stopping", "stopped",
]


def _pk100_manifest(*, with_frame: bool) -> dict:
    """The agent's manifest for PK100, derived from `PK100_DATASHEET`.
    `with_frame=False` is the planted trap spec/09 calls for: a `pose6d`
    result with no `frame` -- exactly the schema's own worked example
    (`capabilities[0].results.part_pose`, 'frame' is a required property).
    """
    part_pose: dict = {"type": "pose6d", "summary": "The picked part's pose, for traceability."}
    if with_frame:
        part_pose["frame"] = "tcp"

    return {
        "ocm_version": "1.1",
        "id": "com.example.pickhead.pk100",
        "revision": "0.1.0",
        "kind": "end_effector",
        "license": "CERN-OHL-S-2.0",
        "name": "PK100 Pneumatic Pick Head",
        "mechanical": {
            "mount": {"interface": "iso-9409-1-a50", "footprint_mm": [80.0, 60.0]},
            "frames": {
                "origin": {"xyz_mm": [0.0, 0.0, 0.0]},
                "tcp": {"xyz_mm": [0.0, 0.0, 45.0]},
            },
            "geometry": {"collision": "meshes/TODO_convex.stl"},
            "mass_kg": 0.6,
            "com_mm": [0.0, 0.0, 22.0],
        },
        "state_machine": {"model": "packml", "implements": list(_STATE_MACHINE_STATES), "abort_safe": True},
        "capabilities": [
            {
                "name": "pick",
                "summary": "Apply vacuum at the commanded level and pick the part.",
                "parameters": {
                    "vacuum_kpa": {"type": "number", "unit": "kPa", "min": 20.0, "max": 80.0, "summary": "Vacuum level to apply."},
                },
                "results": {"part_pose": part_pose},
            }
        ],
        "comms": {
            "protocol": "ethercat",
            "signals": [
                {"name": "vacuum_on", "direction": "output", "type": "bool"},
                {"name": "part_present", "direction": "input", "type": "bool"},
            ],
        },
    }


def test_acceptance_demo(api: OcmApi, workspace_root: Path):
    pytest.importorskip("tesseract_robotics")

    refusals_seen: list = []

    # 2. describe_schema + get_example(end_effector) -- the agent looks
    # before it writes.
    schema_envelope = api.describe_schema()
    assert schema_envelope.ok, schema_envelope.refusals
    example_envelope = api.get_example("end_effector")
    assert example_envelope.ok, example_envelope.refusals

    # create_module_draft
    draft_envelope = api.create_module_draft("com.example.pickhead.pk100", "end_effector")
    assert draft_envelope.ok, draft_envelope.refusals
    assert draft_envelope.data["draft"] is True

    # 3. First attempt: the planted trap (pose6d result with no frame).
    # ALWAYS WRITTEN (spec/09: validation gates publishing, not saving),
    # but ok=false with the violation named by path + hint.
    trapped_envelope = api.update_module("com.example.pickhead.pk100", manifest=_pk100_manifest(with_frame=False))
    assert not trapped_envelope.ok
    assert len(trapped_envelope.refusals) >= 1
    refusals_seen.extend(trapped_envelope.refusals)
    trap_refusal = trapped_envelope.refusals[0]
    assert trap_refusal.code == Codes.SCHEMA_INVALID
    assert "frame" in trap_refusal.message
    # A pose6d-specific hint, not generic "fix the field" boilerplate --
    # it points the agent at the verb that actually answers "what frame?".
    assert "list_frames" in trap_refusal.hint

    # Agent corrects and resubmits.
    corrected_envelope = api.update_module("com.example.pickhead.pk100", manifest=_pk100_manifest(with_frame=True))
    assert corrected_envelope.ok, corrected_envelope.refusals

    # generate_geometry_stub -- ADR-0011: agents never hand-write URDF.
    # Also required for place_instance below: resolve_cell needs a real
    # mechanical.geometry.urdf_fragment to compose the scene at all.
    geometry_envelope = api.generate_geometry_stub("com.example.pickhead.pk100", (80.0, 60.0), 45.0)
    assert geometry_envelope.ok, geometry_envelope.refusals

    # validate_module passes now.
    validate_envelope = api.validate_module("com.example.pickhead.pk100")
    assert validate_envelope.ok, validate_envelope.refusals
    assert validate_envelope.data["valid"] is True

    # publish_module -- module becomes resolvable.
    publish_envelope = api.publish_module("com.example.pickhead.pk100", "1.0.0")
    assert publish_envelope.ok, publish_envelope.refusals
    assert publish_envelope.data["published"] is True

    # 4. place_instance into bracket-asm-01 at a spot that overhangs the
    # 1200x900mm base footprint (frame1200) -- refused with "+X by N mm".
    overhang_envelope = api.place_instance(
        "bracket-asm-01", "pk1", "com.example.pickhead.pk100@1.0.0",
        {"pose": {"xyz_mm": [2000, 300, 0], "rpy_deg": [0, 0, 0]}},
    )
    assert not overhang_envelope.ok
    assert len(overhang_envelope.refusals) >= 1
    refusals_seen.extend(overhang_envelope.refusals)
    overhang_refusal = overhang_envelope.refusals[0]
    assert overhang_refusal.code == Codes.WORKSPACE_OVERHANG
    assert "+X" in overhang_refusal.message

    # Agent moves it inside the base footprint -- ok.
    moved_envelope = api.move_instance(
        "bracket-asm-01", "pk1",
        {"pose": {"xyz_mm": [900, 600, 300], "rpy_deg": [0, 0, 0]}},
    )
    assert moved_envelope.ok, moved_envelope.refusals

    # 5. plan_cell -> cycle table returned. Reposition cam1 out of the
    # straight-line joint-space sweep first -- bracket-asm-01's real cam1
    # placement is a documented near-miss (Bullet/Tesseract floating-point
    # non-determinism), so this keeps the final, must-succeed call
    # deterministic (see test_verbs.py::test_plan_cell_and_emit).
    api.move_instance("bracket-asm-01", "cam1", {"pose": {"xyz_mm": [640, 300, 900], "rpy_deg": [180, 0, 0]}})

    plan_envelope = api.plan_cell("bracket-asm-01")
    assert plan_envelope.ok, plan_envelope.refusals
    assert "cycle_table" in plan_envelope.data

    assert len(refusals_seen) >= 2
