# SPDX-License-Identifier: AGPL-3.0-or-later
"""ADR-0031 D1: the carrier type -- Carrier.from_dict round-trips a
schema-valid manifest, load_carrier validates against the carrier schema,
and the control sections a carrier must never carry are schema-refused.
Fixture values are inline and obviously synthetic (ADR-0014: a real
pallet's frames and mass are the owner's to state)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from ocm_core import CARRIER_CONTROL_FIELDS, Carrier, ManifestValidationError, load_carrier
from ocm_core.loader import DEFAULT_CARRIER_SCHEMA_PATH, load_schema, validate_module_dict


def _carrier_dict() -> dict[str, Any]:
    return {
        "ocm_version": "1.1",
        "id": "com.example.carrier.test-pallet",
        "revision": "0.1.0",
        "name": "Test Pallet",
        "vendor": "Example",
        "license": "CERN-OHL-S-2.0",
        "description": "Synthetic test carrier.",
        "mechanical": {
            "mount": {"footprint_mm": [240, 240]},
            "frames": {
                "origin": {"xyz_mm": [0, 0, 0]},
                "part_datum": {"xyz_mm": [120, 120, 40], "note": "synthetic"},
            },
            "geometry": {"urdf_fragment": "urdf/pallet.urdf"},
            "mass_kg": 2.5,
            "com_mm": [120, 120, 20],
        },
    }


def test_carrier_from_dict_round_trips():
    carrier = Carrier.from_dict(_carrier_dict())
    assert carrier.id == "com.example.carrier.test-pallet"
    assert carrier.mechanical.mass_kg == 2.5
    assert carrier.mechanical.mount.footprint_mm == (240, 240)
    assert carrier.mechanical.origin.xyz_mm == (0, 0, 0)
    assert carrier.mechanical.part_datum is not None
    assert carrier.mechanical.part_datum.xyz_mm == (120, 120, 40)
    assert carrier.mechanical.geometry.urdf_fragment == "urdf/pallet.urdf"
    assert carrier.mechanical.com_mm == (120, 120, 20)


def test_carrier_dict_is_schema_valid():
    schema = load_schema(DEFAULT_CARRIER_SCHEMA_PATH)
    assert validate_module_dict(_carrier_dict(), schema) == []


@pytest.mark.parametrize("field", CARRIER_CONTROL_FIELDS)
def test_control_sections_are_schema_refused(field: str):
    # D1: additionalProperties:false refuses these structurally. The
    # NAMED refusal (OCM_CARRIER_TYPE_HAS_CONTROL) is validate_carrier's,
    # api-side -- this pins the schema floor underneath it.
    doc = _carrier_dict()
    doc[field] = {"model": "packml"} if field == "state_machine" else []
    schema = load_schema(DEFAULT_CARRIER_SCHEMA_PATH)
    errors = validate_module_dict(doc, schema)
    assert any(f"'{field}' was unexpected" in e for e in errors), errors


def test_load_carrier_validates_and_types(tmp_path: Path):
    path = tmp_path / "carrier.yaml"
    path.write_text(yaml.safe_dump(_carrier_dict()), encoding="utf-8")
    carrier = load_carrier(path)
    assert isinstance(carrier, Carrier)

    bad = _carrier_dict()
    del bad["mechanical"]["mass_kg"]
    path.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(ManifestValidationError):
        load_carrier(path)


def test_carrier_schema_frame_def_matches_the_module_schemas():
    # The carrier schema embeds $defs.frame rather than external-$ref-ing
    # the module schema (plain Draft202012Validator resolves no cross-file
    # refs), so THIS test is what keeps the two copies from drifting: they
    # must stay JSON-identical, or the shared definition gets lifted for
    # real.
    from ocm_core.loader import DEFAULT_SCHEMA_PATH

    module_schema = load_schema(DEFAULT_SCHEMA_PATH)
    carrier_schema = load_schema(DEFAULT_CARRIER_SCHEMA_PATH)
    assert carrier_schema["$defs"]["frame"] == module_schema["$defs"]["frame"]
