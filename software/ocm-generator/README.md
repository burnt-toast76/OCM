# ocm-generator

**This is the thesis.** See [ROADMAP Step 1](../../ROADMAP.md).

```
cell.yaml + plan.yaml
  -> scene/    URDF fragments -> Tesseract environment   <- built
  -> planner/  Tesseract IK + a collision-checked joint-space line  <- built (v0: first drive_screw step only)
  -> emitters/ URScript, PLCopen XML                     <- built (URScript only)
  -> validate/ THE REFUSAL LOGIC
```

**The most valuable output of this tool is "no."**

## scene/ (`ocm_generator.scene`)

Takes a `ResolvedCell` (from `ocm-resolve`) and a module search path and
composes it into a single combined URDF (a `Scene`) -- ADR-0007's "cell.yaml
compiles directly into a Tesseract scene graph," half of it. `build_scene`
itself never touches `tesseract_robotics`: it's plain Python/XML, so the
base `ocm-generator` install doesn't need Tesseract at all. Every instance's
`mechanical.geometry.urdf_fragment` gets namespaced and spliced into the
combined URDF, attached either to `world` (mount.pose, converted from the
schema's mm/deg to URDF's m/rad) or, for `mount.on` chains (e.g. `sd1` on
`robot1.flange`), kinematically parented to the target's own named link with
an identity offset -- not a computed world-frame pose, since a tool's
position on a moving robot depends on live joint state.

`build_scene(resolved, modules_root)` raises `SceneBuildError` -- carrying
every violation found, not just the first -- if any urdf_fragment is
missing/malformed or any `mount.on` names an attachment link that doesn't
exist. It builds cleanly end-to-end on the real `bracket-asm-01` cell: every
module it references has real collision geometry now -- six box primitives
derived from each manifest's own `footprint_mm`/frame offsets, and a real
vendored-and-flattened UR5e (see `modules/com.universal-robots.ur5e/NOTICE.md`).
See `tests/test_scene_build_real_bracket_cell.py`.

A link may carry several `<collision>` boxes (frame1200's own link is a
deck slab plus four guard walls -- see its `urdf/frame1200.urdf.xacro`
comment and spec/02's datum convention); `ocm_generator.scene.kinematics`
parses and forward-kinematics-places all of them, not just the first, and
that same module backs both the viewer and:

**Workspace containment.** The base module's own collision geometry (deck
+ walls) *is* the workspace footprint. `build_scene` computes every
non-base instance's world AABB and refuses the cell if it extends past
that footprint (X/Y only), naming the instance and the overhang in mm.
The robot itself is exempt -- its reach is configuration-dependent by
design, and keeping it inside the walls at every commanded pose is the
planner's job, not a static check (spec/02: the walls are collision
geometry *for the planner*; this check is a cheap stand-in for one part of
that, done now, before there is a planner). Anything mounted ON the robot
(e.g. `sd1`) is *not* exempt, because it has a well-defined static pose to
check once a `joint_state` is given:

**`joint_state`.** A cell.yaml module instance may declare an optional
`joint_state:` map (joint name -> radians, applied as-is -- no mm/deg
conversion, unlike `mount.pose`). Composed into the scene via the same
kinematics used for the viewer/containment check; any joint left
unspecified, and every fixed joint, sits at zero. `bracket-asm-01`'s
`robot1` carries a folded home pose for exactly this reason: at the arm's
default all-zero pose, `sd1` lands about 2 mm outside the guard-wall
footprint; folding `shoulder_lift`/`elbow` brings it back inside with
~400 mm to spare. See `test_real_bracket_cell_without_the_folded_joint_state_pokes_through_the_wall`
for the regression test that pins this down by removing the block and
watching `build_scene` refuse the cell again.

**`--collision`** (the only thing here that needs the `tesseract` extra --
see CLI section below): loads the composed URDF into a real Tesseract
`Environment`, applies `Scene.joint_state`, and runs a real discrete
contact check with an actual Bullet backend
(`ocm_generator/scene/collision.py`). Two things are structurally exempted
from ever counting as a crash, not just tolerated within the margin: an
instance and whatever it's *directly* mounted on (a robot's base flush
against the deck it's bolted to, a tool flush against the flange it's
bolted to) -- but only one hop of it, deliberately not transitively, since
"sd1 safely touches robot1" and "robot1 safely touches base" do not
compose into "sd1 safely touches base." `sd1` actually punching into a
guard wall at the arm's zeroed pose is exactly the case that must still
fire, and does (see `tests/test_collision.py`).

## planner/ (`ocm_generator.planner`) + emitters/ (`ocm_generator.emitters`)

`ocm plan --emit-urscript` (needs the `tesseract` extra, like `--collision`
above): plans the motion for the first `drive_screw` step in a cell's
`plan` -- the first for_each item, walking `sequence`/`on_fail` nesting but
never descending into an `on_fail` branch itself, since that's recovery,
not the forward path this builds motion for -- and emits it as URScript.

**Where the part is.** `locate_part`'s actual vision result isn't
modeled -- like `.scene.kinematics`, this isn't a live simulator. The
plan's own `clamp` step names which fixture the part is seated in; that
fixture's manifest `part_datum` frame ("where a correctly-seated part's
own origin lands" -- see `com.accelsolutions.fixture.pneumatic-nest`'s own
note) gives the nominal part pose directly, which is exactly what the
vision system exists to verify, not something this bypasses.

**Standoff/contact/retract poses** (`ocm_generator/planner/poses.py`) come
from the targeted `cell.part.features.*` entry (`xyz_mm`/`normal`, in the
fixture's `part_datum` frame) and the capability's own `motion` block
(`approach_vec`/`approach_mm`/`approach_speed_mm_s`/`retract_vec`/
`retract_mm`) -- computed directly in the tool's FLANGE frame (not its TCP)
since IK needs the flange pose and sd50's `tcp` frame is a purely
translational offset from it.

**Reachability** (`ocm_generator/planner/ik.py`): each pose is solved with
`tesseract_kinematics`' real analytic UR inverse kinematics
(`URInvKinFactory`, `model: UR5e`) against the composed scene's own URDF.
An unreachable pose is refused by name (`PoseUnreachableError`, naming
"standoff" or "contact") -- not retried, not routed around.

**The home->standoff path** (`ocm_generator/planner/path.py`): a straight
line in JOINT SPACE (not Cartesian) from the robot's committed home
`joint_state` to the IK-solved standoff, sampled at `--path-samples`
(default 50) states and collision-checked at each one with the same
`check_collisions` `--collision` uses. A straight line that collides is
refused (`PathCollisionError`, naming the colliding instance pair and how
far along the path it happened), even when both endpoints are
individually clear -- see `tests/test_planner.py`'s test against the real,
committed `bracket-asm-01` cell, where the straight-line path to every one
of its three holes swings the wrist through `cam1` (the vision camera
mounted over the workspace) despite home and the standoff itself each
being clean on their own. **This is deliberately not path-planned or
optimized (no OMPL, no TrajOpt) -- refusing a colliding straight line is
correct v0 behavior**, matching this package's own thesis that "the most
valuable output of this tool is 'no.'" Only the standoff->contact `movel`
(a few mm along the capability's own approach vector) and the retract
`movel` are not re-verified -- that channel is what `approach_vec` was
declared to keep clear, and it's short.

**URScript emission** (`ocm_generator/emitters/urscript.py`): `movej`
standoff -> `movel` contact (at the capability's own `approach_speed_mm_s`,
converted to m/s) -> a `# TODO PLC handshake: <op>` placeholder -> `movel`
retract -> `movej` home. Positions in metres, rotations as axis-angle
radians (URScript's own `p[x,y,z,rx,ry,rz]` convention), real UR joint
names (named in a trailing comment; UR's own joint order otherwise, not
this package's namespaced ones). No leading `movej(home)` -- the script
assumes the robot starts at its own resting `joint_state`, which is
exactly the path this already collision-checked. No `set_tcp()` either --
every `movel` targets the FLANGE, the same frame IK solved reachability
against; the bit lands correctly as a direct consequence of the flange
being placed correctly, since sd50 is bolted on at a fixed, known,
purely-translational offset.

## CLI

```
pip install -e ../ocm-core -e ../ocm-resolve -e ".[test,tesseract]"
pytest

# drop ",tesseract" above to skip the --collision/plan tests and run
# without installing Tesseract at all -- everything else still works,
# including `ocm scene` itself.

# either of these work -- the console script needs Scripts/ on PATH,
# `python -m` doesn't:
ocm validate modules/com.accelsolutions.screwdriver.sd50/module.yaml
python -m ocm_generator resolve cells/bracket-asm-01/cell.yaml --modules modules
python -m ocm_generator scene cells/bracket-asm-01/cell.yaml --modules modules --view /tmp/cell.html
python -m ocm_generator scene cells/bracket-asm-01/cell.yaml --modules modules --collision
python -m ocm_generator plan  cells/bracket-asm-01/cell.yaml --modules modules --emit-urscript /tmp/out.script
```

Four subcommands, one per stage: `validate` (a module manifest against the
schema), `resolve` (a cell against a module search path), `scene` (resolve +
compose the scene), `plan` (plan the first `drive_screw` step's motion and
emit URScript -- see the planner/emitters section above). Each prints every
collected violation (or, for `plan`, its one refusal) on failure, matching
the libraries underneath -- see `ocm_generator/cli.py`.

`scene` takes three optional actions, any combination at once:

- `--dump-urdf FILE.urdf` -- the composed URDF as a plain file, e.g. to
  cross-check in another URDF tool.
- `--collision [--collision-margin-mm MM]` -- a real Tesseract discrete
  collision check (needs the `tesseract` extra). Exits nonzero on any real
  contact; see the "Workspace containment"/`--collision` sections above
  for exactly what does and doesn't count as one.
- `--view FILE.html` -- a single self-contained HTML file: three.js loaded
  from a CDN via an import map, no build step, no npm, no server. Open it
  by double-clicking. It's a **debug viewer**, not the product viewer
  (`ocm-viewer/`'s own R3F + GLB pipeline, per ADR-0007) -- geometry is
  walked straight out of the composed URDF and drawn as box/cylinder/sphere
  primitives (see `ocm_generator/scene/viewer.py`); links whose only
  collision geometry is a mesh (currently just the vendored UR5e) get a
  small translucent placeholder marker instead of their real shape, since
  this tool deliberately doesn't add a mesh/URDF-loader JS dependency.
  Distinct color per module instance, with a legend; orbit controls; a
  ground grid at z=0; axes at the world origin; and a label at every
  `mount.on` attachment point and every module's declared `frames.tcp`
  (e.g. `bracket-asm-01` gets a "robot1__flange (mount for sd1)" marker and
  a "sd1 TCP" marker, 186.5 mm apart -- exactly `sd50`'s declared
  `frames.tcp` z-offset).

The transform math the viewer (and eventually the planner) relies on --
composing URDF's fixed-axis roll-pitch-yaw `<origin>`s along a joint
chain -- lives on its own in `ocm_generator/scene/transforms.py`, unit
tested independently of URDF parsing or Tesseract in
`tests/test_transforms.py`.
