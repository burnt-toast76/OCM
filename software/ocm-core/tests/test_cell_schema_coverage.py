# SPDX-License-Identifier: AGPL-3.0-or-later
"""Schema-vs-model coverage for the cell schema.

ADR-0015's `ComponentConnector` silently dropped `pins`: the schema and the
on-disk YAML both had them, the typed model didn't, and the resolver went blind.
This test makes that class of bug impossible for the cell schema -- it fails when
a property in `spec/schema/ocm-cell-1.0.schema.json` has no corresponding field
on the `ocm_core.cell` dataclass that models that node.

Every object node in the schema (the root, every `$defs` entry, and every inline
nested object) is mapped to the dataclass that models it. A node with no mapping
is a failure (add the model, then map it); a schema property with no model field
is a failure (add the field). Nodes with no `properties` (opaque `part`/`plan`,
arrays, scalars) model nothing and are skipped.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from ocm_core import cell as cell_mod
from ocm_core.loader import DEFAULT_CELL_SCHEMA_PATH

# schema-node location -> the dataclass that models it. Location is a structural
# path: "<root>" and its inline descendants, or "$defs.<name>" for a $def and its
# inline descendants. $ref targets are covered once, under their $def.
REGISTRY: dict[str, type] = {
    "<root>": cell_mod.Cell,
    "<root>.base": cell_mod.Base,
    "<root>.controller": cell_mod.Controller,
    "<root>.safety": cell_mod.CellSafety,
    "<root>.nets": cell_mod.Nets,
    "<root>.identity": cell_mod.Identity,
    "<root>.carriers": cell_mod.Carriers,
    "<root>.record_sink": cell_mod.RecordSink,
    "<root>.record_sink.journal": cell_mod.Journal,
    "<root>.record_sink.forward[]": cell_mod.ForwardTarget,
    "<root>.produces": cell_mod.Produces,
    "<root>.produces.measurements[]": cell_mod.Measurement,
    "<root>.produces.verdict": cell_mod.Verdict,
    "<root>.produces.record_keys": cell_mod.RecordKeys,
    "<root>.mode_selector": cell_mod.ModeSelector,
    "$defs.instance_pose": cell_mod.Pose,
    "$defs.consumable": cell_mod.Consumable,
    "$defs.module_instance": cell_mod.ModuleInstance,
    "$defs.module_instance.mount": cell_mod.InstanceMount,
    "$defs.module_instance.address": cell_mod.InstanceAddress,
    "$defs.port": cell_mod.Port,
    "$defs.endpoint": cell_mod.Endpoint,
    "$defs.net": cell_mod.Net,
    "$defs.link": cell_mod.Link,
    # "$defs.module_ref" is a bare string (no properties) -- nothing to model.
}


def _object_nodes(node: dict, location: str):
    """Yield (location, node) for every object node carrying `properties`,
    walking inline children but NOT following `$ref` (its target is walked once
    under its own `$defs.<name>` location).
    """
    if not isinstance(node, dict):
        return
    if "$ref" in node:
        return
    if node.get("type") == "object" and "properties" in node:
        yield location, node
        for prop, child in node["properties"].items():
            yield from _object_nodes(child, f"{location}.{prop}")
        addl = node.get("additionalProperties")
        if isinstance(addl, dict):
            yield from _object_nodes(addl, f"{location}.<additionalProperties>")
    elif node.get("type") == "array":
        items = node.get("items")
        if isinstance(items, dict):
            yield from _object_nodes(items, f"{location}[]")


def _all_object_nodes(schema: dict):
    yield from _object_nodes(schema, "<root>")
    for name, defn in schema.get("$defs", {}).items():
        yield from _object_nodes(defn, f"$defs.{name}")


def test_every_cell_schema_property_has_a_model_field():
    schema = json.loads(Path(DEFAULT_CELL_SCHEMA_PATH).read_text(encoding="utf-8"))
    nodes = list(_all_object_nodes(schema))
    # Guard the guard: if the walk finds nothing, the test proves nothing.
    assert len(nodes) >= 20, f"schema walk found only {len(nodes)} object nodes -- walker is broken"

    unmapped = sorted({loc for loc, _ in nodes if loc not in REGISTRY})
    assert not unmapped, f"schema object nodes with no model mapping (add the model + REGISTRY entry): {unmapped}"

    missing: list[str] = []
    for loc, node in nodes:
        model = REGISTRY[loc]
        fields = {f.name for f in dataclasses.fields(model)}
        for prop in node["properties"]:
            if prop not in fields:
                missing.append(f"{loc}.{prop} (schema) has no field on {model.__name__}")
    assert not missing, "schema properties with no model field (the ADR-0015 pins gap):\n  " + "\n  ".join(missing)


def test_coverage_count_is_reported(capsys):
    """Emits the number of schema properties the coverage test guards -- surfaced
    in the run log and reported in the task summary.
    """
    schema = json.loads(Path(DEFAULT_CELL_SCHEMA_PATH).read_text(encoding="utf-8"))
    nodes = list(_all_object_nodes(schema))
    n_props = sum(len(node["properties"]) for _, node in nodes)
    print(f"\ncell-schema coverage: {n_props} properties across {len(nodes)} object nodes guarded")
    assert n_props > 0
