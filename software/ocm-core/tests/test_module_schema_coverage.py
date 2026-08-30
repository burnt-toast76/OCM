# SPDX-License-Identifier: AGPL-3.0-or-later
"""Schema-vs-model coverage for the MODULE schema -- the same ADR-0015 pins-gap
guard test_cell_schema_coverage.py applies to the cell schema (that gap WAS a
module-schema bug: ComponentConnector silently dropped `pins` and the resolver
went blind). Fails when a property in ocm-module-1.0.schema.json has no
corresponding field on the ocm_core.module dataclass modelling that node.

Nodes the model deliberately keeps raw are mapped to OPAQUE -- an explicit,
reviewed escape, not a silent skip.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from ocm_core import module as module_mod
from ocm_core import parameter as parameter_mod
from ocm_core.loader import DEFAULT_SCHEMA_PATH

from test_cell_schema_coverage import _all_object_nodes  # same tests dir (no package)

# Marker for schema nodes the model intentionally does not type.
OPAQUE = object()

REGISTRY: dict[str, object] = {
    "<root>": module_mod.Module,
    "<root>.mechanical": module_mod.Mechanical,
    "<root>.mechanical.mount": module_mod.Mount,
    # the frames CONTAINER is a plain dict[str, Frame] on Mechanical -- the
    # per-frame shape is covered by $defs.frame / the additionalProperties map.
    "<root>.mechanical.frames": OPAQUE,
    "<root>.mechanical.frames.<additionalProperties>": parameter_mod.Frame,
    "<root>.mechanical.geometry": module_mod.Geometry,
    "<root>.mechanical.structure[]": module_mod.StructurePrimitive,
    "<root>.mechanical.structure[].pose": module_mod.StructurePose,
    # ADR-0031 D3: the located datum. The per-constraint tolerance map is a
    # plain dict[str, DofTolerance]; its value shape is $defs.dof_tolerance.
    "<root>.mechanical.located": module_mod.Located,
    "<root>.mechanical.located.constraints[]": module_mod.LocatedConstraint,
    "$defs.dof_tolerance": module_mod.DofTolerance,
    "<root>.electrical": module_mod.Electrical,
    "<root>.electrical.supplies[]": module_mod.Supply,
    "<root>.electrical.pneumatic": module_mod.Pneumatic,
    "<root>.electrical.connectors[]": module_mod.Connector,
    "<root>.electrical.connectors[].pins[]": module_mod.Pin,
    "<root>.comms": module_mod.Comms,
    "<root>.comms.signals[]": module_mod.Signal,
    "<root>.capabilities[]": module_mod.Capability,
    "<root>.capabilities[].actuates[]": module_mod.Actuation,
    "<root>.capabilities[].motion": module_mod.Motion,
    "<root>.capabilities[].motion.path": module_mod.PathSpec,
    "<root>.capabilities[].requires.<additionalProperties>": module_mod.Requirement,
    "<root>.process": module_mod.Process,
    "<root>.state_machine": module_mod.StateMachine,
    "<root>.safety": module_mod.Safety,
    "<root>.maintenance": module_mod.Maintenance,
    "<root>.maintenance.wear_items[]": module_mod.WearItem,
    "<root>.components[]": module_mod.ModuleComponent,
    "<root>.ports[]": module_mod.Port,
    "<root>.nets": module_mod.Nets,
    "$defs.frame": parameter_mod.Frame,
    "$defs.endpoint": module_mod.Endpoint,
    "$defs.net": module_mod.Net,
    "$defs.instance_pose": module_mod.InstancePose,
    "$defs.parameter": parameter_mod.Parameter,
    "<root>.links[]": module_mod.Link,
}

# Field-name aliases: schema property -> model field, where the model
# deliberately renames (each is a reviewed exception, like OPAQUE).
ALIASES: dict[tuple[object, str], str] = {}


def test_every_module_schema_property_has_a_model_field():
    schema = json.loads(Path(DEFAULT_SCHEMA_PATH).read_text(encoding="utf-8"))
    nodes = list(_all_object_nodes(schema))
    assert len(nodes) >= 20, f"schema walk found only {len(nodes)} object nodes -- walker is broken"

    unmapped = sorted({loc for loc, _ in nodes if loc not in REGISTRY})
    assert not unmapped, f"module-schema object nodes with no model mapping: {unmapped}"

    missing: list[str] = []
    for loc, node in nodes:
        model = REGISTRY[loc]
        if model is OPAQUE:
            continue
        fields = {f.name for f in dataclasses.fields(model)}
        for prop in node["properties"]:
            target = ALIASES.get((model, prop), prop)
            if target not in fields:
                missing.append(f"{loc}.{prop} (schema) has no field on {model.__name__}")
    assert not missing, "module-schema properties with no model field (the ADR-0015 pins gap):\n  " + "\n  ".join(missing)


def test_module_coverage_count_is_reported(capsys):
    schema = json.loads(Path(DEFAULT_SCHEMA_PATH).read_text(encoding="utf-8"))
    nodes = list(_all_object_nodes(schema))
    n_props = sum(len(node["properties"]) for _, node in nodes)
    print(f"\nmodule-schema coverage: {n_props} properties across {len(nodes)} object nodes guarded")
    assert n_props > 0
