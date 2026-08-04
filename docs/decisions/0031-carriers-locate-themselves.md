# ADR-0031 — Carriers are passive, pass through, and locate themselves

**Status:** Proposed. Consumes ADR-0028 (a capability declares the joints it actuates) and
ADR-0029 (the plan is the timeline). Extends ADR-0020 (carrier identity) with the geometry that
ADR left out. Prerequisite for the pilot cell.

## Context

OCM assumes everything in a cell is owned by the cell and controlled by it. A pallet is neither,
and five things break on contact with one.

**A carrier cannot be a module.** `state_machine` is in the module schema's `required` list. A
pallet has no controller, no PackML states, and no comms. Declaring one to satisfy a schema is
the fabrication ADR-0014 exists to refuse, performed against the schema rather than a datasheet.

**A carrier has no geometry.** ADR-0020's `carriers` block is `{tag, warn_at_fraction,
refuse_at_fraction}` — a fleet fact about identity and wear. ADR-0019's boundary handling is
three signal channels. Nothing anywhere gives a carrier a pose, a mesh, or a joint.

**The part's location is inferred from a verb.** `compute_part_datum_world` calls
`_find_clamp_fixture(cell.plan)`, which scans for a step whose `op` is `clamp`, and raises
`PlanningError("plan has no 'clamp' step -- can't tell which fixture the part is seated in")`
when there is none. In a line where the part arrives already clamped in the carrier, no cell
downstream of the first has a `clamp` step, and every one of them fails to plan.

**Actuation is module-local by construction.** `check_module_actuation` resolves every
`actuates` joint against the module's own `urdf_fragment`, unnamespaced, and refuses
`OCM_ACTUATION_JOINT_UNKNOWN` otherwise. That was right for ADR-0028 and it is wrong here: the
conveyor's pusher engages a release on the carrier, and a spring — not a command — closes the
clamp when the pusher retracts. The actuator and the actuated body are in different things that
meet only transiently.

**And the precise pose is not where the joints say it is.** A pallet arrives on a belt, is
stopped pneumatically, then lifted onto a plane-and-two-pins datum: the stop surface constrains
Z, RX, RY; tapered pins constrain X, Y, RZ. The coarse mechanisms have millimetres of
repeatability. The datum features have hundredths. Any model in which the located pose is
computed from the travel and lift joint values makes the precision pose inherit the coarse
error — which is the one thing the pins exist to prevent.

The repo has no tolerance concept at all. Not on frames, not on poses, not anywhere.

## Decision 1 — A carrier is a first-class kind, not a module and not a fleet fact

`carriers` grows a geometric sibling. A **carrier type** is authored like a module — `frames`,
`mechanical.geometry` with a `urdf_fragment`, joints, meshes — and explicitly omits
`state_machine`, `comms`, and `capabilities`, because a carrier has none of them. It is
transcribed hardware, and per ADR-0014 the absent fields stay absent rather than acquiring
placeholders.

A cell declares a carrier **instance**: which type, and where it enters. ADR-0020's existing
`carriers` block is untouched and keeps meaning what it means — identity and wear are a
different question about the same object.

**Rejected: make the carrier a module with a stub `state_machine`.** It would validate, it
would be false, and every consumer that reasons about PackML would have to special-case a
module that has no states. A schema satisfied by a lie is worse than a schema that refuses.

**Rejected: model the carrier as part of the conveyor module.** Geometrically workable — the
existing `mount.on` chain does real kinematic parenting onto a named link — but it asserts the
cell owns a pallet borrowed from the line, and it duplicates the carrier's transcription into
every cell it passes through.

## Decision 2 — The located pose is the origin of the chain, and transit is a departure from it

The carrier's kinematic chain is rooted at the datum it is located against, not at the mechanism
that brings it there:

```
conveyor_base --[fixed]--> located_datum --[prismatic: travel]--> --[prismatic: lift]--> carrier
```

`located_datum` is a frame rigid to the conveyor's own machined structure: the pose a correctly
seated carrier lands at. **Both joints at zero IS the located pose.** Transit is negative
offset — `travel: -400 mm` at the entry opening, `lift: -12 mm` riding the belt.

Every joint between `located_datum` and the carrier is therefore at zero for the whole of the
work the cell does. The part datum derives from machined geometry and nothing else, which is
what a plane-and-two-pins fixture physically does.

This also dissolves a problem ADR-0028 could not express. A pneumatic lift running until it hits
a hard stop has no commanded position, and `actuates: {to: 12, units: mm}` would claim one. Under
this inversion nothing declares a commanded travel: the stopped position is a datum and
everything else is an offset from it. The honest statement and the convenient one coincide.

**Rejected: root the chain at the conveyor base and derive the located pose forward.** It is the
obvious direction and it is precisely wrong — it makes the hundredths-precision pose a function
of two millimetres-precision joint values. Store constraints, not derived transforms.

## Decision 3 — A located datum declares its constraint features and each one's tolerance

`located_datum` is not a bare frame. It declares which physical features constrain which degrees
of freedom, and how well:

```yaml
located:
  frame: located_datum
  constraints:
  - feature: lift_stop_surface
    governs: [z, rx, ry]
    tolerance: {z: {value: 0.05, unit: mm}, rx: {value: 0.02, unit: deg}, ry: {value: 0.02, unit: deg}}
  - feature: locating_pins
    governs: [x, y, rz]
    tolerance: {x: {value: 0.03, unit: mm}, y: {value: 0.03, unit: mm}, rz: {value: 0.05, unit: deg}}
```

Every one of the six degrees of freedom is governed exactly once. A DOF governed twice refuses;
a DOF governed by nothing refuses. Both are the same failure — a fixture whose constraint scheme
does not close — and finding it in a manifest is cheaper than finding it in steel.

Tolerances are declared per feature, not per datum, because the plane and the pins are different
features with genuinely different numbers, and averaging them into one figure would be an
invented value.

`source: measured | datasheet | estimated`, as ADR-0029 already carries on durations. A
tolerance that has never been measured says so, and anything quoting a positional accuracy
derived from it inherits the label.

Transit poses declare no tolerance and need none. Nothing precise happens there.

**`located` lives on the conveyor module, not on the carrier, and not on both.** The datum
features are machined into the conveyor's structure and do not travel; the carrier is the thing
being located, not the thing doing the locating. Splitting the declaration across both — pad
faces and pin bushings on the carrier, stop surface and pins on the conveyor — describes the
fit more completely and was rejected for it: two manifests would then have to agree about one
constraint scheme, and nothing could check that they did without modelling the mating itself.
One owner, one declaration, one place a refusal points at.

The carrier's side of the fit is not lost, only unstated here. If bushing wear ever needs a
tolerance of its own, it belongs with ADR-0020's wear budget, which already owns how a carrier
degrades over its life.

## Decision 4 — The part datum is declared on the carrier, not inferred from a `clamp` step

A carrier type declares `frames.part_datum` — where a correctly seated part's own origin lands —
exactly as a fixture module does today.

`compute_part_datum_world` stops calling `_find_clamp_fixture`. It reads the cell's carrier
instance, takes that carrier's `part_datum`, and composes it through the world pose of the
carrier's root link, which the D2 chain already places. `_find_clamp_fixture` is deleted rather
than kept as a fallback: a plan-scraping heuristic and a declaration are two answers to one
question, and the heuristic is the one that is wrong in every cell but the first.

A cell whose plan operates on a part but declares neither a carrier nor a fixture with
`part_datum` refuses `OCM_PART_DATUM_UNDECLARED`. It does not guess.

**Consequence for the first cell.** The loading cell's pallet arrives empty and the part's
location changes during the plan — source, then gripper, then carrier. This decision makes the
carrier's `part_datum` a stated fact, which is a precondition for modelling that, but it does not
model it. Pick and place are a shape ADR-0032 has to define; this ADR assumes the part is
already in the carrier when the cell's plan begins, and a cell that assumes otherwise is not
plannable yet.

## Decision 5 — A module may actuate a carrier joint it physically engages

ADR-0028's module-local rule is relaxed exactly once, and narrowly. A capability's `actuates`
entry may name a joint on the carrier by an explicit `carrier:` qualifier:

```yaml
- name: release_clamp
  actuates:
  - {joint: release_pusher, to: 8.0, units: mm}
  - {carrier: true, joint: clamp_jaw, to: 6.0, units: mm}
  nominal_duration_s: 0.4
```

Both joints move on one verb, because engaging the pusher opens the jaw. That is a true
statement about the mechanism, and it needs no coupled-joint machinery — URDF `<mimic>` would be
the alternative and `_joint_motion` has no mimic handling at all, so it would silently do
nothing.

`check_module_actuation` gains the carrier fragment for qualified entries, and every ADR-0028
check applies to them unchanged: unknown joint, fixed joint, unit mismatch, out of limit.

**Only a module may reach into a carrier, never the reverse.** A carrier has no capabilities to
reach with. The relaxation is one-directional and stays that way.

**A spring return is not an actuation.** The pusher retracting is a commanded motion; the jaw
closing behind it is stored energy. Both are declared here as joint targets because that is what
the geometry does, but the carrier's clamp is at rest closed — its zero — and no verb anywhere
commands it shut. `OCM_CARRIER_CLAMP_NOT_AT_REST` advises when a carrier type's clamp joint has a
non-zero rest value, because a spring clamp whose unpowered state is open is almost certainly a
transcription error.

## Refusal codes

| Code | Phase | Outcome | Message |
|---|---|---|---|
| `OCM_PART_DATUM_UNDECLARED` | design | refuse | Cell plan operates on `part` but no carrier or fixture declares `frames.part_datum` |
| `OCM_LOCATED_DOF_UNGOVERNED` | design | refuse | `located.constraints` governs no feature for {dof} — the constraint scheme does not close |
| `OCM_LOCATED_DOF_OVERCONSTRAINED` | design | refuse | {dof} is governed by both `{feature_a}` and `{feature_b}` |
| `OCM_LOCATED_TOLERANCE_MISSING` | design | refuse | `{feature}` governs {dof} but declares no tolerance for it |
| `OCM_CARRIER_TYPE_HAS_CONTROL` | design | refuse | Carrier type `{id}` declares `{field}` — a carrier has no controller, no states, and no capabilities |
| `OCM_CARRIER_JOINT_UNKNOWN` | design | refuse | Capability `{cap}` actuates carrier joint `{joint}`, absent from carrier type `{id}`'s fragment |
| `OCM_CARRIER_UNPLACED` | design | refuse | Cell declares carrier `{name}` with no entry pose and no `located` datum to rest at |
| `OCM_CARRIER_CLAMP_NOT_AT_REST` | design | advise | Carrier type `{id}`: clamp joint `{joint}` has a non-zero rest value — a spring clamp rests closed |

## Consequences

**`_find_clamp_fixture` is deleted and `compute_part_datum_world` is rewritten.** Both are on the
path every planning verb takes. The dogfood cell has a `clamp` step and will keep planning
through the new path, which makes it a usable regression check rather than a rewrite.

**Tolerances are declared and not yet consumed.** Nothing reads them in this ADR. They are
declared now because the numbers are known at authoring time and are unrecoverable later, and
because a located pose without them is a claim of infinite precision. What consumes them — IK
pose derivation, collision margins, a stated positional accuracy — is a later decision.

**Handedness is two carrier-facing modules, not one parameterised module.** A left-entry and a
right-entry conveyor put the stop pins in different places, so their `located` frames and
constraint features differ. Frames are transcribed facts and OCM has no parameterisation; two
manifests with two part numbers is the honest shape.

**The first cell is still not plannable.** D4 states the part datum; it does not move the part.
That is ADR-0032.

**The carrier still does not cross the cell boundary.** A carrier entering and leaving is
modelled here as travel to and from the entry offset. Line-level composition — the same physical
pallet handed between cells — is ADR-0019 D5's deferred territory and stays deferred.
