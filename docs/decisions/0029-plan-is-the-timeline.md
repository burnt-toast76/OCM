# ADR-0029 — The plan is the timeline

**Status:** Accepted. Consumes ADR-0028 (a capability declares the joints it actuates).
Generalises the fastening-shaped planner ADR-0007 built. Prerequisite for
ADR-0030 (`ocm-viewer`, not yet written).

**Phase.** D1–D7 are all implemented. Phase 1 delivered D1–D4 (`planner/timeline.py` walks
`cell.plan` in order; frames are namespaced joint-state dicts; rows are typed; the timeline is
strictly serial and the `load_screw` overlap is gone). Phase 2 delivered D5–D7: the collision
check pass moved out of `plan_fastening_sequence` and into the timeline walk, so every motion
row is checked against the module state in effect at that point; actuation rows carry a full
collision-checked sweep (`check_actuation_segment`), and a dwell holds its immediate
predecessor's final frame, never a stale one; `ocm plan --emit-trace` writes the timeline as a
JSON trace and `--view-animation` is a renderer over that same trace, with the dynamic set
derived from which joints actually vary in the frames rather than from mount topology.

## Context

ADR-0023 says plans are verbs. The planner never caught up.

`plan_fastening_sequence` returns a `FasteningPlan`: a tool instance, a robot instance, a tuple
of `HolePose`, and a tuple of `PathSegment`. It is built by `find_fastening_plan`, which
searches `cell.plan` for the one `for_each` block containing a `drive_screw` and raises
`NoDriveScrewStepError` if there isn't one. A second scraper, `_find_clamp_fixture`, walks the
plan looking for a `clamp` step — **not to sequence it**, only to learn which fixture the part
is seated in, so `part_datum` can be located.

So the cell's own stated order — clamp, then fasten each hole, then release — is read twice for
two facts and never walked. `nest1.clamp` resolves, validates, appears in the guardrail tests,
and produces no motion, no row, and no frame. `ocm_resolve.plan_walk.iter_op_steps` declines
sequencing explicitly, on the grounds that it "stays the planner's job." The planner declined
too, and nothing noticed because until ADR-0028 no non-robot module could move.

Three structural facts follow from that history and shape this decision:

**Frames are robot-shaped.** `PathSegment.frames` is `tuple[tuple[float, ...], ...]` in
`UR_JOINT_ORDER`. `_frame_transforms(root, base_joint_state, robot_instance, joints, ...)` takes
one robot's tuple. A jaw has nowhere to go in that signature.

**The scene's non-robot joints are frozen.** `check_joint_segment` builds each sample as
`dict(scene.joint_state)` updated with the robot's interpolated joints. `scene.joint_state`
comes from `cell.yaml` once. Every collision check the planner has ever run assumed every
fixture sits in its authored pose for the whole cycle. That was true when nothing else moved.
It is false the moment a jaw does — and the case it hides is the interesting one: a transit
that is clear with the jaws open and fouls with them closed.

**One invariant is load-bearing.** `emitters/animation.py` never interpolates a path of its own.
Every frame it draws is a state `check_joint_segment` already sampled and proved collision-free.
An animation whose frames are partly checked and partly not, with no way to tell which, is a
render that looks equally authoritative in both halves. That is the failure this project exists
to refuse, so it gets its own decision (D6) rather than a footnote.

## Decision 1 — The timeline is walked from `cell.plan`, in order

A new `planner/timeline.py` walks `cell.plan` top to bottom, expands `for_each` in listed
order, and dispatches each op-step by what its capability declares:

- the step carries `at:` (a part feature) → **motion rows**, produced by the existing
  IK-and-path machinery, unchanged
- the step's capability declares `actuates` (ADR-0028) → an **actuation row**
- neither, but the capability declares `nominal_duration_s` → a **dwell row**

`find_fastening_plan` and `plan_fastening_sequence` survive as the producer of motion rows for
a fastening step. They stop being the entry point. `_find_clamp_fixture` stays as-is: locating
the part datum is a different question from sequencing, and conflating them is what produced
this ADR.

**Rejected: teach `iter_op_steps` to sequence.** It is the resolver's, it is deliberately
order-blind, and three consumers depend on that. Sequencing needs module manifests, IK, and a
scene; the resolver has none of them.

## Decision 2 — A frame is a namespaced joint-state dict

`dict[str, float]`, keyed `instance__joint`, exactly the shape `Scene.joint_state` and
`compute_world_poses` already speak. A robot frame and a jaw frame stop being different kinds
of thing, and `_frame_transforms` stops taking a `robot_instance`.

IK and Tesseract keep speaking `UR_JOINT_ORDER` tuples internally. Conversion happens at the
boundary, in one place.

**Rejected: keep tuples and carry a parallel module-state map.** Two representations of "where
everything is at instant t," and every consumer would have to remember to consult both.

## Decision 3 — Rows are typed, and the type says what produced the frames

`CycleTimeRow` already carries `source` (`"ESTIMATE"` | `"nominal_duration_s"` |
`"overlapped"`) and `held_at_segment`. It gains a `kind` (`motion` | `actuation` | `dwell`),
its frames become D2 dicts, and `"overlapped"` is removed with the concurrency it described
(D4).

The distinction `source` already draws — a duration that was estimated from joint distance
versus one a manifest declared — is preserved unchanged, and remains the reason a viewer can
caption a segment with the number the printed cycle-time table shows rather than a
separately-computed one.

## Decision 4 — Strictly serial. The overlap special case is removed

The timeline is a total order. No parallel construct, no resource model, no concurrency.

`estimate_cycle_time` currently hides `load_screw`'s duration inside the transit it overlaps,
via `CycleTimeRow.source == "overlapped"` and `overlapped_with`. That is concurrency, hardcoded
for one verb, and it goes. `source` loses `"overlapped"`, `CycleTimeRow` loses
`overlapped_with`, and `CycleTimeReport`'s `naive_serial_total_s` / `overlapped_total_s` /
`savings_s` collapse to a single `total_s`.

The reported cycle time gets longer. That is the correct direction: a model that reports a
cycle longer than the real machine never oversells it, and ADR-0027's asymmetry argument
applies unchanged — conservative is an engineer investigating, optimistic is a customer quoted
a number the machine cannot hit.

`load_screw` does not need special placement once it stops being special. The cell's own plan
lists it before `drive_screw` inside the `for_each` sequence, so D1's in-order walk emits it as
a dwell exactly where the manifest says it happens, held at the previous segment's last frame
by the existing `held_at_segment` mechanism. A behaviour that required a hardcoded exception
becomes a consequence of reading the plan in the order it was written.

**Rejected: grandfather the existing overlap.** It is a true statement about the machine and it
is tested, so keeping it was defensible. But one hardcoded concurrency case inside a model
documented as serial is a discrepancy every future reader has to rediscover, and the first
person to want a second one will add a second special case rather than write the concurrency
ADR. Removing it makes the model's claim about itself true.

## Decision 5 — A robot segment is checked against the module state in effect at that point

`check_joint_segment` already builds each sample as `dict(scene.joint_state)` with the robot's
joints overlaid. The timeline threads an accumulating joint state through the walk, and each
motion row is checked against a `dataclasses.replace(scene, joint_state=...)` carrying the
module joints as the plan has left them — jaws closed after `clamp`, open after `unclamp`.

This is the substance of the ADR. It is a small change and it is the first time the planner
collides against the machine's *state* rather than its *layout*, which is the time-dimension
counterpart of what ADR-0027 fixed in space.

Initial state is `cell.yaml`'s own `joint_state`, or the joint's zero where unspecified —
unchanged from today, and already limit-checked (ADR-0028 Erratum 1).

## Decision 6 — Actuation rows are collision-checked, like every other row

An actuation row's frames are linear interpolation from each actuated joint's previous value to
its `actuates` target, at constant timestep over `nominal_duration_s`. Every capability's joints
move together across the same sample set, because they are one verb.

Each sample is checked by the same `check_collisions` the robot path uses, against the scene
with the robot at its accumulated pose and the module's joints at the interpolated values.
A colliding sample refuses with the existing `OCM_PATH_COLLISION`, naming the row's label and
the colliding pair, exactly as a robot segment does — an actuation row is a segment, and it
needs no code of its own.

The invariant `emitters/animation.py` was built around therefore holds across the whole
timeline, not just its robot half: **every frame in an emitted trace is a state that was
sampled and proved collision-free.** No `checked` flag, no unchecked-segment advisory, no
viewer obligation to distinguish two grades of frame — because there is only one grade.

**What this does not check, and why it still needs saying.** `check_collisions` skips contact
between two links of the same instance (`instance_a == instance_b`), on the sound grounds that
a robot's own arm segments touch at their shared joints by design. The same rule means two jaws
of one nest closing on each other are not checked. Separately, `cell.part` has geometry
declared in `cell.yaml` but `build.py` never places it in the scene, so nothing checks a jaw
closing onto the part either. So this decision catches a module joint sweeping into a
*different instance* — jaws into a tool parked above them, a feeder pusher into the robot — and
does not catch a fixture closing on itself or on the workpiece.

That is a real limit and it is stated here rather than discovered later. It is also why this
decision costs little: the same-instance skip removes the false positives an
allowed-collision matrix would otherwise be needed to suppress, so no ACM is introduced.

Placing `cell.part` in the collision scene is the obvious next gap and is deliberately not
opened here.

## Decision 7 — The emitted artifact is a trace; HTML is one consumer

`ocm plan` emits a JSON trace: the ordered rows, their durations and sources, their frames, the
`checked` flag, and the static scene payload. `--view-animation` becomes a renderer over that
trace rather than a producer of its own.

Without this, ADR-0030's `ocm-viewer` reimplements sequencing, and the cell acquires two
descriptions of what it does. That is precisely what ADR-0027 was written to prevent, one layer
up.

## Refusal codes

| Code | Phase | Outcome | Message |
|---|---|---|---|
| `OCM_PLAN_STEP_UNPLANNABLE` | design | refuse | Plan step `{step}` calls `{inst}.{op}`, which declares no `at:` target, no `actuates`, and no `nominal_duration_s` — nothing to place on a timeline |
| `OCM_ACTUATION_DURATION_MISSING` | design | refuse | Capability `{cap}` on `{module}` declares `actuates` but no `nominal_duration_s` — the endpoint is stated, the time is not, and it will not be invented |

`OCM_PATH_COLLISION` is reused unchanged for a colliding actuation row (D6). No new code: the
timeline has one notion of a segment and one notion of a segment colliding.

`OCM_ACTUATION_DURATION_MISSING` is the fabrication guard. ADR-0028 D5 assumed
`nominal_duration_s` would be present because every capability in the repo happens to declare
it; nothing enforced it. Without this, a timeline would have to invent a duration for a stated
motion, and it would render as a cycle time indistinguishable from a measured one.

## Consequences

**`FasteningPlan` stops being the plan.** It becomes one row producer among three.
`emitters/urscript.py`, `emitters/cycle_time.py`, `coordinator/`, and `cli.py` all consume it
today; each needs its consumption re-pointed at the timeline. This is the bulk of the work and
the bulk of the risk.

**Cycle-time output changes for the dogfood cell.** `clamp` and `unclamp` currently contribute
nothing; they will contribute 0.6 s and 0.4 s. Any test asserting a total will need updating —
those updates are correct, not accommodations, and each one should be checked to confirm the
new number is the sum of stated durations.

**Nothing in `modules/` moves yet.** Every non-robot fragment is a single static link
(ADR-0028's consequences section). This ADR makes the machinery capable of animating a clamp;
authoring the nest's real fragment is separate work and remains the owner's design facts to
state, not an agent's to invent (ADR-0014).

**Cycle-time totals change twice over.** `clamp` and `unclamp` start contributing (0.6 s and
0.4 s for the dogfood nest), and `load_screw` stops being hidden inside a transit. Every
asserted total moves, and every one should be re-derived from stated durations rather than
re-baselined to whatever the new code emits.

**The workpiece is still not in the collision scene.** `cell.part` declares `cad:` and
`features:`, and `build.py` places neither. D6 makes that gap matter more, because a checked
actuation sweep that cannot see the part reads as more thorough than it is. Worth its own ADR.
