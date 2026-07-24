# SPDX-License-Identifier: AGPL-3.0-or-later
"""A field the schema declares but the dataclass silently drops is a real,
repeatable bug (ComponentConnector.pins was exactly this: the schema and
every on-disk YAML carried it, ocm-core just never modeled it, and nobody
noticed until it was found by hand). This walks BOTH schemas' own
"properties" trees and, for every object node, asserts every schema
property has a same-named field on the dataclass ocm_core maps that node
to -- so this class of bug fails a test instead of waiting to be found by
hand a second time.

Deliberately schema -> model only (not the reverse): a dataclass field with
no schema counterpart is either a load-bearing internal-only field or dead
code, neither of which this test is about.
"""

from __future__ import annotations

import json
import types
from dataclasses import is_dataclass
from typing import Any, Union, get_args, get_origin, get_type_hints

from ocm_core.component import Component
from ocm_core.module import Endpoint, Module, Net

# Every optional field in ocm_core is written `X | None` (PEP 604), which
# get_type_hints resolves to types.UnionType, NOT typing.Union -- but check
# both so this doesn't silently stop working if that style ever changes.
UNION_TYPES = (types.UnionType, Union)


def _resolve_ref(schema_root: dict, node: dict) -> dict:
    if "$ref" in node:
        ref = node["$ref"]
        assert ref.startswith("#/$defs/"), f"unsupported $ref shape: {ref!r}"
        return schema_root["$defs"][ref[len("#/$defs/") :]]
    return node


def _unwrap_to_dataclass(py_type: Any) -> Any | None:
    """Peels Optional[...]/tuple[...]/dict[str, ...] wrappers down to a bare
    dataclass, mirroring exactly what every from_dict in this package does
    (Optional -> None default, tuple -> repeated items, dict -> keyed
    items). Returns None once it bottoms out at something that isn't a
    dataclass (a plain str/float/bool/Any leaf, or an unrecognized shape) --
    those have no further schema-vs-model correspondence to check.
    """
    origin = get_origin(py_type)
    if origin in UNION_TYPES:
        args = [a for a in get_args(py_type) if a is not type(None)]
        return _unwrap_to_dataclass(args[0]) if len(args) == 1 else None
    if origin in (tuple, list):
        args = get_args(py_type)
        return _unwrap_to_dataclass(args[0]) if args else None
    if origin is dict:
        args = get_args(py_type)
        return _unwrap_to_dataclass(args[1]) if len(args) == 2 else None
    if is_dataclass(py_type):
        return py_type
    return None


def _check_node(schema_root: dict, schema_node: dict, py_type: Any, path: str, errors: list[str]) -> None:
    node = _resolve_ref(schema_root, schema_node)
    dc = _unwrap_to_dataclass(py_type)
    if dc is None:
        return  # the Python side is a scalar (or Any/dict[str, str]/...) -- nothing further to structurally check

    # dict[str, X]-shaped node, e.g. mechanical.frames or capabilities[].parameters:
    # additionalProperties IS the per-value schema; any "properties" alongside
    # it are just documented example keys, not real fields to check against dc.
    additional = node.get("additionalProperties")
    if isinstance(additional, dict) and ("$ref" in additional or additional.get("type") == "object" or additional.get("properties")):
        _check_node(schema_root, additional, dc, path + "{}", errors)
        return

    if node.get("type") == "array":
        item_schema = node.get("items")
        if item_schema:
            _check_node(schema_root, item_schema, dc, path + "[]", errors)
        return

    props = node.get("properties")
    if not props:
        return
    if not is_dataclass(dc):
        errors.append(f"{path}: schema declares object properties but the mapped type {dc!r} isn't a dataclass")
        return

    field_types = get_type_hints(dc)
    for key, subschema in props.items():
        if key not in field_types:
            errors.append(f"{path}.{key}: schema property has no matching field on {dc.__name__} -- silently dropped by from_dict")
            continue
        _check_node(schema_root, subschema, field_types[key], f"{path}.{key}", errors)


def test_component_schema_fields_all_have_a_matching_dataclass_field(component_schema_path):
    schema = json.loads(component_schema_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    _check_node(schema, schema, Component, "component", errors)
    assert not errors, "schema field(s) silently dropped by ocm_core.component's object model:\n" + "\n".join(errors)


def test_module_schema_fields_all_have_a_matching_dataclass_field(schema_path):
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    _check_node(schema, schema, Module, "module", errors)
    assert not errors, "schema field(s) silently dropped by ocm_core.module's object model:\n" + "\n".join(errors)


def test_module_connectivity_types_are_covered(schema_path):
    """ADR-0015's ports/nets/links, on top of the same generic walker the
    ComponentPin fix (b70f357) built -- the whole-module test above already
    walks these for free (no code change was needed to cover them), but
    this pins that down explicitly and scopes it to just the new types, so
    it can't quietly regress even if the bigger test's own shape changes
    later. $defs/endpoint is checked directly too: it's reused from THREE
    call sites (nets.electrical[].endpoints[], nets.pneumatic[].endpoints[],
    links[].a/b) and every one of them must independently resolve to the
    real Endpoint dataclass, not just the first.
    """
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    field_types = get_type_hints(Module)
    errors: list[str] = []
    _check_node(schema, schema["$defs"]["endpoint"], Endpoint, "$defs.endpoint", errors)
    _check_node(schema, schema["$defs"]["net"], Net, "$defs.net", errors)
    _check_node(schema, schema["properties"]["ports"], field_types["ports"], "module.ports", errors)
    _check_node(schema, schema["properties"]["nets"], field_types["nets"], "module.nets", errors)
    _check_node(schema, schema["properties"]["links"], field_types["links"], "module.links", errors)
    assert not errors, "ADR-0015 connectivity field(s) silently dropped:\n" + "\n".join(errors)
