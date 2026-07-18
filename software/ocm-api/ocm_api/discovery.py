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


def describe_schema(ws: Workspace, section: str | None = None) -> Envelope:
    schema = load_schema(ws.schema_path)
    subtree: Any = schema
    if section:
        subtree = schema.get("properties", {}).get(section) or schema.get("$defs", {}).get(section)
        if subtree is None:
            known = sorted(set(schema.get("properties", {})) | set(schema.get("$defs", {})))
            return single_refusal(
                Codes.NOT_FOUND,
                path=f"section='{section}'",
                message=f"no schema section {section!r} (known: {known})",
                allowed={"values": known},
            )

    changelog = ws.changelog_path.read_text(encoding="utf-8") if ws.changelog_path.is_file() else ""
    return Envelope.succeed(
        {
            "ocm_version": schema.get("properties", {}).get("ocm_version", {}).get("enum", []),
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
    return Envelope.succeed(payload)


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
