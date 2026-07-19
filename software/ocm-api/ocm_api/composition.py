# SPDX-License-Identifier: AGPL-3.0-or-later
"""Cell composition verbs (spec/09). Every mutation (`place_instance`,
`move_instance`, `remove_instance`, `set_plan`, `set_joint_state`) writes
the change to `cell.yaml` UNCONDITIONALLY, then re-resolves and rebuilds
the scene, returning whatever refusals that turns up -- spec/09: "Each
call re-resolves and returns the envelope -- live refusals... This is the
GUI's drag handler and the agent's placement tool: same verb." The write
happens either way (design principle #3: "files are the state"); the
envelope just tells the caller whether what they wrote is any good.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Callable

from ocm_core import ModuleRef
from ocm_core.cell import Cell
from ocm_generator.scene import SceneBuildError, base_footprint_mm, build_scene
from ocm_resolve.plan_walk import iter_op_steps

from .envelope import Codes, Envelope, Refusal, single_refusal
from .resolution import resolve_with_refusals
from .translate import scene_error_to_refusal
from .workspace import Workspace, read_yaml, write_yaml


def create_cell(ws: Workspace, cell_id: str, base_module: str) -> Envelope:
    if ws.cell_exists(cell_id):
        return single_refusal(Codes.ALREADY_EXISTS, path=f"cells['{cell_id}']", message=f"a cell {cell_id!r} already exists")
    try:
        ModuleRef.parse(base_module)
    except ValueError as e:
        return single_refusal(Codes.INVALID_ARGUMENT, path="base_module", message=str(e))

    doc: dict[str, Any] = {
        "ocm_version": "1.0",
        "kind": "cell",
        "id": f"com.example.cell.{cell_id}",
        "name": cell_id,
        "license": "CERN-OHL-S-2.0",
        "base": {"module": base_module, "datum": "cell_origin", "grid": "ocm-base-grid-50"},
        "modules": [],
        "plan": [],
    }
    write_yaml(ws.cell_path(cell_id), doc)
    return Envelope.succeed({"cell_id": cell_id, "id": doc["id"], "path": str(ws.cell_path(cell_id))})


def _workspace_bounds_mm(scene: Any) -> dict[str, Any] | None:
    """The base module's own X/Y footprint, in mm -- exactly what a
    WORKSPACE_OVERHANG refusal's `allowed.footprint` already names, but
    surfaced on every composition call (not just a failing one) so an
    agent's mental model of "how much room do I have" comes from data,
    not from tripping the tolerance once and reading the refusal message.
    That tolerance is real geometry (the base module's own guard walls,
    which sit outside its nominal footprint_mm), not a magic number this
    package invented -- see ocm_generator.scene.containment.
    """
    bounds = base_footprint_mm(scene.urdf_xml, scene.joint_state, scene.base.link_names)
    if bounds is None:
        return None
    lo, hi = bounds
    return {"x_mm": [round(lo[0] * 1000, 1), round(hi[0] * 1000, 1)], "y_mm": [round(lo[1] * 1000, 1), round(hi[1] * 1000, 1)]}


def _find_tool_slot_incumbent(modules: list[dict[str, Any]], mount_on: str, exclude_instance: str | None = None) -> str | None:
    """The instance (if any) already occupying `mount_on` (e.g.
    'robot1.flange') -- `exclude_instance` lets move_instance check without
    tripping over the instance's own current entry.
    """
    for m in modules:
        if m.get("instance") == exclude_instance:
            continue
        existing_mount = m.get("mount")
        if isinstance(existing_mount, dict) and existing_mount.get("on") == mount_on:
            return m.get("instance")
    return None


def _tool_slot_refusal(instance: str, mount_on: str, incumbent: str) -> Refusal:
    return Refusal(
        code=Codes.TOOL_SLOT_OCCUPIED,
        path=f"modules['{instance}'].mount.on",
        message=f"{mount_on} is already occupied by {incumbent!r} -- cannot also place {instance!r} there",
        hint=f"remove_instance({incumbent!r}) first if you mean to swap tools -- place_instance never evicts or swaps automatically.",
    )


def _orphan_warnings(doc: dict[str, Any], removed_instance: str) -> list[str]:
    """spec: mutations that orphan plan steps (remove_instance, tool
    swaps) report the impact even when the call itself otherwise succeeds.
    Two independent kinds of dangling reference, both by instance NAME
    (never by mount position, which is free to be reused):

    - A plan step naming `removed_instance` as its `module` -- this also
      trips resolve_cell's own hard UNKNOWN_MODULE check (same
      iter_op_steps walk), so it typically coincides with ok=false; the
      warning still adds the human-readable "you just removed X, here's
      the blast radius" summary a bare per-step refusal list doesn't.
    - Another instance's `tool:` field (e.g. robot1's `tool: grip1`,
      spec/02's "which end effector is currently mounted" convention) --
      NOT cross-checked by resolve_cell at all, so this one silently
      succeeds (ok=true) unless flagged here.
    """
    warnings: list[str] = []

    orphaned_ops = [step.get("op", "?") for _location, step in iter_op_steps(doc.get("plan", [])) if step.get("module") == removed_instance]
    if orphaned_ops:
        counts = Counter(orphaned_ops)
        summary = ", ".join(f"{op} ×{n}" for op, n in sorted(counts.items()))
        plural = "s" if len(orphaned_ops) != 1 else ""
        warnings.append(f"removing {removed_instance} orphans {len(orphaned_ops)} plan step{plural} ({summary}); the plan will no longer resolve.")

    stale_tool_holders = sorted(m.get("instance") for m in doc.get("modules", []) if m.get("tool") == removed_instance)
    for holder in stale_tool_holders:
        warnings.append(f"removing {removed_instance} leaves {holder}.tool pointing at a removed instance -- update {holder}'s tool: field.")

    return warnings


def _mutate_and_resolve(ws: Workspace, cell_id: str, mutate: Callable[[dict[str, Any], list[str]], Refusal | None]) -> Envelope:
    if not ws.cell_exists(cell_id):
        return single_refusal(Codes.NOT_FOUND, path=f"cells['{cell_id}']", message=f"no cell {cell_id!r} in this workspace")

    doc = read_yaml(ws.cell_path(cell_id)) or {}
    warnings: list[str] = []
    refusal = mutate(doc, warnings)
    if refusal is not None:
        return Envelope.refuse([refusal], warnings=warnings)

    write_yaml(ws.cell_path(cell_id), doc)

    try:
        cell = Cell.from_dict(doc)
    except (KeyError, ValueError) as e:
        return single_refusal(Codes.CELL_INVALID, path="$", message=f"cell document is structurally incomplete: {e}")

    resolved, refusals = resolve_with_refusals(cell, ws)
    if resolved is None:
        return Envelope.refuse(refusals, warnings=warnings)

    try:
        scene = build_scene(resolved, ws.modules_dir)
    except SceneBuildError as e:
        return Envelope.refuse([scene_error_to_refusal(err) for err in e.errors], warnings=warnings)

    return Envelope.succeed(
        {
            "cell_id": cell_id,
            "instances": sorted(scene.instances),
            "base": scene.base.root_link,
            "workspace_bounds": _workspace_bounds_mm(scene),
        },
        warnings=warnings,
    )


def place_instance(ws: Workspace, cell_id: str, instance: str, module_ref: str, mount: dict[str, Any]) -> Envelope:
    def mutate(doc: dict[str, Any], warnings: list[str]) -> Refusal | None:
        modules = doc.setdefault("modules", [])
        if any(m.get("instance") == instance for m in modules):
            return Refusal(
                code=Codes.ALREADY_EXISTS,
                path=f"modules['{instance}']",
                message=f"instance {instance!r} is already placed in {cell_id!r} -- use move_instance to reposition it",
            )
        mount_on = mount.get("on") if isinstance(mount, dict) else None
        if mount_on is not None:
            incumbent = _find_tool_slot_incumbent(modules, mount_on)
            if incumbent is not None:
                return _tool_slot_refusal(instance, mount_on, incumbent)
        modules.append({"instance": instance, "module": module_ref, "mount": mount})
        return None

    return _mutate_and_resolve(ws, cell_id, mutate)


def move_instance(ws: Workspace, cell_id: str, instance: str, mount: dict[str, Any]) -> Envelope:
    def mutate(doc: dict[str, Any], warnings: list[str]) -> Refusal | None:
        modules = doc.get("modules", [])
        target = next((m for m in modules if m.get("instance") == instance), None)
        if target is None:
            return Refusal(code=Codes.NOT_FOUND, path=f"modules['{instance}']", message=f"no instance {instance!r} placed in {cell_id!r}")
        mount_on = mount.get("on") if isinstance(mount, dict) else None
        if mount_on is not None:
            incumbent = _find_tool_slot_incumbent(modules, mount_on, exclude_instance=instance)
            if incumbent is not None:
                return _tool_slot_refusal(instance, mount_on, incumbent)
        target["mount"] = mount
        return None

    return _mutate_and_resolve(ws, cell_id, mutate)


def remove_instance(ws: Workspace, cell_id: str, instance: str) -> Envelope:
    def mutate(doc: dict[str, Any], warnings: list[str]) -> Refusal | None:
        modules = doc.get("modules", [])
        kept = [m for m in modules if m.get("instance") != instance]
        if len(kept) == len(modules):
            return Refusal(code=Codes.NOT_FOUND, path=f"modules['{instance}']", message=f"no instance {instance!r} placed in {cell_id!r}")
        warnings.extend(_orphan_warnings(doc, instance))
        doc["modules"] = kept
        return None

    return _mutate_and_resolve(ws, cell_id, mutate)


def set_plan(ws: Workspace, cell_id: str, plan: list[Any], part: dict[str, Any] | None = None) -> Envelope:
    """`part` is optional and, if given, replaces `cell.yaml`'s own
    `part:` block (the physical part + its named features, e.g.
    `part.features.hole_1` -- what a `drive_screw` step's `at:` and a
    `binds:` result both resolve against). spec/09's verb table has no
    separate `set_part`; `part` and the plan that references it are too
    tightly coupled to write independently without a moment where the
    two disagree, so one document-granularity write covers both.
    """

    def mutate(doc: dict[str, Any], warnings: list[str]) -> Refusal | None:
        doc["plan"] = plan
        if part is not None:
            doc["part"] = part
        return None

    return _mutate_and_resolve(ws, cell_id, mutate)


def set_joint_state(ws: Workspace, cell_id: str, instance: str, joints: dict[str, float]) -> Envelope:
    def mutate(doc: dict[str, Any], warnings: list[str]) -> Refusal | None:
        for m in doc.get("modules", []):
            if m.get("instance") == instance:
                m["joint_state"] = joints
                return None
        return Refusal(code=Codes.NOT_FOUND, path=f"modules['{instance}']", message=f"no instance {instance!r} placed in {cell_id!r}")

    return _mutate_and_resolve(ws, cell_id, mutate)
