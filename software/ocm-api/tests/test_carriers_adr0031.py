# SPDX-License-Identifier: AGPL-3.0-or-later
"""ADR-0031 part 1, api-side: validate_carrier is the one validation
surface for a carrier type (ADR-0016 -- no weaker sibling), and a carrier
carrying a control section refuses OCM_CARRIER_TYPE_HAS_CONTROL naming
the field, not a bare additional-property message. Plus the translate.py
mapping for the resolve-side located refusals. Fixtures are inline and
obviously synthetic (ADR-0014)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ocm_api import Codes, OcmApi
from ocm_api.translate import resolve_error_to_refusal

_FRAGMENT = """<?xml version="1.0"?>
<robot name="frag">
  <link name="origin"><collision><geometry><box size="0.24 0.24 0.02"/></geometry></collision></link>
</robot>
"""


def _carrier_dict() -> dict[str, Any]:
    return {
        "ocm_version": "1.1",
        "id": "com.example.carrier.test-pallet",
        "revision": "0.1.0",
        "name": "Test Pallet",
        "license": "CERN-OHL-S-2.0",
        "mechanical": {
            "frames": {"origin": {"xyz_mm": [0, 0, 0]}, "part_datum": {"xyz_mm": [120, 120, 40]}},
            "geometry": {"urdf_fragment": "urdf/pallet.urdf"},
            "mass_kg": 2.5,
        },
    }


def _write_carrier(workspace_root: Path, doc: dict[str, Any], fragment: str | None = _FRAGMENT) -> None:
    carrier_dir = workspace_root / "carriers" / doc["id"]
    carrier_dir.mkdir(parents=True, exist_ok=True)
    (carrier_dir / "carrier.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")
    if fragment is not None:
        (carrier_dir / "urdf").mkdir(exist_ok=True)
        (carrier_dir / "urdf" / "pallet.urdf").write_text(fragment, encoding="utf-8")


def test_clean_carrier_validates_ok(api: OcmApi, workspace_root: Path):
    _write_carrier(workspace_root, _carrier_dict())
    e = api.validate_carrier("com.example.carrier.test-pallet")
    assert e.ok, e.refusals
    assert e.data == {"id": "com.example.carrier.test-pallet", "valid": True}


def test_carrier_with_state_machine_refuses_naming_the_field(api: OcmApi, workspace_root: Path):
    doc = _carrier_dict()
    # A carrier authored from a module template: the control sections came
    # along for the ride.
    doc["state_machine"] = {"model": "packml", "abort_safe": True}
    doc["capabilities"] = []
    _write_carrier(workspace_root, doc)

    e = api.validate_carrier("com.example.carrier.test-pallet")
    assert not e.ok
    codes_and_paths = {(r.code, r.path) for r in e.refusals}
    assert (Codes.OCM_CARRIER_TYPE_HAS_CONTROL, "state_machine") in codes_and_paths
    assert (Codes.OCM_CARRIER_TYPE_HAS_CONTROL, "capabilities") in codes_and_paths
    r = next(r for r in e.refusals if r.path == "state_machine")
    assert "no controller, no states, and no capabilities" in r.message
    # The generic schema "additional property" duplicate is suppressed --
    # the named refusal IS the message.
    assert not any(
        r.code == Codes.OCM_SCHEMA_INVALID and "state_machine" in r.message for r in e.refusals
    )


def test_declared_fragment_must_exist_and_parse(api: OcmApi, workspace_root: Path):
    _write_carrier(workspace_root, _carrier_dict(), fragment=None)
    e = api.validate_carrier("com.example.carrier.test-pallet")
    assert not e.ok
    assert any(r.code == Codes.OCM_NOT_FOUND and r.path == "mechanical.geometry.urdf_fragment" for r in e.refusals)

    _write_carrier(workspace_root, _carrier_dict(), fragment="<robot><link name='unterminated></robot>")
    e = api.validate_carrier("com.example.carrier.test-pallet")
    assert not e.ok
    assert any(r.code == Codes.OCM_FRAGMENT_MALFORMED for r in e.refusals)


def test_unknown_carrier_refuses_not_found(api: OcmApi):
    e = api.validate_carrier("com.example.carrier.ghost")
    assert not e.ok
    assert e.refusals[0].code == Codes.OCM_NOT_FOUND


def test_located_resolve_errors_map_to_their_codes():
    # The resolve-side located errors ride the same module-error channel as
    # every other manifest refusal; the mapping is what makes them codes.
    prefix = "module conv1 (com.example.conveyor.locating): "
    cases = {
        prefix + "located.frame 'ghost' is not a declared mechanical.frames entry (has: ['origin'])":
            Codes.OCM_LOCATED_FRAME_UNKNOWN,
        prefix + "located constraints govern nothing for 'rz' -- the constraint scheme does not close":
            Codes.OCM_LOCATED_DOF_UNGOVERNED,
        prefix + "located DOF 'z' is governed by both 'lift_stop_surface' and 'locating_pins' -- the constraint scheme does not close":
            Codes.OCM_LOCATED_DOF_OVERCONSTRAINED,
        prefix + "located feature 'lift_stop_surface' governs rx but declares no tolerance for it":
            Codes.OCM_LOCATED_TOLERANCE_MISSING,
        prefix + "located feature 'locating_pins' gives x an angular unit 'deg'; a linear DOF takes a length (['mm', 'cm', 'm', 'in', 'ft'])":
            Codes.OCM_LOCATED_UNIT_MISMATCH,
        prefix + "located feature 'locating_pins' tolerance unit 'furlongs' is unrecognised (known: [...])":
            Codes.OCM_UNIT_UNRECOGNISED,
    }
    for error, expected_code in cases.items():
        refusal = resolve_error_to_refusal(error)
        assert refusal.code == expected_code, (error, refusal.code)
        assert refusal.message == error
