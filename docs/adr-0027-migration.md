# ADR-0027 migration worklist — reported, not performed

What every existing `modules/` and `components/` entry needs to satisfy ADR-0027. Nothing here
was changed in the landing pass (the ADR's engine work is in; the manifests are not migrated —
per the landing brief, this report IS the transcription worklist). Until a module republishes,
nothing refuses: `collision_source` is gated at `publish_module`, and the mode-specific checks
fire only once a mode is declared.

## The blunt summary

**No shipped module declares a `components:` list.** Every one of the eight is a
whole-purchased-device or placeholder-CAD module with a single `collision` mesh path — and
every one of those mesh paths except two is a placeholder that does not exist on disk. So
today's honest positions are:

- `derived` is **not yet available to any shipped module** — there are no posed component
  instances to derive from. Choosing it means doing the ADR-0014 transcription work first
  (components + poses + envelopes).
- `authored` is only honest where a real mesh exists — today that is **ur5e** (real vendored
  meshes) and **vg25** (a generated stub, which `generate_geometry_stub` now stamps
  `authored`).

## Per module

| Module | Recommended mode | What it needs |
|---|---|---|
| `com.universal-robots.ur5e` | **authored** | Nothing but the declaration — real collision meshes exist (`meshes/collision/*.stl`). The one module migratable by adding a single line. |
| `com.acme.gripper.vg25` | **authored** | The declaration; its `collision` is the generated stub fragment (the stub path now writes `collision_source: authored` for new stubs — this one predates that). |
| `com.accelsolutions.screwdriver.sd50` | **derived** (eventually) | Placeholder mesh (`meshes/sd50_convex.stl` does not exist). Honest path: transcribe its parts (motor, vacuum unit, feed block) as components with envelopes + poses, or author a real mesh. Until then, no declaration and no republish. |
| `com.accelsolutions.fixture.pneumatic-nest` | **derived** (eventually) | Same — placeholder mesh; jaws/cylinder/base are transcribable parts. |
| `com.accelsolutions.screwfeeder.sf20` | **derived** (eventually) | Same — placeholder mesh. |
| `com.accelsolutions.dispense.dh200` | **derived** (eventually) | Same — placeholder mesh; the head is a purchased device family (dp8's relatives) whose envelopes are datasheet-answerable. |
| `com.lmi.gocator.2350` | **authored** (real CAD is published by LMI) or derived | Placeholder mesh today. |
| `com.accelsolutions.base.frame1200` | **authored** | Placeholder mesh; the frame is our own CAD (ADR-0005's DXF-is-the-deliverable), so an authored hull is the natural artifact. Alternatively `structure[]` primitives make it the cleanest `derived` candidate — it is nothing BUT structure. |

## Per component

| Component | `geometry.envelope` | Work |
|---|---|---|
| `com.nordson-kline.dispenser.dp8` | **COMPLETE** (mm) | None — already load-bearing-ready. |
| `com.automation-direct.eps25-100wc-1001` | **ABSENT** (`geometry: {}`) | Transcribe length/width/height/units from the datasheet. Datasheet-answerable; until then any module referencing it in `derived` mode refuses `OCM_DERIVED_ENVELOPE_MISSING` — the intended effect. |

## The DP-8 module in particular

There is **no DP-8 module in `modules/`** — the "DP-8 module" of ADR-0027's Shape block is the
cold-test artifact (`docs/cold-test-module-authoring.md`), authored during the ADR-0015 cold
test and never committed as a manifest. What it requires when it lands, per the Shape block:

1. `collision_source: derived` — it is exactly the module the mode was designed for (a
   purchased dispenser + mounting plate + riser).
2. A `components:` entry for `DP1` (`com.nordson-kline.dispenser.dp8@1.0.0`) with a `pose` —
   dp8's envelope is already complete, so nothing blocks on transcription.
3. `mechanical.structure[]` for the mount plate and riser (box + cylinder, mm) — the Shape
   block's own example values.
4. `link: z_carriage` on DP1 once its fragment has a moving axis; until the fragment exists,
   the default-root behaviour is correct.
5. Its pressure sensor (`eps25`) as a second component instance — **blocked on eps25's absent
   envelope** (see above); the module refuses `OCM_DERIVED_ENVELOPE_MISSING` until that
   transcription lands, which is ADR-0014's completion list working as designed.

## Open questions recorded during landing

- **Mixed modes per link** (authored bridge + derived tooling on a gantry): decided *not in
  this pass* — one `collision_source` per module, matching ADR-0027 as written. When a real
  gantry module needs it, per-link mixing is a small additive erratum, not speculative schema.
- **Containment semantics**: convex hull (face half-spaces; hull == mesh for the repo's
  `_convex.stl` convention). On a concave authored mesh this can only under-refuse — the
  conservative direction ADR-0027 already accepts. Revisit only if a concave authored mesh
  becomes real.
- **Draft default**: none. A fresh draft omits `collision_source` (choosing is design);
  `generate_geometry_stub` stamps `authored` because a stub mesh *is* an authored artifact.
