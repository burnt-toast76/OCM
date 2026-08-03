# SPDX-License-Identifier: AGPL-3.0-or-later
"""ADR-0028 manifest-only refusals: the checks that need NO fragment --
duplicate joint within one capability's `actuates` (OCM_ACTUATION_CONFLICT)
and a unit outside BOTH explicit tables (OCM_UNIT_UNRECOGNISED). Which table
applies depends on the joint type, which lives in the fragment; that
coherence check is the generator's, deliberately not re-tested here.
Follows test_resolve_adr0027.py's structure."""

from __future__ import annotations

from typing import Any

from ocm_core import Module
from ocm_resolve import resolve_module


def _module_with_actuates(actuates: list[dict[str, Any]]) -> Module:
    return Module.from_dict({
        "ocm_version": "1.1",
        "id": "com.example.tool.actuated",
        "revision": "1.0.0",
        "kind": "fixture",
        "license": "CERN-OHL-S-2.0",
        "name": "Actuation test tool",
        "mechanical": {
            "mount": {"interface": "custom"},
            "frames": {"origin": {"xyz_mm": [0, 0, 0]}},
            "geometry": {"urdf_fragment": "urdf/t.urdf"},
            "mass_kg": 1.0,
        },
        "state_machine": {"model": "packml", "abort_safe": True},
        "capabilities": [{
            "name": "clamp",
            "summary": "Close the jaws.",
            "timeout_s": 3.0,
            "on_timeout": "hold",
            "actuates": actuates,
        }],
    })


def test_clean_actuates_produces_no_violations():
    module = _module_with_actuates([
        {"joint": "jaw_left", "to": 6.0, "units": "mm"},
        {"joint": "jaw_right", "to": -6.0, "units": "mm"},
        {"joint": "wrist", "to": 90.0, "units": "deg"},  # angular units accepted too
    ])
    assert resolve_module(module) == []


def test_same_joint_actuated_twice_in_one_capability_is_refused():
    module = _module_with_actuates([
        {"joint": "jaw_left", "to": 6.0, "units": "mm"},
        {"joint": "jaw_left", "to": 3.0, "units": "mm"},
    ])
    errors = resolve_module(module)
    assert any("actuates joint 'jaw_left' more than once" in e for e in errors), errors


def test_unit_in_neither_table_is_refused():
    module = _module_with_actuates([
        {"joint": "jaw_left", "to": 6.0, "units": "furlong"},
    ])
    errors = resolve_module(module)
    assert any("actuation unit 'furlong' is unrecognised" in e for e in errors), errors


def test_unit_recognised_by_either_table_passes_this_pass():
    # A length unit on what will turn out to be a revolute joint is the
    # GENERATOR's refusal (OCM_ACTUATION_UNIT_MISMATCH, needs the fragment);
    # this manifest-only pass accepts anything either table knows.
    module = _module_with_actuates([
        {"joint": "spin", "to": 45.0, "units": "mm"},  # possibly wrong for the joint -- not knowable here
    ])
    assert resolve_module(module) == []
