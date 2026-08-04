# SPDX-License-Identifier: AGPL-3.0-or-later
"""Schema-vs-model coverage for the CARRIER schema (ADR-0031 D1) -- the
same ADR-0015 pins-gap guard the module and cell schemas carry. Fails when
a property in ocm-carrier-1.0.schema.json has no corresponding field on
the ocm_core.carrier dataclass modelling that node."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from ocm_core import carrier as carrier_mod
from ocm_core import module as module_mod
from ocm_core import parameter as parameter_mod
from ocm_core.loader import DEFAULT_CARRIER_SCHEMA_PATH

from test_cell_schema_coverage import _all_object_nodes  # same tests dir (no package)

# Marker for schema nodes the model intentionally does not type.
OPAQUE = object()

REGISTRY: dict[str, object] = {
    "<root>": carrier_mod.Carrier,
    "<root>.mechanical": carrier_mod.CarrierMechanical,
    "<root>.mechanical.mount": carrier_mod.CarrierMount,
    # the frames CONTAINER is a plain dict[str, Frame] -- the per-frame
    # shape is covered by $defs.frame, same as the module registry.
    "<root>.mechanical.frames": OPAQUE,
    "<root>.mechanical.frames.<additionalProperties>": parameter_mod.Frame,
    # one Geometry model, shared with the module (ADR-0031 D1: no drifting
    # copy) -- the carrier schema's node is a subset of its fields.
    "<root>.mechanical.geometry": module_mod.Geometry,
    "$defs.frame": parameter_mod.Frame,
}


def test_every_carrier_schema_property_has_a_model_field():
    schema = json.loads(Path(DEFAULT_CARRIER_SCHEMA_PATH).read_text(encoding="utf-8"))
    nodes = list(_all_object_nodes(schema))
    assert len(nodes) >= 5, f"schema walk found only {len(nodes)} object nodes -- walker is broken"

    unmapped = sorted({loc for loc, _ in nodes if loc not in REGISTRY})
    assert not unmapped, f"carrier-schema object nodes with no model mapping: {unmapped}"

    missing: list[str] = []
    for loc, node in nodes:
        model = REGISTRY[loc]
        if model is OPAQUE:
            continue
        fields = {f.name for f in dataclasses.fields(model)}
        for prop in node["properties"]:
            if prop not in fields:
                missing.append(f"{loc}.{prop} (schema) has no field on {model.__name__}")
    assert not missing, "carrier-schema properties with no model field (the ADR-0015 pins gap):\n  " + "\n  ".join(missing)


def test_carrier_coverage_count_is_reported(capsys):
    schema = json.loads(Path(DEFAULT_CARRIER_SCHEMA_PATH).read_text(encoding="utf-8"))
    nodes = list(_all_object_nodes(schema))
    n_props = sum(len(node["properties"]) for _, node in nodes)
    print(f"\ncarrier-schema coverage: {n_props} properties across {len(nodes)} object nodes guarded")
    assert n_props > 0
