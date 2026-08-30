# ADR-0027 — Collision geometry is derived from posed components, or authored and checked against them

**Status:** Accepted. Resolves the conflict between ADR-0015 D1 and ADR-0007; amends
ADR-0016 D3's publish requirement.

## Context

ADR-0007 calls `urdf_fragment` the load-bearing field of the whole spec: `cell.yaml` compiles
into a Tesseract scene graph, and the planner will not drive through a module it knows about.

ADR-0015 D1 places component instances by pose against a STEP-derived GLB backdrop, and
accepts explicitly that if the manifest and the geometry disagree, nothing detects it. The
justification was that "the manifest is what generates code, and the geometry is what a human
looks at."

That justification does not hold, because the geometry is also what the planner collides
against, and the two artifacts are produced independently:

- A module's `mechanical.geometry.collision` is a single mesh path, hand-produced from CAD.
- Component instances carry their own `pose` in the module frame.
- `scene/build.py` assembles the scene from each module's `urdf_fragment`. **Component
  instances and their poses never enter the scene at all.**

So moving, adding, or deleting a component instance changes the manifest, changes what the
Module page draws, and changes nothing the planner sees. The accepted cost was documentation
drift. The actual exposure is a robot planning against geometry that no longer describes the
machine — and the failure is silent, which is the one property ADR-0012 exists to exclude.

The asymmetry that shapes the fix: **collision geometry that is too small is dangerous;
geometry that is too large is merely conservative.** A missed volume is a crash. An excess
volume is a refused plan and an engineer who investigates.

## Decision 1 — A module declares how its collision geometry is produced

`mechanical.geometry.collision_source` is required on a published module, with two values.

**`derived`** — the module declares no collision mesh artifact. The resolver builds the
collision proxy from what the manifest already states: each component instance's transcribed
envelope, placed at its declared pose, plus the module's own declared structural primitives
(D3). One source, no second artifact, nothing to fall out of sync.

**`authored`** — the module declares a mesh path, hand-produced from CAD, and it is
authoritative. The resolver does not replace it. It does check it (D2).

**Rejected: leave it implicit and infer from whether a mesh path is present.** Absence would
then mean two different things — "derive it" and "not transcribed yet" — which is precisely
the placeholder-versus-absence confusion ADR-0016 D3 was written to remove.

## Decision 2 — In `authored` mode, component envelopes must be contained

Every component instance's envelope, at its declared pose, must lie within the module's
authored collision geometry. A component protruding outside it is a refusal.

This is deliberately one-directional. It catches the dangerous case — a component the planner
does not know is there — and it does not complain about an authored mesh that is larger than
the sum of its parts, because conservative geometry is fine and demanding tightness would
make the check unusable on any real convex hull.

It is also the check that closes ADR-0015 D1's open cost. The manifest and the geometry can
still disagree; they can no longer disagree *in the direction that hurts* without saying so.

## Decision 3 — Module-owned structure is declared as primitives, not transcribed

A module is not only purchased parts. Brackets, plates, and standoffs are fabricated, have no
datasheet, and under ADR-0014 have nothing to transcribe.

`mechanical.structure[]` declares them as posed primitives — box, cylinder, or a mesh path
for a fabricated part we produce and therefore own the CAD for. This is module-layer design
in the ADR-0014 sense, authored, not transcribed. It is what makes `derived` mode viable for
a real assembly rather than only for a rack of purchased devices.

## Decision 4 — Component instances attach to a link; the fragment stays authored

Kinematics is design. `urdf_fragment` continues to be authored at the module layer and is not
derived from anything.

A component instance gains an optional `link` naming a link in that fragment, defaulting to
the fragment's root. That is what lets a component riding a moving axis travel with it
instead of sitting in space.

This is not the STEP node-path binding ADR-0015 D1 rejected. The objection there was that CAD
node paths are unstable across re-export and would need a rebind-diff mechanism and a
matching heuristic. Link names are authored by us, in our own fragment, in the same repo as
the manifest that names them. A link that does not exist is a refusal, which is a check, not
a mechanism.

## Decision 5 — `derived` mode requires complete inputs, and refuses instead of approximating

A module in `derived` mode where any component instance lacks a `pose`, or whose referenced
component declares no `geometry.envelope`, is refused. The resolver does not fall back to a
bounding box of what it happens to have, and does not silently omit the incomplete instance.

A partial collision proxy is the worst artifact in this design: it looks like a collision
model, it is smaller than the machine, and nothing says so. Refusing produces ADR-0014's
completion list instead — and `geometry.envelope` is datasheet-answerable, so the missing
values are transcription work, not design work.

**Overlapping envelopes are `advise`, not `refuse`.** Real assemblies interpenetrate — a
bracket wraps a sensor, a fitting enters a manifold. Overlap is weak evidence of a pose error
and strong evidence of nothing. It is surfaced and not gated (ADR-0025 D3).

## Decision 6 — `publish_module` requires a collision *source*, not a collision *mesh*

ADR-0016 D3 requires artifact claims at publish. Amended: what publish requires is that the
module can produce collision geometry — an authored mesh, or a complete `derived` input set.
A published `derived` module with no mesh artifact is correct and complete.

Nothing is weakened. A module still cannot reach publish claiming geometry it cannot produce;
the claim is now about producibility rather than about a file existing.

## Shape

```yaml
mechanical:
  geometry:
    visual: assets/dp8-module.glb
    urdf_fragment: assets/dp8-module.urdf.xacro
    collision_source: derived        # derived | authored
    # collision:  <- absent in derived mode; required when authored

  structure:
    - {id: mount-plate, shape: box, size: [180, 120, 8], units: mm,
       pose: {xyz: [0, 0, 0], rpy: [0, 0, 0]}}
    - {id: riser, shape: cylinder, radius: 12, length: 90, units: mm,
       pose: {xyz: [60, 0, 4], rpy: [0, 0, 0]}, link: base}

components:
  - refdes: DP1
    ref: com.nordson-kline.dispenser.dp8@1.0.0
    link: z_carriage                 # ADR-0027 D4; defaults to the fragment root
    pose: {xyz: [0, 0, 94], rpy: [0, 0, 0]}
```

Refusals this admits:

| Refusal | Mode |
|---|---|
| Published module declares no `collision_source` | both |
| `authored` with no `collision` path, or a path that is not a file | authored |
| Component envelope at its pose protrudes outside the authored collision geometry | authored |
| `derived` and a component instance has no `pose` | derived |
| `derived` and a referenced component declares no `geometry.envelope` | derived |
| `derived` and a `structure` primitive is missing a dimension or units | derived |
| A component instance or structure primitive names a `link` absent from the fragment | both |
| Component envelopes overlap (`advise`, not `refuse`) | derived |

## Consequences

- **`scene/build.py` gains a collision-geometry step it does not have.** Today it assembles
  from `urdf_fragment` alone; it must now emit per-link collision geometry from posed
  envelopes and structure primitives in `derived` mode.
- Envelope boxes are convex, which is what ADR-0007 notes Tesseract's Bullet backend wants.
  The derived proxy is coarser than a hull and faster, and coarse-but-known beats
  precise-but-stale.
- **The Module page's component placement stops being decorative.** A pose edit changes the
  collision scene, which is what an author already assumes is happening.
- ADR-0015 D1's rejection of STEP node-path binding stands unchanged, and its accepted cost
  narrows to what it was actually argued for: the GLB backdrop remains documentation, and
  nothing detects if it drifts. Nothing safety-relevant depends on it any more.
- `geometry.envelope` moves from a nice-to-have on the component schema to a load-bearing
  transcription field. Existing component definitions that omit it will refuse when a module
  referencing them selects `derived`. That is the intended effect.
- **Units.** Envelopes are transcribed verbatim (ADR-0014) and may be printed in `in` or `mm`.
  Deriving geometry requires converting them. This is the deterministic-resolver dependency
  that ADR-0021's measurement refusal also carries and that no ADR has yet established. It
  must land with this work, outside the model, per ADR-0014's verbatim-capture policy.

## Related

ADR-0007 (Tesseract), ADR-0012 (one refusal engine), ADR-0014 (components vs modules),
ADR-0015 (module connectivity), ADR-0016 (one validation surface), ADR-0025 (refusal phases),
ADR-0026 (ports)
