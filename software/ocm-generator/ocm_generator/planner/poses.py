# SPDX-License-Identifier: AGPL-3.0-or-later
"""Find the first forward drive_screw step in a cell's plan, and compute
the flange-frame standoff/contact/retract poses it needs from the part
feature it targets and the capability's own motion block.

## v0 scope: where the part actually is

`locate_part`'s real vision result isn't modeled -- this isn't a live
simulator any more than .scene.kinematics is (see that module's own
docstring). Instead, the part is assumed seated exactly at the DECLARED
part datum (ADR-0031 D4): the cell's carrier instance's `part_datum`
frame, or the one placed fixture module that declares one -- "where a
correctly seated part's own origin lands... what cam1's locate_part
corrects against" (see com.accelsolutions.fixture.pneumatic-nest's own
manifest note). Using it directly isn't a simulation of the vision
system; it's the exact nominal placement that system exists to verify.

## Frame math

Every `cell.part.features.*` entry is `xyz_mm`/`normal`, both expressed in
the fixture's own `part_datum` frame. The capability's `motion` block
(`frame: tcp`) expresses `approach_vec`/`retract_vec` in the *tool's own*
TCP frame -- which, for sd50, shares its rotation exactly with the flange
(its `tcp` frame's `rpy_deg` is the schema default, identity), so a single
rotation serves both: point the tool's local +Z (sd50's own note: "+Z
points away from flange, i.e. INTO the screw") anti-parallel to the
feature's outward normal, then walk that rotation's own local axes by
`approach_mm`/`retract_mm` to get standoff/retract from contact. The
result is computed directly in the FLANGE frame (not TCP), since a fixed,
known, purely-translational offset (sd50's own `tcp` frame) is all that
separates the two, and the flange pose is what IK actually needs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from ocm_core import Module
from ocm_core.cell import Cell
from ocm_resolve import ResolvedCell

from ocm_generator.scene import Pose, Scene
from ocm_generator.scene.transforms import Vec3

from .errors import NoDriveScrewStepError, PlanningError


@dataclass(frozen=True)
class DriveScrewStep:
    """One for_each item's drive_screw step, with that item substituted
    into `at`.
    """

    tool_instance: str  # e.g. "sd1"
    hole_id: str  # e.g. "hole_1" -- the for_each item bound at this step
    at_path: str  # e.g. "part.features.hole_1"
    params: dict[str, Any]


@dataclass(frozen=True)
class ToolPoses:
    """Flange-frame (world) poses for one drive_screw step's motion."""

    standoff: Pose
    contact: Pose
    retract: Pose
    approach_speed_m_s: float


@dataclass(frozen=True)
class FastenPlan:
    """The plan's fastening for_each block, expanded to one DriveScrewStep
    per item, in listed order -- v0 doesn't reorder or optimize visiting
    order, "no path optimization -- v0 is honest."
    """

    steps: tuple[DriveScrewStep, ...]
    load_screw_module: str | None  # the module a load_screw op targets, if the sequence has one before drive_screw
    on_fail_summary: str | None  # e.g. "eject_screw, reject_part" -- PLC-side, not emitted as URScript


def standoff_step_number(hole_index: int) -> int:
    """spec/08's monotonic handshake step number for hole `hole_index`'s
    (1-based) standoff sync point -- the gate `.emitters.urscript` and
    `.coordinator` must agree on byte-for-byte, so both call this (and
    `contact_step_number`) instead of each computing `2 * i - 1` locally.
    """
    return 2 * hole_index - 1


def contact_step_number(hole_index: int) -> int:
    """spec/08's monotonic handshake step number for hole `hole_index`'s
    (1-based) contact sync point. See `standoff_step_number`.
    """
    return 2 * hole_index


def _substitute_item(value: Any, item: str | None) -> Any:
    if isinstance(value, str) and item is not None:
        return value.replace("${item}", item)
    return value


def _describe_on_fail(on_fail: Any) -> str | None:
    if not isinstance(on_fail, list) or not on_fail:
        return None
    parts = []
    for entry in on_fail:
        if not isinstance(entry, dict):
            continue
        if "op" in entry:
            parts.append(str(entry["op"]))
        elif "action" in entry:
            parts.append(str(entry["action"]))
    return ", ".join(parts) if parts else None


def _find_fasten_block(plan: list[Any]) -> tuple[list[Any], list[Any]] | None:
    """Depth-first search of `plan`'s forward path (`sequence`, never
    `on_fail` -- that's recovery, not the forward path this plans motion
    for) for the first `for_each` block whose `sequence` contains a
    drive_screw op. Returns (for_each items, sequence), unresolved --
    `${item}` substitution happens once per item, not here.
    """
    for entry in plan:
        if not isinstance(entry, dict):
            continue

        for_each = entry.get("for_each")
        sequence = entry.get("sequence")
        if isinstance(for_each, list) and isinstance(sequence, list):
            if any(isinstance(s, dict) and s.get("op") == "drive_screw" for s in sequence):
                return for_each, sequence
            continue

        if isinstance(sequence, list):
            found = _find_fasten_block(sequence)
            if found is not None:
                return found

    return None


def _resolve_sequence_for_item(sequence: list[Any], item: str) -> tuple[DriveScrewStep, str | None, str | None]:
    """(this item's DriveScrewStep, the load_screw op's module if one
    directly precedes drive_screw in the sequence, drive_screw's own
    on_fail summary).
    """
    load_screw_module: str | None = None
    for entry in sequence:
        if not isinstance(entry, dict):
            continue
        if entry.get("op") == "load_screw" and "module" in entry:
            load_screw_module = entry["module"]
            continue
        if entry.get("op") == "drive_screw" and "module" in entry:
            at_path = _substitute_item(entry.get("at", ""), item)
            step = DriveScrewStep(
                tool_instance=entry["module"],
                hole_id=item,
                at_path=at_path,
                params=dict(entry.get("params", {})),
            )
            return step, load_screw_module, _describe_on_fail(entry.get("on_fail"))

    raise PlanningError("fasten sequence lost its drive_screw op")  # pragma: no cover -- _find_fasten_block already checked


def find_fastening_plan(cell: Cell) -> FastenPlan:
    """Raises NoDriveScrewStepError if the plan has no forward fastening
    for_each (an on_fail recovery step doesn't count).
    """
    found = _find_fasten_block(cell.plan)
    if found is None:
        raise NoDriveScrewStepError(f"cell {cell.id!r}'s plan has no (non on_fail) drive_screw step")

    for_each_items, sequence = found
    if not for_each_items:
        raise NoDriveScrewStepError(f"cell {cell.id!r}'s fasten step has an empty for_each list")

    steps: list[DriveScrewStep] = []
    load_screw_module: str | None = None
    on_fail_summary: str | None = None
    for item in for_each_items:
        step, load_screw_module, on_fail_summary = _resolve_sequence_for_item(sequence, str(item))
        steps.append(step)

    return FastenPlan(steps=tuple(steps), load_screw_module=load_screw_module, on_fail_summary=on_fail_summary)


def compute_part_datum_world(resolved: ResolvedCell, scene: Scene, world_poses: dict[str, Pose]) -> tuple[str, Pose]:
    """(owner_instance_name, world pose of its part_datum frame).

    ADR-0031 D4: the part datum is DECLARED, never scraped from a `clamp`
    verb -- the old `_find_clamp_fixture` heuristic is deleted, not kept as
    a fallback, because a heuristic and a declaration are two answers to
    one question and the heuristic is wrong in every cell but the first
    (in a line, the part arrives already clamped and no downstream cell
    has a clamp step).

    Owner precedence: the cell's carrier instance (its TYPE's
    frames.part_datum, composed through the carrier's root link -- which
    the D2 chain places at the located datum when both transit joints sit
    at zero); otherwise the one placed module whose manifest declares
    frames.part_datum. Nothing declaring one refused at resolve
    (OCM_PART_DATUM_UNDECLARED); more than one fixture declaring it with
    no carrier is ambiguous and refuses here rather than guessing.
    """
    rc = resolved.carrier
    if rc is not None:
        part_datum = rc.carrier.mechanical.frames.get("part_datum")
        if part_datum is None:
            # Resolve only passes a carrier without part_datum when a
            # fixture declares one instead -- fall through to the fixtures.
            pass
        else:
            root_link = scene.instance(rc.name).root_link
            if root_link not in world_poses:
                raise PlanningError(f"scene has no world pose for carrier {rc.name}'s root link {root_link!r}")
            local = Pose.from_xyz_rpy(_mm(part_datum.xyz_mm), _deg_to_rad(part_datum.rpy_deg))
            return rc.name, world_poses[root_link].compose(local)

    candidates = sorted(
        name for name, ri in resolved.instances.items() if "part_datum" in ri.module.mechanical.frames
    )
    if not candidates:
        raise PlanningError(
            "no carrier or fixture declares frames.part_datum -- the part's location is a stated "
            "fact, not a guess (ADR-0031 D4; resolve refuses this earlier as OCM_PART_DATUM_UNDECLARED)"
        )
    if len(candidates) > 1:
        raise PlanningError(
            f"multiple fixtures declare frames.part_datum ({candidates}) and the cell places no "
            "carrier -- ambiguous, and it will not be guessed (ADR-0031 D4)"
        )

    fixture_name = candidates[0]
    fixture_ri = resolved.instances[fixture_name]
    part_datum = fixture_ri.module.mechanical.frames["part_datum"]

    fixture_root_link = scene.instance(fixture_name).root_link
    if fixture_root_link not in world_poses:
        raise PlanningError(f"scene has no world pose for {fixture_name}'s root link {fixture_root_link!r}")

    fixture_origin_world = world_poses[fixture_root_link]
    part_datum_local = Pose.from_xyz_rpy(_mm(part_datum.xyz_mm), _deg_to_rad(part_datum.rpy_deg))
    return fixture_name, fixture_origin_world.compose(part_datum_local)


def _resolve_at(part: dict[str, Any] | None, at_path: str) -> dict[str, Any]:
    if part is None:
        raise PlanningError(f"at={at_path!r} references cell.part, but this cell has no part: block")
    segments = at_path.split(".")
    if not segments or segments[0] != "part":
        raise PlanningError(f"at={at_path!r}: expected a 'part.<...>' path")

    node: Any = part
    walked = "part"
    for segment in segments[1:]:
        if not isinstance(node, dict) or segment not in node:
            raise PlanningError(f"at={at_path!r}: {walked!r} has no {segment!r}")
        node = node[segment]
        walked = f"{walked}.{segment}"

    if not isinstance(node, dict) or "xyz_mm" not in node:
        raise PlanningError(f"at={at_path!r}: does not resolve to a feature with 'xyz_mm'")
    return node


def _mm(xyz_mm: Vec3) -> Vec3:
    return (xyz_mm[0] / 1000.0, xyz_mm[1] / 1000.0, xyz_mm[2] / 1000.0)


def _deg_to_rad(rpy_deg: Vec3) -> Vec3:
    return (math.radians(rpy_deg[0]), math.radians(rpy_deg[1]), math.radians(rpy_deg[2]))


def _add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _scale(v: Vec3, s: float) -> Vec3:
    return (v[0] * s, v[1] * s, v[2] * s)


def _negate(v: Vec3) -> Vec3:
    return (-v[0], -v[1], -v[2])


def compute_flange_poses(
    step: DriveScrewStep,
    cell_part: dict[str, Any] | None,
    part_datum_world: Pose,
    tool_module: Module,
) -> ToolPoses:
    """Standoff/contact/retract poses for the tool's FLANGE, in world frame.

    Raises PlanningError if the target feature can't be resolved, or the
    tool module doesn't declare the frames/motion this needs (a `tcp`
    frame, and drive_screw's own `motion` block with approach_vec/
    approach_mm/approach_speed_mm_s).
    """
    feature = _resolve_at(cell_part, step.at_path)
    feature_local_xyz = _mm(tuple(feature["xyz_mm"]))
    feature_local_normal: Vec3 = tuple(feature.get("normal", (0.0, 0.0, 1.0)))

    feature_world_position = part_datum_world.transform_point(feature_local_xyz)
    feature_world_normal = part_datum_world.rotate_vector(feature_local_normal)

    capability = tool_module.capability("drive_screw")
    motion = capability.motion
    if motion is None or motion.approach_vec is None or motion.approach_mm is None:
        raise PlanningError(f"{tool_module.id}'s drive_screw capability declares no usable motion block")
    if motion.approach_speed_mm_s is None:
        raise PlanningError(f"{tool_module.id}'s drive_screw motion declares no approach_speed_mm_s")

    tcp_frame = tool_module.mechanical.tcp
    if tcp_frame is None:
        raise PlanningError(f"{tool_module.id} declares no mechanical.frames.tcp")
    tcp_offset_local = _mm(tuple(tcp_frame.xyz_mm))

    # The tool's local +Z is the bit's own drive axis ("+Z points away from
    # flange, i.e. INTO the screw" -- sd50's own frame note): point it
    # anti-parallel to the feature's outward normal so the bit drives IN.
    contact_rotation = Pose.from_z_axis((0.0, 0.0, 0.0), _negate(feature_world_normal))
    tcp_offset_world = contact_rotation.rotate_vector(tcp_offset_local)
    contact_flange_position = _sub(feature_world_position, tcp_offset_world)
    contact_flange = Pose(contact_flange_position, contact_rotation.rotation)

    approach_dir_world = contact_flange.rotate_vector(motion.approach_vec)
    standoff_flange = Pose(
        _sub(contact_flange_position, _scale(approach_dir_world, motion.approach_mm / 1000.0)),
        contact_flange.rotation,
    )

    retract_vec = motion.retract_vec or _negate(motion.approach_vec)
    retract_mm = motion.retract_mm or motion.approach_mm
    retract_dir_world = contact_flange.rotate_vector(retract_vec)
    retract_flange = Pose(
        _add(contact_flange_position, _scale(retract_dir_world, retract_mm / 1000.0)),
        contact_flange.rotation,
    )

    return ToolPoses(
        standoff=standoff_flange,
        contact=contact_flange,
        retract=retract_flange,
        approach_speed_m_s=motion.approach_speed_mm_s / 1000.0,
    )
