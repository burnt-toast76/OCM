# SPDX-License-Identifier: AGPL-3.0-or-later
"""ADR-0023's four refusal CODES, as they surface through the API (validate_module
for the module-scoped ones, place_instance/set_plan for the cell-scoped ones).
The raw detection is tested in ocm-resolve; this pins the code + hint mapping
(ocm-api/translate.py) an agent or GUI actually renders.
"""

from __future__ import annotations

from typing import Any

from ocm_api import Codes, OcmApi, Workspace
from ocm_api.workspace import write_yaml


def _end_effector_manifest(module_id: str, cap: dict[str, Any], *, abort_safe: bool = False, signals: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "ocm_version": "1.1",
        "id": module_id,
        "revision": "1.0.0",
        "kind": "end_effector",
        "license": "CERN-OHL-S-2.0",
        "name": "Test Tool",
        "mechanical": {
            "mount": {"interface": "iso-9409-1-a50", "footprint_mm": [70.0, 70.0]},
            "frames": {"origin": {"xyz_mm": [0.0, 0.0, 0.0]}, "tcp": {"xyz_mm": [0.0, 0.0, 100.0]}},
            "geometry": {"collision": "meshes/tool_convex.stl", "urdf_fragment": "urdf/tool.urdf.xacro"},
            "mass_kg": 1.0,
            "com_mm": [0.0, 0.0, 50.0],
        },
        "comms": {"protocol": "ethercat", "signals": signals or []},
        "capabilities": [cap],
        "state_machine": {"model": "packml", "implements": ["idle", "execute"], "abort_safe": abort_safe},
    }


def _drive_cap(**overrides: Any) -> dict[str, Any]:
    cap: dict[str, Any] = {"name": "grip", "summary": "Grip.", "timeout_s": 6.0, "on_timeout": "abort"}
    cap.update(overrides)
    return cap


def _put_module(ws: Workspace, manifest: dict[str, Any]) -> None:
    write_yaml(ws.module_path(manifest["id"]), manifest)


# --- CONDITION_UNKNOWN_SIGNAL -----------------------------------------------


def test_condition_unknown_signal_surfaces_through_validate_module(api: OcmApi, ws: Workspace):
    _put_module(ws, _end_effector_manifest("com.example.tool.badcond", _drive_cap(preconditions=["ghost_signal == true"])))
    e = api.validate_module("com.example.tool.badcond")
    assert not e.ok
    r = next(r for r in e.refusals if r.code == Codes.CONDITION_UNKNOWN_SIGNAL)
    assert "ADR-0023" in (r.hint or "")


# --- TIMEOUT_DISPOSITION_CONFLICT -------------------------------------------


def test_timeout_disposition_conflict_surfaces_through_validate_module(api: OcmApi, ws: Workspace):
    _put_module(ws, _end_effector_manifest("com.example.tool.badtimeout", _drive_cap(on_timeout="hold"), abort_safe=False))
    e = api.validate_module("com.example.tool.badtimeout")
    assert not e.ok
    assert any(r.code == Codes.TIMEOUT_DISPOSITION_CONFLICT for r in e.refusals)


def test_on_timeout_hold_is_fine_when_the_module_is_abort_safe(api: OcmApi, ws: Workspace):
    _put_module(ws, _end_effector_manifest("com.example.tool.oktimeout", _drive_cap(on_timeout="hold"), abort_safe=True))
    e = api.validate_module("com.example.tool.oktimeout")
    assert not any(r.code == Codes.TIMEOUT_DISPOSITION_CONFLICT for r in e.refusals), e.refusals


# --- REQUIREMENT_UNBOUND / REQUIREMENT_UNKNOWN_TARGET -----------------------


def _place_robot(api: OcmApi, cell_id: str) -> None:
    api.create_cell(cell_id, "com.accelsolutions.base.frame1200@2.0.0")
    api.place_instance(cell_id, "robot1", "com.universal-robots.ur5e@3.1.0", {"pose": {"xyz_mm": [400, 300, 0], "rpy_deg": [0, 0, 0]}})
    # home pose, so a tool on the flange doesn't overhang the base footprint
    api.set_joint_state(cell_id, "robot1", {"shoulder_lift_joint": -1.5707963267948966, "elbow_joint": 1.5707963267948966})


def test_requirement_unbound_surfaces_when_sd50_is_placed_without_a_binding(api: OcmApi):
    _place_robot(api, "c-unbound")
    e = api.place_instance("c-unbound", "sd1", "com.accelsolutions.screwdriver.sd50@1.2.0", {"on": "robot1.flange"})
    assert not e.ok
    r = next(r for r in e.refusals if r.code == Codes.REQUIREMENT_UNBOUND)
    assert "workpiece_secured" in r.path
    assert "input bool" in (r.hint or "")


def test_requirement_unknown_target_surfaces_for_a_dangling_binding(api: OcmApi):
    _place_robot(api, "c-badtarget")
    e = api.place_instance(
        "c-badtarget", "sd1", "com.accelsolutions.screwdriver.sd50@1.2.0", {"on": "robot1.flange"},
        requires={"workpiece_secured": "ghost.clamped"},
    )
    assert not e.ok
    assert any(r.code == Codes.REQUIREMENT_UNKNOWN_TARGET for r in e.refusals)


def test_requirement_bound_to_a_real_peer_signal_resolves(api: OcmApi):
    _place_robot(api, "c-bound")
    api.place_instance("c-bound", "nest1", "com.accelsolutions.fixture.pneumatic-nest@1.1.0", {"pose": {"xyz_mm": [640, 300, 0], "rpy_deg": [0, 0, 90]}})
    e = api.place_instance(
        "c-bound", "sd1", "com.accelsolutions.screwdriver.sd50@1.2.0", {"on": "robot1.flange"},
        requires={"workpiece_secured": "nest1.clamped"},
    )
    assert e.ok, e.refusals
