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
