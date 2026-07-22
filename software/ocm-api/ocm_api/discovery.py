# SPDX-License-Identifier: AGPL-3.0-or-later
"""Discovery verbs (spec/09: "the agent's eyes") -- read-only, never
refuse for reasons other than "doesn't exist". Everything here wraps
ocm_core's own loader/schema utilities and ocm_generator's scene builder;
no rule invented here duplicates a check that lives elsewhere.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from ocm_core import load_schema
from ocm_core.loader import validate_module_dict
from ocm_generator.scene import build_scene

from .envelope import Codes, Envelope, single_refusal
from .resolution import resolve_with_refusals
from .translate import schema_violation_to_refusal
from .workspace import Workspace, is_draft_revision, read_yaml

# kind -> the real, committed manifest that best demonstrates it. spec/09:
# "The worked examples are the real documentation."
EXAMPLE_MODULE_BY_KIND: dict[str, str] = {
    "end_effector": "com.accelsolutions.screwdriver.sd50",
    "process": "com.accelsolutions.dispense.dh200",
    "sensor": "com.lmi.gocator.2350",
    "fixture": "com.accelsolutions.fixture.pneumatic-nest",
    "feeder": "com.accelsolutions.screwfeeder.sf20",
    "base": "com.accelsolutions.base.frame1200",
    "robot": "com.universal-robots.ur5e",
}


def describe_schema(ws: Workspace, section: str | None = None, target: str = "module") -> Envelope:
    """`target` selects WHICH schema -- spec/09 originally wrote this verb
    with only modules in mind; ADR-0014 later gave components their own
    schema (spec/10), so a caller authoring a component (the /agent/chat
    tool loop, the Components page's schema-driven form) needs a way to
    ask for that one instead. Defaults to "module" -- every caller written
    before ADR-0014 (the MCP server's own module-authoring tools) keeps
    working unchanged.
    """
    if target not in ("module", "component"):
        return single_refusal(
            Codes.INVALID_ARGUMENT,
            path="target",
            message=f"target={target!r} is not 'module' or 'component'",
            allowed={"values": ["module", "component"]},
        )
    schema_path = ws.component_schema_path if target == "component" else ws.schema_path
    schema = load_schema(schema_path)
    subtree: Any = schema
    if section:
        subtree = schema.get("properties", {}).get(section) or schema.get("$defs", {}).get(section)
        if subtree is None:
            known = sorted(set(schema.get("properties", {})) | set(schema.get("$defs", {})))
            return single_refusal(
                Codes.NOT_FOUND,
                path=f"section='{section}'",
                message=f"no schema section {section!r} for target={target!r} (known: {known})",
                allowed={"values": known},
            )

    changelog = ws.changelog_path.read_text(encoding="utf-8") if ws.changelog_path.is_file() else ""
    return Envelope.succeed(
        {
            "ocm_version": schema.get("properties", {}).get("ocm_version", {}).get("enum", []),
            "target": target,
            "section": section,
            "schema": subtree,
            "changelog": changelog,
        }
    )


def get_example(ws: Workspace, kind: str) -> Envelope:
    module_id = EXAMPLE_MODULE_BY_KIND.get(kind)
    if module_id is None or not ws.module_exists(module_id):
        return single_refusal(
            Codes.NOT_FOUND,
            path=f"kind='{kind}'",
            message=f"no worked example registered for kind {kind!r} (known: {sorted(EXAMPLE_MODULE_BY_KIND)})",
            allowed={"values": sorted(EXAMPLE_MODULE_BY_KIND)},
        )
    path = ws.module_path(module_id)
    return Envelope.succeed(
        {"kind": kind, "module_id": module_id, "path": str(path), "manifest_yaml": path.read_text(encoding="utf-8")}
    )


def list_modules(ws: Workspace) -> Envelope:
    rows = []
    for module_id in ws.list_module_ids():
        data = read_yaml(ws.module_path(module_id)) or {}
        revision = str(data.get("revision", "0.0.0"))
        rows.append(
            {
                "id": data.get("id", module_id),
                "revision": revision,
                "kind": data.get("kind"),
                "name": data.get("name"),
                "draft": is_draft_revision(revision),
            }
        )
    return Envelope.succeed(rows)


def _component_aggregates(ws: Workspace, module_data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """ADR-0014: BOM, power budget, air consumption -- all DERIVED from a
    module's own `components:` list, never re-authored. Zero-assumption
    propagates into aggregation: a rail's/gas's total is only ever the sum
    of values every contributing component actually states; if even one
    doesn't state it, that aggregate is OMITTED entirely (never a partial
    sum passed off as a total) and a warning names the incomplete
    component -- the same "report the gap, don't guess" discipline
    authoring.py's own zero-assumption components already follow.

    Air consumption has its own extra way to be "incomplete": components
    record flow in whatever unit their own datasheet printed (flow_units,
    never converted at authoring time -- see ADR-0014/prompts.py), so two
    components stating flow in different units (one "Nl/min", one "SCFM")
    can't be summed into one number without silently pretending a
    conversion happened. That's treated the same as a missing value --
    omit the aggregate, name the mismatch in a warning -- rather than
    quietly summing mismatched units into a meaningless total.

    Returns ({} , []) for a module with no components: list at all (ADR-0014:
    "a module with no components list stays valid" -- nothing to derive).
    """
    components_list = module_data.get("components") or []
    if not components_list:
        return {}, []

    bom: list[dict[str, Any]] = []
    power_by_rail: dict[str, list[float | None]] = {}
    power_gap_notes: dict[str, list[str]] = {}
    air_values: list[float] = []
    air_units: set[str] = set()
    air_gap_notes: list[str] = []
    warnings: list[str] = []

    for mc in components_list:
        refdes = mc.get("refdes")
        ref = mc.get("ref", "")
        component_id, _, _revision = ref.partition("@")
        if not ws.component_exists(component_id):
            warnings.append(f"component {refdes} ({ref}) not found -- its BOM/power/air contribution is omitted")
            bom.append({"refdes": refdes, "id": component_id, "vendor": None, "part_number": None})
            continue

        cdata = read_yaml(ws.component_path(component_id)) or {}
        component_label = f"{refdes} ({cdata.get('id', component_id)})"
        bom.append({"refdes": refdes, "id": cdata.get("id", component_id), "vendor": cdata.get("vendor"), "part_number": cdata.get("part_number")})

        for supply in (cdata.get("electrical") or {}).get("supplies", []):
            rail = supply.get("rail")
            if rail is None:
                continue
            current = supply.get("current_nominal_a")
            power_by_rail.setdefault(rail, []).append(current)
            if current is None:
                power_gap_notes.setdefault(rail, []).append(f"{component_label} doesn't state current_nominal_a")

        pneumatic = cdata.get("pneumatic")
        if pneumatic:
            flow = pneumatic.get("flow")
            flow_units = pneumatic.get("flow_units")
            if flow is None:
                air_gap_notes.append(f"{component_label} doesn't state flow")
            elif not flow_units:
                air_gap_notes.append(f"{component_label} states flow but not flow_units")
            else:
                air_values.append(flow)
                air_units.add(flow_units)

    aggregates: dict[str, Any] = {"bom": bom}

    power_budget = {rail: {"current_nominal_a": sum(currents)} for rail, currents in power_by_rail.items() if rail not in power_gap_notes}
    if power_budget:
        aggregates["power_budget"] = power_budget
    for rail, notes in power_gap_notes.items():
        warnings.append(f"power budget for {rail} is incomplete: " + "; ".join(notes))

    if air_gap_notes:
        warnings.append("air consumption is incomplete: " + "; ".join(air_gap_notes))
    elif len(air_units) > 1:
        warnings.append(f"air consumption mixes units across components ({', '.join(sorted(air_units))}) -- not summed")
    elif air_values:
        aggregates["air_consumption"] = sum(air_values)
        aggregates["air_consumption_units"] = next(iter(air_units))

    return aggregates, warnings


def describe_module(ws: Workspace, module_id: str) -> Envelope:
    if not ws.module_exists(module_id):
        return single_refusal(Codes.NOT_FOUND, path=f"modules['{module_id}']", message=f"no module {module_id!r} in this workspace")

    data = read_yaml(ws.module_path(module_id)) or {}
    schema = load_schema(ws.schema_path)
    errors = validate_module_dict(data, schema)
    revision = str(data.get("revision", "0.0.0"))
    payload = {"id": data.get("id", module_id), "revision": revision, "draft": is_draft_revision(revision), "manifest": data}

    if errors:
        return Envelope.refuse([schema_violation_to_refusal(e) for e in errors])

    aggregates, warnings = _component_aggregates(ws, data)
    if aggregates:
        payload["aggregates"] = aggregates
    return Envelope.succeed(payload, warnings=warnings)


def list_cells(ws: Workspace) -> Envelope:
    rows = []
    for cell_id in ws.list_cell_ids():
        data = read_yaml(ws.cell_path(cell_id)) or {}
        rows.append({"cell_id": cell_id, "id": data.get("id"), "name": data.get("name")})
    return Envelope.succeed(rows)


def describe_cell(ws: Workspace, cell_id: str) -> Envelope:
    from ocm_core.cell import Cell

    if not ws.cell_exists(cell_id):
        return single_refusal(Codes.NOT_FOUND, path=f"cells['{cell_id}']", message=f"no cell {cell_id!r} in this workspace")

    data = read_yaml(ws.cell_path(cell_id)) or {}
    payload: dict[str, Any] = {"cell_id": cell_id, "id": data.get("id"), "name": data.get("name"), "cell": data}

    warnings: list[str] = []
    try:
        cell = Cell.from_dict(data)
    except (KeyError, ValueError) as e:
        warnings.append(f"cell document is structurally incomplete: {e}")
        return Envelope.succeed(payload, warnings=warnings)

    resolved, refusals = resolve_with_refusals(cell, ws)
    if resolved is None:
        warnings.extend(r.message for r in refusals)
        return Envelope.succeed(payload, warnings=warnings)

    payload["instances"] = [
        {
            "instance": name,
            "module": f"{ri.module.id}@{ri.module.revision}",
            "mounted_on": ri.mounted_on.name if ri.mounted_on is not None else None,
        }
        for name, ri in sorted(resolved.instances.items())
    ]
    payload["plan_step_count"] = len(cell.plan)
    return Envelope.succeed(payload, warnings=warnings)


def list_frames(ws: Workspace, cell_id: str) -> Envelope:
    from ocm_core.cell import Cell

    if not ws.cell_exists(cell_id):
        return single_refusal(Codes.NOT_FOUND, path=f"cells['{cell_id}']", message=f"no cell {cell_id!r} in this workspace")

    data = read_yaml(ws.cell_path(cell_id)) or {}
    cell = Cell.from_dict(data)
    resolved, refusals = resolve_with_refusals(cell, ws)
    if resolved is None:
        return Envelope.refuse(refusals)

    scene = build_scene(resolved, ws.modules_dir)
    root = ET.fromstring(scene.urdf_xml)
    known_links = {link.get("name") for link in root.findall("link") if link.get("name")}

    frames: set[str] = set()
    all_instances = {"base": resolved.base, **{name: ri.module for name, ri in resolved.instances.items()}}
    scene_instances = {"base": scene.base, **scene.instances}
    for instance_name, module in all_instances.items():
        for frame_name in module.mechanical.frames:
            frames.add(f"{instance_name}.{frame_name}")
        prefix = f"{instance_name}__"
        for link_name in scene_instances[instance_name].link_names:
            if link_name in known_links and link_name.startswith(prefix):
                frames.add(f"{instance_name}.{link_name[len(prefix):]}")

    return Envelope.succeed(sorted(frames))
