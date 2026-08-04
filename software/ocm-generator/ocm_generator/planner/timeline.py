# SPDX-License-Identifier: AGPL-3.0-or-later
"""ADR-0029 D1: the timeline is walked from `cell.plan`, top to bottom, in
the order the cell wrote it -- `for_each` expands in listed order, and each
op-step is dispatched by what its capability declares:

- the step carries `at:` (a part feature) -> MOTION rows, produced by the
  existing IK/path machinery (`plan_fastening_sequence` survives as the
  producer of motion rows for a fastening step; it stops being the entry
  point);
- the step's capability declares `actuates` (ADR-0028) -> an ACTUATION row;
- neither, but the capability declares `nominal_duration_s` -> a DWELL row;
- none of the above -> PlanStepUnplannableError (OCM_PLAN_STEP_UNPLANNABLE).

`load_screw` needs no placement logic once it stops being special (D4):
the cell lists it before `drive_screw` inside the `for_each` sequence, so
this in-order walk emits it as a dwell exactly where the manifest says it
happens, held at its predecessor's last frame.

## The walk is where checking happens (D5, D6)

`plan_fastening_sequence` produces UNCHECKED segments; this walk checks
each motion row via `check_joint_segment` against the state accumulated
so far -- so a transit planned after `clamp` is checked with the jaws
closed, and one planned before it with them open. Each actuation row is
checked via `check_actuation_segment` the same way (D6): every joint the
capability actuates sweeps linearly together, each sample collision-
checked with the robot at its accumulated pose, refusing with the same
PathCollisionError a robot segment uses -- an actuation row is a segment,
and it needs no code of its own. One place checks, and it is the place
that knows the state. A capability that declares `actuates` with no
`nominal_duration_s` refuses (ActuationDurationMissingError): the
endpoint is stated, the time is not, and it will not be invented.

What D6's check does not catch (stated in check_actuation_segment's own
docstring too): same-instance contact (two jaws of one nest closing on
each other) and the workpiece (`cell.part` is not in the collision
scene). It catches a module joint sweeping into a DIFFERENT instance.

## Sequencing lives here, nowhere else

`ocm_resolve.plan_walk.iter_op_steps` is deliberately order-blind (op and
param checking only) and stays that way -- sequencing needs module
manifests, IK, and a scene, none of which the resolver has. `on_fail` is
recovery, not the forward path, and is not walked.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

from ocm_core.units import (
    angle_to_rad,
    known_angle_units,
    known_length_units,
    length_to_mm,
)
from ocm_resolve import ResolvedCell

from ocm_generator.scene import Scene
from ocm_generator.scene.errors import CollisionCheckUnavailable

from .cycle_time import DEFAULT_JOINT_SPEED_RAD_S, CycleTimeReport, CycleTimeRow, joint_distance
from .errors import ActuationDurationMissingError, PlanningError, PlanningUnavailable, PlanStepUnplannableError
from .path import DEFAULT_PATH_SAMPLES, check_actuation_segment, check_joint_segment
from .plan import DEFAULT_COLLISION_MARGIN_MM, FasteningPlan, PathSegment


@dataclass(frozen=True)
class Timeline:
    """The ordered rows the in-order walk produced -- every row carrying
    its own already-checked frames -- plus the checked segments the motion
    rows correspond to (by `PathSegment.label`) and the FasteningPlan that
    produced them (`.emitters.urscript` still consumes it directly -- it
    is one row producer, no longer the plan). The trace (`.emitters.
    trace`, ADR-0029 D7) is this, serialised.
    """

    rows: tuple[CycleTimeRow, ...]
    segments: tuple[PathSegment, ...]
    plan: FasteningPlan
    total_s: float
    joint_speed_rad_s: float

    @property
    def report(self) -> CycleTimeReport:
        """The rows as the CycleTimeReport the emitters render."""
        return CycleTimeReport(rows=self.rows, total_s=self.total_s, joint_speed_rad_s=self.joint_speed_rad_s)


def _native_value(to: float, units: str) -> float:
    """An actuation target in URDF-native units (metres/radians) -- the
    unit's own table decides the conversion; type-vs-joint mismatch was
    already refused at module validation (ADR-0028 D2).
    """
    if units in known_length_units():
        return length_to_mm(to, units) / 1000.0
    if units in known_angle_units():
        return angle_to_rad(to, units)
    # Refused at resolve (OCM_UNIT_UNRECOGNISED) before any plan is built;
    # belt only.
    raise PlanningError(f"actuation unit {units!r} is in no known unit table")


def build_timeline(
    resolved: ResolvedCell,
    scene: Scene,
    plan: FasteningPlan,
    joint_speed_rad_s: float = DEFAULT_JOINT_SPEED_RAD_S,
    collision_margin_mm: float = DEFAULT_COLLISION_MARGIN_MM,
    path_samples: int = DEFAULT_PATH_SAMPLES,
) -> Timeline:
    """Walk `resolved.cell.plan` in order and place every step on one
    strictly serial timeline (ADR-0029 D1/D4), collision-checking each
    motion and actuation row against the state in effect at that point
    (D5/D6). `plan` is `plan_fastening_sequence`'s own output for this
    cell -- the motion-row producer's segments, IK-solved and UNCHECKED;
    this walk is what checks them.

    Raises PlanStepUnplannableError for a step with nothing to place,
    ActuationDurationMissingError for a stated endpoint with no stated
    time, PathCollisionError (naming the row and the colliding pair) for
    a motion or actuation sweep that collides, PlanningUnavailable if the
    collision backend (the `tesseract` extra) is missing, and
    PlanningError if a step carries `at:` outside the fastening for_each
    (v0's only motion machinery).
    """
    robot_prefix = f"{plan.robot_instance}__"
    # D3: the non-robot joint state, threaded through the walk. Starts at
    # the cell's own authored joint_state (already limit-checked at scene
    # build -- ADR-0028 Erratum 1) and accumulates each actuation row's
    # targets as the plan leaves them.
    module_state: dict[str, float] = {k: v for k, v in scene.joint_state.items() if not k.startswith(robot_prefix)}
    # The FULL namespaced state in effect -- module joints as the plan has
    # left them AND the robot wherever the last motion row put it. Every
    # check below runs against this, and every row's frames end in it.
    current_state: dict[str, float] = dict(scene.joint_state)

    segments_for_hole: dict[str | None, dict[str, PathSegment]] = {}
    for segment in plan.segments:
        segments_for_hole.setdefault(segment.hole_id, {})[segment.kind] = segment

    rows: list[CycleTimeRow] = []
    checked_by_label: dict[str, PathSegment] = {}
    last_row_label: str | None = None

    def scene_in_effect() -> Scene:
        return dataclasses.replace(scene, joint_state=dict(current_state))

    def emit_motion(segment: PathSegment) -> None:
        nonlocal current_state, last_row_label
        # D5: checked against the module state in effect at THIS point in
        # the plan -- jaws closed after clamp, open after unclamp.
        frames = check_joint_segment(
            scene=scene_in_effect(),
            robot_instance=plan.robot_instance,
            label=segment.label,
            start_joints=segment.start_joints,
            end_joints=segment.end_joints,
            samples=path_samples,
            collision_margin_mm=collision_margin_mm,
        )
        duration = joint_distance(segment.start_joints, segment.end_joints) / joint_speed_rad_s
        rows.append(
            CycleTimeRow(
                label=segment.label,
                duration_s=duration,
                source="ESTIMATE",
                kind="motion",
                module_state=dict(module_state),
                frames=frames,
            )
        )
        checked_by_label[segment.label] = dataclasses.replace(segment, frames=frames)
        current_state = dict(frames[-1])
        last_row_label = segment.label

    def emit_actuation(label: str, duration_s: float, targets: dict[str, float]) -> None:
        nonlocal current_state, last_row_label
        # D6: one verb, one sweep -- every actuated joint interpolates
        # together, each sample checked with the robot at its accumulated
        # pose. The row snapshots module_state at its START; the targets
        # land after it, in effect for every subsequent row.
        start = {key: current_state.get(key, 0.0) for key in targets}
        frames = check_actuation_segment(
            scene=scene_in_effect(),
            label=label,
            start=start,
            end=targets,
            samples=path_samples,
            collision_margin_mm=collision_margin_mm,
        )
        rows.append(
            CycleTimeRow(
                label=label,
                duration_s=duration_s,
                source="nominal_duration_s",
                kind="actuation",
                module_state=dict(module_state),
                frames=frames,
            )
        )
        current_state = dict(frames[-1])
        module_state.update(targets)
        last_row_label = label

    def emit_dwell(label: str, duration_s: float) -> None:
        nonlocal last_row_label
        # A dwell holds its predecessor's final frame -- whatever kind the
        # predecessor was, so a dwell after `clamp` shows the jaws CLOSED,
        # never a frame captured before they moved. With no predecessor it
        # holds the scene's own initial authored state.
        rows.append(
            CycleTimeRow(
                label=label,
                duration_s=duration_s,
                source="nominal_duration_s",
                kind="dwell",
                held_at=last_row_label,
                module_state=dict(module_state),
                frames=(dict(current_state),),
            )
        )
        last_row_label = label

    def handle_fastening_step(item: str) -> None:
        """One drive_screw step of the fastening for_each: the motion rows
        the existing machinery planned for this hole, with the drive dwell
        at contact -- transit, approach, dwell, withdraw.
        """
        by_kind = segments_for_hole.get(item, {})
        if set(by_kind) != {"transit", "approach", "withdraw"}:
            raise PlanningError(
                f"fastening plan has no complete transit/approach/withdraw segment set for {item!r}"
            )  # pragma: no cover -- plan and cell.plan come from the same cell
        emit_motion(by_kind["transit"])
        emit_motion(by_kind["approach"])
        if plan.drive_screw_nominal_duration_s is not None:
            emit_dwell(f"drive_screw @ {item}", plan.drive_screw_nominal_duration_s)
        emit_motion(by_kind["withdraw"])

    def handle_step(step: dict[str, Any], item: str | None, is_fastening_item: bool) -> None:
        instance = step["module"]
        op = step["op"]
        if is_fastening_item and op == "drive_screw":
            handle_fastening_step(str(item))
            return
        if "at" in step:
            # The only motion machinery v0 has is the fastening sequence's
            # own; an at: step anywhere else has nowhere to get motion
            # rows from yet.
            raise PlanningError(
                f"step {step.get('step', op)!r} carries at={step['at']!r}, but v0's motion "
                "machinery plans only the fastening for_each's drive_screw"
            )

        capability = resolved.instance(instance).module.capability(op)
        label = f"{op} @ {item}" if item is not None else f"{instance}.{op}"

        if capability.actuates:
            if capability.nominal_duration_s is None:
                raise ActuationDurationMissingError(instance, resolved.instance(instance).module.id, capability.name)
            targets = {f"{instance}__{act.joint}": _native_value(act.to, act.units) for act in capability.actuates}
            emit_actuation(label, capability.nominal_duration_s, targets)
            return

        if capability.nominal_duration_s is not None:
            emit_dwell(label, capability.nominal_duration_s)
            return

        raise PlanStepUnplannableError(str(step.get("step", op)), instance, op)

    fastening_block_seen = False

    def walk(entries: list[Any]) -> None:
        nonlocal fastening_block_seen
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            for_each = entry.get("for_each")
            sequence = entry.get("sequence")
            if isinstance(for_each, list) and isinstance(sequence, list):
                # The FIRST for_each whose sequence contains a drive_screw
                # is the fastening block -- the same identification
                # `find_fastening_plan` used to build `plan`.
                is_fastening = not fastening_block_seen and any(
                    isinstance(s, dict) and s.get("op") == "drive_screw" for s in sequence
                )
                if is_fastening:
                    fastening_block_seen = True
                for raw_item in for_each:
                    item = str(raw_item)
                    for step in sequence:
                        if isinstance(step, dict) and "module" in step and "op" in step:
                            handle_step(step, item=item, is_fastening_item=is_fastening)
                if is_fastening:
                    # The final return home belongs to the fastening
                    # sequence and follows its last hole.
                    final = segments_for_hole.get(None, {}).get("transit")
                    if final is not None:
                        emit_motion(final)
                continue
            if isinstance(sequence, list):
                walk(sequence)
                continue
            if "module" in entry and "op" in entry:
                handle_step(entry, item=None, is_fastening_item=False)

    try:
        walk(resolved.cell.plan)
    except CollisionCheckUnavailable as e:
        # The walk IS the check pass now (D5/D6); surface a missing
        # backend as the same refusal shape the IK path uses.
        raise PlanningUnavailable(str(e)) from e

    return Timeline(
        rows=tuple(rows),
        segments=tuple(checked_by_label[s.label] for s in plan.segments),
        plan=plan,
        total_s=sum(row.duration_s for row in rows),
        joint_speed_rad_s=joint_speed_rad_s,
    )
