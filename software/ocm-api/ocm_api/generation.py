# SPDX-License-Identifier: AGPL-3.0-or-later
"""Checking & generation verbs (spec/09): "wrapping what exists." Every
one of these is a thin translation over `ocm_generator`'s own scene/
planner/emitters -- `check_collision`/`plan_cell` need the `tesseract`
extra (same as the underlying `ocm scene --collision`/`ocm plan`); a
missing extra becomes an `UNAVAILABLE` refusal, not an exception the
caller has to catch.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from ocm_core.cell import Cell
from ocm_generator.emitters import emit_urscript, render_html_animation
from ocm_generator.planner import (
    NoDriveScrewStepError,
    PathCollisionError,
    PlanningError,
    PlanningUnavailable,
    PoseUnreachableError,
    estimate_cycle_time,
    plan_fastening_sequence,
)
from ocm_generator.scene import (
    CollisionCheckError,
    CollisionCheckUnavailable,
    SceneBuildError,
    build_scene,
    check_collisions,
    render_html,
    scene_to_payload,
)

from .envelope import Codes, Envelope, Refusal, single_refusal
from .resolution import resolve_with_refusals
from .translate import contacts_to_refusals, path_collision_to_refusal, pose_unreachable_to_refusal, scene_error_to_refusal
from .workspace import Workspace, read_yaml


def _resolve_and_build(ws: Workspace, cell_id: str) -> tuple[Any, Any, list[Refusal]]:
    """(resolved, scene, refusals). `resolved`/`scene` are None if
    `refusals` is non-empty.
    """
    if not ws.cell_exists(cell_id):
        return None, None, [Refusal(code=Codes.NOT_FOUND, path=f"cells['{cell_id}']", message=f"no cell {cell_id!r} in this workspace")]

    doc = read_yaml(ws.cell_path(cell_id)) or {}
    try:
        cell = Cell.from_dict(doc)
    except (KeyError, ValueError) as e:
        return None, None, [Refusal(code=Codes.CELL_INVALID, path="$", message=f"cell document is structurally incomplete: {e}")]

    resolved, refusals = resolve_with_refusals(cell, ws)
    if resolved is None:
        return None, None, refusals

    try:
        scene = build_scene(resolved, ws.modules_dir)
    except SceneBuildError as e:
        return None, None, [scene_error_to_refusal(err) for err in e.errors]

    return resolved, scene, []


def build_scene_verb(ws: Workspace, cell_id: str) -> Envelope:
    resolved, scene, refusals = _resolve_and_build(ws, cell_id)
    if scene is None:
        return Envelope.refuse(refusals)

    root = ET.fromstring(scene.urdf_xml)
    # scene_to_payload is the SAME function the debug HTML viewer's own
    # embedded JSON comes from (ocm_generator.scene.viewer) -- one
    # primitive per collision box/cylinder/sphere, a color per instance,
    # attachment/TCP markers. Reused as-is (not re-derived here) so the
    # composer's 3D view and the standalone --view debug viewer can never
    # draw two different pictures of the same cell.
    payload = scene_to_payload(scene, resolved)
    return Envelope.succeed(
        {
            "cell_id": cell_id,
            "n_links": len(root.findall("link")),
            "n_joints": len(root.findall("joint")),
            "base": scene.base.root_link,
            "instances": sorted(scene.instances),
            "colors": payload["colors"],
            "primitives": payload["primitives"],
            "markers": payload["markers"],
        }
    )


def check_collision(ws: Workspace, cell_id: str, collision_margin_mm: float = 1.0) -> Envelope:
    resolved, scene, refusals = _resolve_and_build(ws, cell_id)
    if scene is None:
        return Envelope.refuse(refusals)

    try:
        result = check_collisions(scene, contact_distance_mm=collision_margin_mm)
    except CollisionCheckUnavailable as e:
        return single_refusal(Codes.UNAVAILABLE, path="$", message=str(e))
    except CollisionCheckError as e:
        return single_refusal(Codes.CELL_INVALID, path="$", message=str(e))

    contacts = [
        {
            "instance_a": c.instance_a,
            "instance_b": c.instance_b,
            "link_a": c.link_a,
            "link_b": c.link_b,
            "distance_mm": c.distance_mm,
            "is_violation": c.is_violation,
        }
        for c in result.contacts
    ]
    violation_refusals = contacts_to_refusals(contacts)
    if violation_refusals:
        return Envelope.refuse(violation_refusals)
    return Envelope.succeed({"cell_id": cell_id, "margin_mm": result.margin_mm, "contacts": contacts})


def plan_cell(ws: Workspace, cell_id: str, collision_margin_mm: float = 1.0, path_samples: int = 50) -> Envelope:
    resolved, scene, refusals = _resolve_and_build(ws, cell_id)
    if scene is None:
        return Envelope.refuse(refusals)

    try:
        plan = plan_fastening_sequence(resolved, scene, collision_margin_mm=collision_margin_mm, path_samples=path_samples)
    except NoDriveScrewStepError as e:
        return single_refusal(Codes.NO_FASTENING_STEP, path="plan", message=str(e), hint="Add a for_each fastening step with a drive_screw op to the plan.")
    except PoseUnreachableError as e:
        return Envelope.refuse([pose_unreachable_to_refusal(e.pose_name, str(e))])
    except PathCollisionError as e:
        return Envelope.refuse([path_collision_to_refusal(e.segment, e.instance_a, e.instance_b, e.link_a, e.link_b, e.fraction, str(e))])
    except PlanningUnavailable as e:
        return single_refusal(Codes.UNAVAILABLE, path="$", message=str(e))
    except PlanningError as e:
        return single_refusal(Codes.CELL_INVALID, path="plan", message=str(e))

    report = estimate_cycle_time(plan)
    cycle_table = [
        {
            "label": row.label,
            "duration_s": row.duration_s,
            "source": row.source,
            "overlapped_with": row.overlapped_with,
            "held_at_segment": row.held_at_segment,
        }
        for row in report.rows
    ]
    return Envelope.succeed(
        {
            "cell_id": cell_id,
            "tool_instance": plan.tool_instance,
            "robot_instance": plan.robot_instance,
            "holes": [h.hole_id for h in plan.holes],
            "cycle_table": cycle_table,
            "naive_serial_total_s": report.naive_serial_total_s,
            "overlapped_total_s": report.overlapped_total_s,
            "savings_s": report.savings_s,
        }
    )


def emit(
    ws: Workspace,
    cell_id: str,
    urscript: str | None = None,
    animation: str | None = None,
    view: str | None = None,
    collision_margin_mm: float = 1.0,
    path_samples: int = 50,
) -> Envelope:
    resolved, scene, refusals = _resolve_and_build(ws, cell_id)
    if scene is None:
        return Envelope.refuse(refusals)

    written: dict[str, str] = {}

    if view is not None:
        Path(view).write_text(render_html(scene, resolved), encoding="utf-8")
        written["view"] = str(view)

    if urscript is not None or animation is not None:
        try:
            plan = plan_fastening_sequence(resolved, scene, collision_margin_mm=collision_margin_mm, path_samples=path_samples)
        except NoDriveScrewStepError as e:
            return single_refusal(Codes.NO_FASTENING_STEP, path="plan", message=str(e))
        except PoseUnreachableError as e:
            return Envelope.refuse([pose_unreachable_to_refusal(e.pose_name, str(e))])
        except PathCollisionError as e:
            return Envelope.refuse([path_collision_to_refusal(e.segment, e.instance_a, e.instance_b, e.link_a, e.link_b, e.fraction, str(e))])
        except PlanningUnavailable as e:
            return single_refusal(Codes.UNAVAILABLE, path="$", message=str(e))
        except PlanningError as e:
            return single_refusal(Codes.CELL_INVALID, path="plan", message=str(e))

        if urscript is not None:
            Path(urscript).write_text(emit_urscript(plan), encoding="utf-8")
            written["urscript"] = str(urscript)
        if animation is not None:
            report = estimate_cycle_time(plan)
            Path(animation).write_text(render_html_animation(scene, resolved, plan, report), encoding="utf-8")
            written["animation"] = str(animation)

    return Envelope.succeed({"cell_id": cell_id, "written": written})
