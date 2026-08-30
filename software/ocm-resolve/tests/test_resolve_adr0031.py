# SPDX-License-Identifier: AGPL-3.0-or-later
"""ADR-0031 D3 manifest-only refusals: the located datum's constraint
scheme must close (every DOF governed exactly once), every governed DOF
carries a tolerance, and tolerance units are type-checked against the DOF
(ADR-0028 D2's rule, second site). All answerable from the manifest alone
-- no fragment, no file. Follows test_resolve_adr0028.py's structure;
tolerance numbers are inline and obviously synthetic (ADR-0014)."""

from __future__ import annotations

from typing import Any

from ocm_core import Module
from ocm_resolve import resolve_module

_MM = {"value": 0.05, "unit": "mm"}
_DEG = {"value": 0.02, "unit": "deg"}


def _closed_constraints() -> list[dict[str, Any]]:
    return [
        {
            "feature": "lift_stop_surface",
            "governs": ["z", "rx", "ry"],
            "tolerance": {"z": dict(_MM), "rx": dict(_DEG), "ry": dict(_DEG)},
            "source": "measured",
        },
        {
            "feature": "locating_pins",
            "governs": ["x", "y", "rz"],
            "tolerance": {"x": dict(_MM), "y": dict(_MM), "rz": dict(_DEG)},
            "source": "measured",
        },
    ]


def _module_with_located(located: dict[str, Any]) -> Module:
    return Module.from_dict({
        "ocm_version": "1.1",
        "id": "com.example.conveyor.locating",
        "revision": "1.0.0",
        "kind": "transport",
        "license": "CERN-OHL-S-2.0",
        "name": "Locating conveyor test module",
        "mechanical": {
            "mount": {"interface": "custom"},
            "frames": {"origin": {"xyz_mm": [0, 0, 0]}, "located_datum": {"xyz_mm": [100, 0, 50]}},
            "geometry": {"urdf_fragment": "urdf/t.urdf"},
            "mass_kg": 40.0,
            "located": located,
        },
        "state_machine": {"model": "packml", "abort_safe": True},
    })


def test_fully_specified_located_block_produces_no_violations():
    module = _module_with_located({"frame": "located_datum", "constraints": _closed_constraints()})
    assert resolve_module(module) == []


def test_unknown_frame_is_refused_listing_declared_frames():
    module = _module_with_located({"frame": "ghost_datum", "constraints": _closed_constraints()})
    errors = resolve_module(module)
    assert any(
        "located.frame 'ghost_datum' is not a declared mechanical.frames entry" in e and "located_datum" in e
        for e in errors
    ), errors


def test_ungoverned_dof_is_refused_naming_the_dof():
    constraints = _closed_constraints()
    constraints[1]["governs"] = ["x", "y"]  # rz now governed by nothing
    del constraints[1]["tolerance"]["rz"]
    module = _module_with_located({"frame": "located_datum", "constraints": constraints})
    errors = resolve_module(module)
    assert any("located constraints govern nothing for 'rz'" in e and "does not close" in e for e in errors), errors


def test_doubly_governed_dof_is_refused_naming_both_features():
    constraints = _closed_constraints()
    constraints[1]["governs"] = ["x", "y", "rz", "z"]  # z also governed by the stop surface
    constraints[1]["tolerance"]["z"] = dict(_MM)
    module = _module_with_located({"frame": "located_datum", "constraints": constraints})
    errors = resolve_module(module)
    assert any(
        "located DOF 'z' is governed by both 'lift_stop_surface' and 'locating_pins'" in e for e in errors
    ), errors


def test_governed_dof_without_tolerance_is_refused():
    constraints = _closed_constraints()
    del constraints[0]["tolerance"]["rx"]
    module = _module_with_located({"frame": "located_datum", "constraints": constraints})
    errors = resolve_module(module)
    assert any(
        "located feature 'lift_stop_surface' governs rx but declares no tolerance for it" in e for e in errors
    ), errors


def test_angular_unit_on_a_linear_dof_is_refused():
    constraints = _closed_constraints()
    constraints[1]["tolerance"]["x"] = {"value": 0.03, "unit": "deg"}
    module = _module_with_located({"frame": "located_datum", "constraints": constraints})
    errors = resolve_module(module)
    assert any(
        "gives x an angular unit 'deg'; a linear DOF takes a length" in e for e in errors
    ), errors


def test_length_unit_on_a_rotational_dof_is_refused():
    constraints = _closed_constraints()
    constraints[0]["tolerance"]["ry"] = {"value": 0.02, "unit": "mm"}
    module = _module_with_located({"frame": "located_datum", "constraints": constraints})
    errors = resolve_module(module)
    assert any(
        "gives ry a length unit 'mm'; a rotational DOF takes an angle" in e for e in errors
    ), errors


def test_unit_in_neither_table_is_refused_through_the_existing_code():
    # OCM_UNIT_UNRECOGNISED, unchanged -- a fourth emission site, not a new
    # code (ADR-0027's rule).
    constraints = _closed_constraints()
    constraints[1]["tolerance"]["y"] = {"value": 0.03, "unit": "furlongs"}
    module = _module_with_located({"frame": "located_datum", "constraints": constraints})
    errors = resolve_module(module)
    assert any(
        "located feature 'locating_pins' tolerance unit 'furlongs' is unrecognised" in e for e in errors
    ), errors


def test_module_without_located_is_untouched():
    module = _module_with_located({"frame": "located_datum", "constraints": _closed_constraints()})
    bare = Module.from_dict({
        "ocm_version": "1.1",
        "id": "com.example.conveyor.plain",
        "revision": "1.0.0",
        "kind": "transport",
        "license": "CERN-OHL-S-2.0",
        "mechanical": {
            "mount": {"interface": "custom"},
            "frames": {"origin": {"xyz_mm": [0, 0, 0]}},
            "geometry": {"urdf_fragment": "urdf/t.urdf"},
            "mass_kg": 40.0,
        },
        "state_machine": {"model": "packml", "abort_safe": True},
    })
    assert bare.mechanical.located is None
    assert resolve_module(bare) == []
    assert module.mechanical.located is not None


# ---------------------------------------------------------------------------
# Part 2 (D2 + D4): the cell's carrier declaration and the declared part datum
# ---------------------------------------------------------------------------

from pathlib import Path

import yaml

from ocm_core.cell import Cell
from ocm_resolve import resolve_cell
from ocm_resolve.errors import CellResolutionError

from .conftest import build_cell_dict, minimal_base_manifest, minimal_robot_manifest, minimal_tool_manifest, write_module

import pytest


def _conveyor_manifest() -> dict[str, Any]:
    return {
        "ocm_version": "1.1",
        "id": "com.example.conveyor.locating",
        "revision": "1.0.0",
        "kind": "transport",
        "license": "CERN-OHL-S-2.0",
        "name": "Locating conveyor",
        "mechanical": {
            "mount": {"interface": "custom"},
            "frames": {"origin": {"xyz_mm": [0, 0, 0]}, "located_datum": {"xyz_mm": [100, 0, 50]}},
            "geometry": {"urdf_fragment": "urdf/t.urdf"},
            "mass_kg": 40.0,
            "located": {"frame": "located_datum", "constraints": _closed_constraints()},
        },
        "state_machine": {"model": "packml", "abort_safe": True},
    }


def _carrier_manifest(with_part_datum: bool = True) -> dict[str, Any]:
    frames: dict[str, Any] = {"origin": {"xyz_mm": [0, 0, 0]}}
    if with_part_datum:
        frames["part_datum"] = {"xyz_mm": [120, 120, 40]}
    return {
        "ocm_version": "1.1",
        "id": "com.example.carrier.test-pallet",
        "revision": "1.0.0",
        "license": "CERN-OHL-S-2.0",
        "mechanical": {"frames": frames, "geometry": {"urdf_fragment": "urdf/pallet.urdf"}, "mass_kg": 2.5},
    }


def _write_carrier(tmp_path: Path, manifest: dict[str, Any]) -> None:
    carrier_dir = tmp_path / "carriers" / manifest["id"]
    carrier_dir.mkdir(parents=True, exist_ok=True)
    (carrier_dir / "carrier.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")


def _carrier_cell(tmp_path: Path, carrier_block: dict[str, Any] | None, plan_at_part: bool, fixture_part_datum: bool = False) -> tuple[Cell, Path]:
    root = tmp_path / "modules"
    write_module(root, minimal_base_manifest())
    write_module(root, minimal_robot_manifest())
    tool = minimal_tool_manifest()
    if fixture_part_datum:
        tool["mechanical"]["frames"]["part_datum"] = {"xyz_mm": [0, 0, 10]}
    write_module(root, tool)
    write_module(root, _conveyor_manifest())

    plan = [
        {"step": "fasten", "module": "tool1", "op": "drive_screw",
         **({"at": "part.features.hole_1"} if plan_at_part else {}),
         "params": {"torque_nm": 2.4}},
    ]
    cell_dict = build_cell_dict(
        modules=[
            {"instance": "robot1", "module": "com.example.robot.tiny@1.0.0",
             "mount": {"station": [100, 100], "pose": {"xyz_mm": [100, 100, 0]}}},
            {"instance": "tool1", "module": "com.example.tool.tiny@1.0.0", "mount": {"on": "robot1.flange"}},
            {"instance": "conv1", "module": "com.example.conveyor.locating@1.0.0",
             "mount": {"pose": {"xyz_mm": [300, 100, 0]}}},
        ],
        plan=plan,
    )
    if carrier_block is not None:
        cell_dict["carrier"] = carrier_block
    return Cell.from_dict(cell_dict), root


_CARRIER_BLOCK = {
    "instance": "pal1",
    "type": "com.example.carrier.test-pallet@1.0.0",
    "located_on": "conv1",
    "entry_mm": {"travel": -400, "lift": -12},
}


def test_cell_with_carrier_resolves_and_carries_the_type(tmp_path: Path):
    _write_carrier(tmp_path, _carrier_manifest())
    cell, root = _carrier_cell(tmp_path, dict(_CARRIER_BLOCK), plan_at_part=True)
    resolved = resolve_cell(cell, root)
    assert resolved.carrier is not None
    assert resolved.carrier.name == "pal1"
    assert resolved.carrier.carrier.id == "com.example.carrier.test-pallet"


def test_unknown_carrier_type_refuses(tmp_path: Path):
    cell, root = _carrier_cell(tmp_path, dict(_CARRIER_BLOCK), plan_at_part=False)  # no carrier written
    with pytest.raises(CellResolutionError) as exc:
        resolve_cell(cell, root)
    assert any("carrier not found" in e for e in exc.value.errors), exc.value.errors


def test_located_on_unknown_instance_refuses(tmp_path: Path):
    _write_carrier(tmp_path, _carrier_manifest())
    block = dict(_CARRIER_BLOCK, located_on="ghost")
    cell, root = _carrier_cell(tmp_path, block, plan_at_part=False)
    with pytest.raises(CellResolutionError) as exc:
        resolve_cell(cell, root)
    assert any("located_on 'ghost'" in e and "not a placed module instance" in e for e in exc.value.errors)


def test_located_on_module_without_located_datum_refuses(tmp_path: Path):
    _write_carrier(tmp_path, _carrier_manifest())
    block = dict(_CARRIER_BLOCK, located_on="robot1")  # robot declares no mechanical.located
    cell, root = _carrier_cell(tmp_path, block, plan_at_part=False)
    with pytest.raises(CellResolutionError) as exc:
        resolve_cell(cell, root)
    assert any("declares no mechanical.located datum to root the chain at" in e for e in exc.value.errors)


def test_transit_without_entry_refuses(tmp_path: Path):
    _write_carrier(tmp_path, _carrier_manifest())
    block = {k: v for k, v in _CARRIER_BLOCK.items() if k != "entry_mm"}
    block["transit_mm"] = {"travel": -100, "lift": -5}
    cell, root = _carrier_cell(tmp_path, block, plan_at_part=False)
    with pytest.raises(CellResolutionError) as exc:
        resolve_cell(cell, root)
    assert any("transit_mm but no entry_mm" in e for e in exc.value.errors)


def test_transit_beyond_entry_refuses(tmp_path: Path):
    _write_carrier(tmp_path, _carrier_manifest())
    block = dict(_CARRIER_BLOCK, transit_mm={"travel": -500, "lift": -5})  # entry travel is -400
    cell, root = _carrier_cell(tmp_path, block, plan_at_part=False)
    with pytest.raises(CellResolutionError) as exc:
        resolve_cell(cell, root)
    assert any("beyond the declared entry" in e and "[-400, 0]" in e for e in exc.value.errors)


def test_part_plan_with_no_part_datum_anywhere_refuses(tmp_path: Path):
    # ADR-0031 D4: the plan operates on `part`, nothing declares
    # frames.part_datum, and it will NOT be guessed from a clamp verb.
    cell, root = _carrier_cell(tmp_path, carrier_block=None, plan_at_part=True)
    with pytest.raises(CellResolutionError) as exc:
        resolve_cell(cell, root)
    assert any(
        "plan operates on part but no carrier or fixture declares frames.part_datum" in e
        for e in exc.value.errors
    ), exc.value.errors


def test_part_plan_with_carrier_part_datum_resolves(tmp_path: Path):
    _write_carrier(tmp_path, _carrier_manifest(with_part_datum=True))
    cell, root = _carrier_cell(tmp_path, dict(_CARRIER_BLOCK), plan_at_part=True)
    resolved = resolve_cell(cell, root)
    assert resolved.carrier is not None


def test_part_plan_with_fixture_part_datum_still_resolves(tmp_path: Path):
    # D4 widens the declaration to carriers; it does not move it off
    # fixtures -- a fixture-declared part_datum keeps working, no carrier.
    cell, root = _carrier_cell(tmp_path, carrier_block=None, plan_at_part=True, fixture_part_datum=True)
    resolved = resolve_cell(cell, root)
    assert resolved.carrier is None
