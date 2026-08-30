# ADR-0028 — A capability declares the joints it actuates

**Status:** Accepted (Erratum 1). Extends ADR-0023 (plans are verbs) with the geometric half of a verb.
Prerequisite for the verb-driven timeline (ADR-0029).

## Context

`scene/kinematics.py` already implements generic forward kinematics over a composed URDF.
`_MOVABLE_JOINT_TYPES` covers revolute, continuous, and prismatic; `_joint_motion` translates
along `<axis>` for prismatic and rotates for the rest, driven by a namespaced `joint_state`
map. `build.py` namespaces and splices every instance's `urdf_fragment` and validates a
cell-supplied `joint_state` against that instance's own joints. Two consumers — the debug
viewer and the workspace containment check — share that one FK implementation, deliberately.

None of it has ever been handed a joint that isn't part of a robot.

Every non-robot module fragment in the repo is a single static link. The pneumatic nest's
fragment is an axis-aligned box with a comment admitting it is a stub. The nest declares
`clamp` with `postconditions: [clamped == true]` and `nominal_duration_s: 0.6`. Nothing
anywhere states that clamping moves anything, or how far.

The consequence is that the machine's process state and the machine's geometry are two
disconnected descriptions. `clamp` is fully specified as a PackML transition and completely
unspecified as a physical event. A scene rendered from the manifests shows a nest that never
closes, and — more importantly — a collision check run at any point in the plan collides
against jaws that are always in their authored position, whatever that happens to be.

That is the ADR-0027 failure mode in the time dimension. ADR-0027 closed the gap where the
planner collided against geometry that no longer described the machine's *layout*. This is the
gap where it collides against geometry that does not describe the machine's *state*.

## Decision 1 — `actuates` is a field on a capability

A capability MAY declare `actuates`: the joints the verb drives and the value it drives them
to. The joint names are the module's own, in its own `urdf_fragment`, unnamespaced.

```yaml
capabilities:
- name: clamp
  summary: "Close both jaws and hold the part at a target force."
  preconditions:
  - clamped == false
  - part_present == true
  postconditions:
  - clamped == true
  actuates:
  - {joint: jaw_left,  to:  6.0, units: mm}
  - {joint: jaw_right, to: -6.0, units: mm}
  nominal_duration_s: 0.6
  timeout_s: 3.0
  on_timeout: hold
```

The verb is the transition. `to` is the value the joint holds when the postcondition is true;
there is no `from`, because the precondition already asserts where the machine was and the
preceding capability already declared how it got there. Joint state carries forward through a
plan, seeded by `cell.yaml`'s existing per-instance `joint_state` (or zero).

**Rejected: a separate `mechanical.actuation` block that capabilities reference by name.**
More verbose, and it decouples geometry from the process verb — which is the wrong direction.
A capability that changes the machine's physical state and a capability that does not are
different things, and the manifest should say which one it is at the point where the rest of
the transition is already declared. The decoupled form buys generality (a joint two
capabilities move, a joint no capability commands) that no module in the repo needs, at the
cost of a level of indirection every reader pays for.

**Rejected: named states (`to: closed`) with a state table elsewhere in the module.** Same
indirection cost, and it invites the state table and the capability set to drift.

## Decision 2 — Units are explicit and type-checked against the joint

`units` is REQUIRED on every `actuates` entry and resolved through `ocm_core.units`, as
`mechanical.structure` already does.

This is not ceremony. URDF prismatic values are metres and revolute values are radians, and
`joint_state` today is a bare float documented as "radians, applied as-is." A 12 mm clamp
stroke is `0.012` in that convention. A bare number that means two different things depending
on a joint type declared in a different file is precisely the silent-plausible-value failure
the refusal engine exists to exclude: authored as `12`, it renders a jaw twelve metres away,
and the render still looks like a render.

A linear unit on a revolute or continuous joint refuses. An angular unit on a prismatic joint
refuses. An unrecognised unit refuses through the existing `OCM_UNIT_UNRECOGNISED`.

## Decision 3 — Actuation targets are checked against the joint's own limits

An `actuates` target outside the joint's `<limit>` refuses at resolve.

`build.py`'s `_validate_joint_state` currently catches an unknown joint name and a fixed joint,
then assigns `joint_state_out[namespaced] = float(value)` with no comparison against `<limit>`.
That gap is retrofitted here, for `actuates` and for `cell.yaml`'s `joint_state` alike, because
they are the same class of claim and there is no reason one should be checked and the other
not. A joint driven through its own stop is a fabricated machine state.

A continuous joint has no limits to check and is exempt.

## Decision 4 — Absence renders static and advises; it does not refuse

A capability with no `actuates` is a capability that moves nothing. That is a legitimate
description — `locate_part` moves no joint — and per ADR-0014 an absent field stays absent
rather than acquiring a guess.

But a module whose fragment declares a movable joint that NO capability actuates is almost
certainly incomplete authoring, and it is invisible otherwise. That advises
(`OCM_JOINT_UNACTUATED`), so it lands on the human's completion list without blocking a
resolve. The engine cannot tell a genuinely passive joint from an unfinished one, so it says
so rather than deciding.

## Decision 5 — Timing comes from `nominal_duration_s`, unchanged

No new timing field. `nominal_duration_s` already exists on every capability and
`CycleTimeRow.source` already carries `"nominal_duration_s"` through to the viewer's captions,
distinct from `"ESTIMATE"`. A downstream animation therefore inherits the existing honesty
about where a number came from at no cost, and this ADR does not introduce a second, parallel
notion of how long a verb takes.

Interpolation between the previous joint value and `to` is linear at constant timestep, and is
ADR-0029's problem, not this one. This ADR is responsible only for the endpoint being a stated
fact rather than an inference.

## Refusal codes

| Code | Phase | Outcome | Message |
|---|---|---|---|
| `OCM_ACTUATION_JOINT_UNKNOWN` | design | refuse | Capability `{cap}` actuates joint `{joint}`, absent from this module's `urdf_fragment` (has: {known}) |
| `OCM_ACTUATION_JOINT_FIXED` | design | refuse | Capability `{cap}` actuates `{joint}`, a fixed joint — no configurable position |
| `OCM_ACTUATION_UNIT_MISMATCH` | design | refuse | Capability `{cap}` gives `{joint}` a {kind} unit `{units}`; a {joint_type} joint takes {expected} |
| `OCM_ACTUATION_OUT_OF_LIMIT` | design | refuse | Capability `{cap}` drives `{joint}` to {value} {units}, outside its declared limit [{lower}, {upper}] |
| `OCM_ACTUATION_CONFLICT` | design | refuse | Capability `{cap}` actuates `{joint}` more than once |
| `OCM_JOINT_STATE_OUT_OF_LIMIT` | design | refuse | Instance `{inst}`: `joint_state` drives `{joint}` to {value}, outside its declared limit [{lower}, {upper}] |
| `OCM_JOINT_UNACTUATED` | design | advise | Module `{id}`: movable joint `{joint}` is actuated by no capability |

## Consequences

**Authoring cost is the real cost.** Every non-robot fragment in `modules/` is a stub. Making
the nest clamp means authoring a real fragment with two prismatic jaw joints, limits, and
per-link collision geometry. The code change is small; the modelling is not, and it is
per-module.

**`scene/kinematics.py`'s module docstring is wrong** and should be corrected in this work. It
states that every prismatic joint is evaluated at zero, which contradicts `_MOVABLE_JOINT_TYPES`
and the prismatic branch of `_joint_motion` directly below it. An agent reading that docstring
before the code would reasonably conclude prismatic actuation is unsupported and design around
a limitation that does not exist.

**The module schema's `capabilities.items` is `additionalProperties: false`**, so `actuates`
does not exist until the schema says it does; there is no permissive interim.

**This ADR renders nothing.** It makes a capability's geometric effect a stated fact and
refuses the ways of stating it wrongly. Turning a sequence of those facts into a timeline —
generalising `FasteningPlan`, adding an actuation row kind to `CycleTimeReport`, and removing
`emitters/animation.py`'s robot-vs-static partition — is ADR-0029.

## Erratum 1 (2026-08-04) — the D3 retrofit, fragment-parse failures, and joint enumeration

Found in review of the initial implementation. Three places where what this ADR said and what
the code did diverged, all on the permissive side.

**The D3 retrofit was asymmetric across layers.** This ADR states that a non-`continuous`
joint with no `<limit>` is malformed URDF and refuses. The module-layer check
(`scene/actuation.py`) did that; the cell-layer retrofit (`_validate_joint_state` in
`scene/build.py`) guarded on the `<limit>` element existing before checking it, so a
`joint_state` value on a limitless revolute joint — the exact malformation — passed through
unchecked into the scene. Same claim, same class of defect, opposite outcomes by layer. Both
layers now refuse, and an incomplete `<limit>` (`lower` without `upper`, or the reverse) is as
uncheckable as an absent one and refuses identically. The cell-layer message reuses
`OCM_JOINT_STATE_OUT_OF_LIMIT` and says the limit is *missing*, mirroring the module layer's
use of `OCM_ACTUATION_OUT_OF_LIMIT` for the same condition — no new code for a variant of a
condition the catalogue already names.

**A malformed fragment silently disabled every fragment-dependent check at validate time.**
`check_module_actuation` and `fragment_link_names` (ADR-0027) both swallow fragment parse
failures, on the grounds that the fragment's own load path reports them. At *scene* time that
is true — `build_scene` refuses. At *validate* time nothing parsed the fragment at all:
`validate_module` checked only that the file exists, so a fragment of unparseable XML
validated green with every joint, link, and limit check silently skipped. That is the failure
mode ADR-0025 exists to forbid — a check that cannot run must say so, not vanish.
`validate_module` now parses a fragment that exists, through the scene's own `load_fragment`
(one parser, one error type — a fragment must not validate under a laxer parser than the one
that composes it), and refuses with **`OCM_FRAGMENT_MALFORMED`** (`phase: design`, `outcome:
refuse`). The downstream swallows stay, and are now honest: the refusal they defer to
genuinely fires upstream.

**Joint enumeration must match the composition path.** `scene/actuation.py` collected joints
with `iter("joint")`, which also matches a `<joint>` nested inside a `<transmission>` — an
element `namespace_fragment` never splices into the scene. A capability actuating such a joint
would have validated against a joint that does not exist in the composed cell, and a nested
joint would have suppressed or generated `OCM_JOINT_UNACTUATED` advisories for phantoms.
Enumeration is now top-level `findall("joint")`, the same shape the composition path walks.
(`collision_geometry.py` has the same `iter` usage for links and joints; that is ADR-0027's
decision surface and is recorded here as an observation, not changed.)
