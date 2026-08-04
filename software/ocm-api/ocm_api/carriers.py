# SPDX-License-Identifier: AGPL-3.0-or-later
"""Carrier-type validation (ADR-0031 D1) -- one validation surface per
artifact kind, no weaker sibling (ADR-0016). A carrier is transcribed
hardware and must never carry `state_machine`, `comms`, or
`capabilities`: `additionalProperties: false` refuses them structurally,
but a carrier authored from a module template WILL carry those keys, and
a bare "additional property not allowed" tells the author nothing --
OCM_CARRIER_TYPE_HAS_CONTROL names the field and says why.
"""

from __future__ import annotations

import re

from ocm_core.carrier import CARRIER_CONTROL_FIELDS
from ocm_core.loader import load_schema, validate_module_dict

_ADDITIONAL_PROPS = re.compile(r"Additional properties are not allowed \((?P<names>.+?) (?:was|were) unexpected\)")


def _only_control_fields(error: str) -> bool:
    """True when this schema violation is the generic additional-property
    message AND every property it names is a control section -- the named
    OCM_CARRIER_TYPE_HAS_CONTROL refusal already said it better. A message
    mixing a control field with some other stray key is kept: the stray
    key still needs reporting.
    """
    m = _ADDITIONAL_PROPS.search(error)
    if m is None:
        return False
    names = re.findall(r"'([^']+)'", m["names"])
    return bool(names) and all(name in CARRIER_CONTROL_FIELDS for name in names)

from .envelope import Codes, Envelope, Refusal, single_refusal
from .translate import schema_violation_to_refusal
from .workspace import Workspace, read_yaml


def validate_carrier(ws: Workspace, carrier_id: str) -> Envelope:
    """Schema validation plus the carrier-specific checks: control-section
    fields refuse by name (see module docstring), and whatever geometry
    artifacts ARE declared must point at files that exist and (for the
    fragment) parse -- the same claim-nothing-backs rule validate_module
    applies (ADR-0016; ADR-0028 Erratum 1 for the parse).
    """
    if not ws.carrier_exists(carrier_id):
        return single_refusal(Codes.OCM_NOT_FOUND, path=f"carriers['{carrier_id}']", message=f"no carrier {carrier_id!r} in this workspace")

    doc = read_yaml(ws.carrier_path(carrier_id)) or {}

    # ADR-0031 D1: detect the control sections by name, BEFORE the generic
    # schema pass, and suppress the schema's own unhelpful duplicate.
    refusals: list[Refusal] = [
        Refusal(
            code=Codes.OCM_CARRIER_TYPE_HAS_CONTROL,
            path=field,
            message=(
                f"carrier type {doc.get('id', carrier_id)!r} declares {field!r} -- a carrier has no "
                "controller, no states, and no capabilities; a schema satisfied by a stub would be a "
                "fabrication (ADR-0014), so the field must go, not be filled in"
            ),
            hint="Delete the section. A pallet is commanded by nothing; identity and wear belong to the cell's ADR-0020 carriers block instead.",
        )
        for field in CARRIER_CONTROL_FIELDS
        if field in doc
    ]

    schema = load_schema(ws.carrier_schema_path)
    errors = validate_module_dict(doc, schema)
    refusals.extend(schema_violation_to_refusal(e) for e in errors if not _only_control_fields(e))

    carrier_dir = ws.carrier_dir(carrier_id)
    geometry = doc.get("mechanical", {}).get("geometry", {}) if isinstance(doc.get("mechanical"), dict) else {}
    for key in ("visual", "collision"):
        declared = geometry.get(key)
        if declared and not (carrier_dir / declared).is_file():
            refusals.append(
                Refusal(
                    code=Codes.OCM_NOT_FOUND,
                    path=f"mechanical.geometry.{key}",
                    message=f"{declared!r} does not exist under {carrier_dir}",
                )
            )
    urdf_fragment = geometry.get("urdf_fragment")
    if urdf_fragment and not (carrier_dir / urdf_fragment).is_file():
        refusals.append(
            Refusal(
                code=Codes.OCM_NOT_FOUND,
                path="mechanical.geometry.urdf_fragment",
                message=f"{urdf_fragment!r} does not exist under {carrier_dir}",
            )
        )
    elif urdf_fragment:
        from ocm_generator.scene.errors import FragmentError
        from ocm_generator.scene.urdf import load_fragment

        try:
            load_fragment(carrier_dir / urdf_fragment)
        except FragmentError as e:
            refusals.append(
                Refusal(
                    code=Codes.OCM_FRAGMENT_MALFORMED,
                    path="mechanical.geometry.urdf_fragment",
                    message=str(e),
                    hint="Fix the fragment's XML -- every fragment-dependent check is blind until it parses.",
                )
            )

    if refusals:
        return Envelope.refuse(refusals)
    return Envelope.succeed({"id": doc.get("id", carrier_id), "valid": True})
