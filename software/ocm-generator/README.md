# ocm-generator

**This is the thesis.** See [ROADMAP Step 1](../../ROADMAP.md).

```
cell.yaml + plan.yaml
  -> scene/        URDF fragments -> Tesseract environment          <- built
  -> planner/      Tesseract IK + collision-checked joint-space     <- built (full fastening for_each)
  -> emitters/     URScript (spec/08 handshake), PLCopen XML        <- built (URScript only)
  -> coordinator/  spec/08 handshake, generated per resolved cell   <- built (asyncio, simulated I/O)
  -> validate/     THE REFUSAL LOGIC
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
above): plans the motion for the *entire* fastening `for_each` in a cell's
`plan` -- every item, in listed order (no path/visit-order optimization --
v0 is honest about that), walking `sequence`/`on_fail` nesting but never
descending into an `on_fail` branch itself, since that's PLC-side
recovery, not the forward path this builds motion for -- and emits it as
one continuous URScript program:

```
home -> standoff_1 -> contact_1 -> retract_1
      -> standoff_2 -> contact_2 -> retract_2 -> ... -> retract_N -> home
```

Transits between holes go directly `retract_i -> standoff_{i+1}`; the
robot only returns home once, at the very end.

**Where the part is.** `locate_part`'s actual vision result isn't
modeled -- like `.scene.kinematics`, this isn't a live simulator. The
plan's own `clamp` step names which fixture the part is seated in; that
fixture's manifest `part_datum` frame ("where a correctly-seated part's
own origin lands" -- see `com.accelsolutions.fixture.pneumatic-nest`'s own
note) gives the nominal part pose directly, which is exactly what the
vision system exists to verify, not something this bypasses.

**Standoff/contact/retract poses** (`ocm_generator/planner/poses.py`) come
from each item's `cell.part.features.*` entry (`xyz_mm`/`normal`, in the
fixture's `part_datum` frame, `${item}` substituted into `at` per
for_each item) and the capability's own `motion` block
(`approach_vec`/`approach_mm`/`approach_speed_mm_s`/`retract_vec`/
`retract_mm`) -- computed directly in the tool's FLANGE frame (not its TCP)
since IK needs the flange pose and sd50's `tcp` frame is a purely
translational offset from it.

**Reachability and IK branch consistency** (`ocm_generator/planner/ik.py`):
every pose in the chain -- not just each hole's standoff, but its contact
and retract too, even though those are emitted as `movel`s the controller
solves its own IK for online -- is solved with `tesseract_kinematics`'
real analytic UR inverse kinematics (`URInvKinFactory`, `model: UR5e`)
against the composed scene's own URDF, and selected as the solution
closest (by joint-space distance) to the IMMEDIATELY PRECEDING
configuration in the sequence -- never re-seeded from `home`. The UR
solver returns up to 8 valid solutions ("branches") for almost any
reachable pose; chaining without regard for what came before can pick
solutions that are each individually valid but require an enormous,
physically absurd swing to get from one to the next (a "branch flip"). An
unreachable pose is refused by name (`PoseUnreachableError`, e.g.
`"standoff_2"`) -- not retried, not routed around. See
`tests/test_planner.py`'s own branch-consistency test, which pins this
down by asserting no consecutive pair across a real 3-hole sequence swings
any single joint by more than ~120 degrees (a real branch flip shows up as
~180+).

**Every segment's path** (`ocm_generator/planner/path.py`): a straight
line in JOINT SPACE (not Cartesian) between each consecutive pair in the
chain above -- not just `home -> standoff_1`, but `standoff_i ->
contact_i`, `contact_i -> retract_i`, and every inter-hole
`retract_i -> standoff_{i+1}` transit too (short, but not skipped) --
sampled at `--path-samples` (default 50) states per segment and
collision-checked at each one with the same `check_collisions`
`--collision` uses. A straight line that collides is refused
(`PathCollisionError`, naming the SEGMENT, e.g. `"retract_1 ->
standoff_2"`, the colliding instance pair, and how far along it happened),
even when both endpoints are individually clear -- see
`tests/test_planner.py`'s test against the real, committed
`bracket-asm-01` cell's own three holes (camera aside; see below) and its
own synthetic obstacle fixture. **This is deliberately not path-planned or
optimized (no OMPL, no TrajOpt) -- refusing a colliding straight line is
correct v0 behavior**, matching this package's own thesis that "the most
valuable output of this tool is 'no.'"

*(Aside, found empirically while building this: the real, committed
`bracket-asm-01` cell's own `home -> standoff_1` swings the wrist through
`cam1`, the vision camera mounted directly over the workspace, for all
three of its holes -- despite home and each standoff being clean on their
own. `tests/test_planner.py` uses a camera-free variant of that same cell
so its tests are about what they're actually testing, not about
re-proving the camera finding on every run.)*

**`load_screw` overlap.** `load_screw` has no `motion` block -- sd50's own
manifest note: "the generator is free to overlap this with the robot's
move to the next hole." Its PLC-handshake placeholder (`# PLC handshake:
load_screw (overlaps following transit)`) is emitted immediately before
the transit `movej` that carries the robot to that hole's standoff -- for
hole 1, that's `home -> standoff_1`. It is not itself a numbered spec/08
sync point: its completion is observed indirectly, through drive_screw's
own `screw_present` precondition at the FOLLOWING standoff sync.

**`on_fail`** (e.g. `eject_screw`, `reject_part`) is PLC coordinator logic
(ADR-0004: PackML sequences modules, and abort/recovery routing is the
coordinator's job) -- noted as a comment, never emitted as robot motion. A
failed result (`result_ok == false`) still reaches the robot for real,
though: as `hs_abort`, same as any other abort.

**URScript emission** (`ocm_generator/emitters/urscript.py`) implements
[spec/08-robot-handshake.md](../../spec/08-robot-handshake.md)'s
step-counter protocol for real, over its `ur-rtde` binding -- not a
`# TODO` comment. Per hole: `movej` standoff -> a sync (announce arrival,
then block -- checking abort and incrementing the heartbeat every
iteration -- until the coordinator raises `hs_done_step` to meet it) ->
`movel` contact (at the capability's own `approach_speed_mm_s`) -> another
sync -> `movel` retract; one trailing `movej` home at the very end, not
one per hole. Step numbers are monotonic in plan order (one at each
standoff, one at each contact -- `.planner.poses.standoff_step_number`/
`contact_step_number`, the exact same functions `.coordinator` uses, so
the two generated programs can't drift on what step N means). The header
comment documents the full register map and states outright that every
pose is a FLANGE pose -- no `set_tcp()` is issued; the screwdriver's own
TCP offset is a fixed, known translation from the flange, so the bit
lands correctly as a direct consequence of the flange landing correctly.
Positions in metres, rotations as axis-angle radians (URScript's own
`p[x,y,z,rx,ry,rz]` convention), real UR joint names. No leading
`movej(home)` -- the script assumes the robot starts at its own resting
`joint_state`, which is exactly the path this already collision-checked.

**Cycle-time estimate** (`ocm_generator/planner/cycle_time.py` +
`ocm_generator/emitters/cycle_time.py`, printed by the CLI after planning
succeeds): a plain-text table, one row per motion segment and per
stationary op, in the order they actually happen. Motion rows are labeled
`ESTIMATE` -- `max(|joint delta|) / a stated default joint speed`
(1.0 rad/s; there's no jerk-limited trajectory generation yet, see
ADR-0007's Ruckig note), never to be mistaken for a real trajectory
generator's number. Op rows (`load_screw`/`drive_screw`) use each
capability's own declared `nominal_duration_s`, unmodified. The table
totals both a naive serial time (everything back to back) and the
overlapped time (each `load_screw` running concurrently with the transit
into its hole), and reports the difference as the overlap savings.

**`--view-animation`** (`ocm_generator/emitters/animation.py`): embeds the
planned motion into the same self-contained HTML viewer `ocm scene --view`
builds, and animates it. **Reuses the collision-check states -- never
recomputes or re-derives motion**: every animation frame is one of the
joint-angle samples `.planner.path.check_joint_segment` already
interpolated and ran a real discrete collision check against for this
exact plan (`PathSegment.frames`), run through the same forward
kinematics the static viewer uses to get link poses -- an animation frame
is therefore always a state that has already been proven collision-free.
`DATA.animation` is a flat list matching the printed cycle-time table's
own rows one-for-one, so a segment's caption and duration are the literal
numbers in that table:

- **motion** segments carry every checked frame for a real
  standoff/contact/retract/transit move.
- **dwell** segments -- `drive_screw` actually driving (1.8 s), a wait at
  standoff for `load_screw`'s own precondition -- carry exactly ONE held
  frame for their whole duration. The pause is visible on purpose: it's
  where spec/08's handshake actually lives (a standoff sync withholding
  `hs_done_step`, a contact sync running `drive_screw`'s own PackML
  cycle).

Only the robot and whatever's mounted on it (transitively -- `sd1` rides
`robot1`'s flange) gets a new pose per frame; every static module (base,
`nest1`, `feed1`, `cam1`, ...) is emitted once, exactly as `--view`
already does (reused directly, filtered). **No smoothing, no retiming --
linear playback of exactly the checked states, at a constant per-frame
timestep within each segment; jerk-limited timing arrives with Ruckig
later (ADR-0007).** The viewer adds play/pause, a scrub slider spanning
the whole sequence, 0.5&times;/1&times;/2&times; speed, and a caption
showing the current segment name and elapsed/total time (for a dwell:
`drive_screw @ hole_2 — waiting on PLC`).

Unlike the plain `--view` debug viewer (unchanged -- still loads three.js
from a CDN via an import map), `--view-animation`'s output vendors
three.js: the core library plus the OrbitControls/CSS2DRenderer addons
(MIT-licensed, see `ocm_generator/scene/vendor/three/NOTICE.md`) are
embedded as `data:` URIs directly in the page's own import map, so the
generated file has no runtime dependency on any external host at all --
truly self-contained, openable offline.

## coordinator/ (`ocm_generator.coordinator`)

The other side of spec/08's handshake: a generated Python (asyncio)
coordinator program that walks a resolved cell's fastening for_each
sequence in lockstep with the URScript `.emitters.urscript` emits for the
same plan -- not PLCopen yet (ROADMAP Step 1's `emitters/plcopen.py` is
still future work), but the same protocol logic that will eventually sit
behind it.

Every module's I/O -- the four handshake signals AND the ordinary
capability/process signals a precondition or a result reads -- goes
through one interface, `.signals.SignalBus`, so the real EtherCAT/SOEM
layer (ADR-0002) is a driver this v0 doesn't need yet, not a rewrite
later. `SimulatedSignalBus` is the only implementation so far: an
in-memory table, no transport, no timing.

**`.robot_link.RobotLink`** binds spec/08's four signals
(`hs_at_step`/`hs_done_step`/`hs_abort`/`hs_heartbeat`) to a robot
instance BY ROLE (`handshake_at_step`/`handshake_done_step`/
`handshake_abort`/`handshake_heartbeat` in that module's own
`comms.signals` block) -- see `com.universal-robots.ur5e`'s manifest for
the real binding (RTDE registers 0/0/1/1). Never a hardcoded register
number; a missing or ambiguous role binding is a startup-time refusal
(`HandshakeBindingError`), not a hang mid-cycle.

**`.program.Coordinator`** walks the same `find_fastening_plan` result
`.planner` uses (so both programs agree on the sequence and the step
numbering without sharing anything but that one function), and per hole:

- Fires `load_screw` (if the sequence has one) without waiting on it --
  mirroring exactly where the URScript places its own "overlaps following
  transit" comment.
- Waits for the robot's arrival at that hole's standoff sync, THEN
  withholds `hs_done_step` until `drive_screw`'s own declared
  `preconditions` (plain `signal == literal` expressions, `.packml`) hold
  against the tool module's live signals -- spec/08's "interlocks become
  motion gates" made real, not a comment.
- Waits for arrival at contact, runs `drive_screw`'s PackML
  start->Execute->Complete cycle against the module (simulated -- see
  `.packml`'s own module docstring on why its numeric encoding is this
  project's placeholder, not a spec: nothing in this repo pins one down
  yet), reads back `torque_achieved`/`angle_achieved`/`result_ok`, and
  appends a trace entry.
- A false `result_ok` raises `hs_abort` (the robot halts in place, per
  spec/08) and returns an aborted `CoordinatorResult` instead of writing
  `hs_done_step` -- `on_fail`'s `eject_screw`/`reject_part` routing is PLC
  logic this v0 doesn't implement yet, but the abort signal that would
  drive it is real.
- Watches `hs_heartbeat` in the background; static for more than 2s (spec/08's
  own threshold, `heartbeat_timeout_s`) while the walk should still be
  running raises `HeartbeatStaleError`.

Every hole's results are written to a JSON traceability log
(`write_trace_log`, or pass `trace_log_path=` to `Coordinator`).

**The loopback proof** (`tests/test_coordinator.py`) runs a real generated
`Coordinator` against two simulated peers on one shared bus:

- **`.urscript_sim.SimulatedRobot`** -- a stand-in for the physical UR
  controller. It PARSES an actual emitted URScript string for
  `write_output_integer_register(0, N)` / `while
  read_input_integer_register(0) < N: ...` and replays that exact
  sequence; it does not know the plan, the hole count, or the step
  numbering in advance. If the emitter's output shape changes, this
  adapts with it -- it is not a second, hand-maintained copy of the
  protocol the coordinator and the emitter already share.
- **`.simulated_module.SimulatedPackMLModule`** -- a stand-in for sd1's
  own EtherCAT firmware: watches for a start request and, after a short
  delay, produces whatever signals the requested op's manifest declares
  (`load_screw` sets `screw_present`; `drive_screw` clears it and reports
  torque/angle/`result_ok` -- the latter overridable per hole, which is
  how the abort test forces a specific failure).

The three tests this proves: the full 3-hole sequence completes
end-to-end (both generated programs, no shortcuts); the coordinator
provably withholds `hs_done_step` while `screw_present` is false --
proven by real elapsed wall-clock time, not just an internal counter --
and the robot genuinely blocks waiting for it; and a forced
`result_ok=false` on hole 2 raises `hs_abort`, the simulated robot halts
(`RobotAborted`), and hole 3 is never reached.

*(A real bug caught building this: the simulated module's own internal
`packml_cmd`/`packml_state` cycle was edge-based, and a stale
pre-`await`-captured "last command" value let a second request's edge go
undetected if the first request's own processing delay was long enough --
exactly the "missed edge" failure mode spec/08's REAL handshake is
deliberately level-based to avoid. Fixed by re-reading the command fresh
after the slow part, rather than trusting a snapshot taken before it.)*

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
python -m ocm_generator plan  cells/bracket-asm-01/cell.yaml --modules modules --emit-urscript /tmp/out.script --view-animation /tmp/anim.html
ocm fmt --check   # needs ocm-api installed too, see below
```

Five subcommands: `validate` (a module manifest against the schema),
`resolve` (a cell against a module search path), `scene` (resolve +
compose the scene), `plan` (plan the full fastening `for_each` sequence's
motion, emit URScript, optionally an animated HTML viewer, and print a
cycle-time estimate -- see the planner/emitters section above), and `fmt`
(canonicalize manifest YAML formatting, below). `validate`/`resolve`/
`scene`/`plan` each print every collected violation (or, for `plan`, its
one refusal) on failure, matching the libraries underneath -- see
`ocm_generator/cli.py`.

### `ocm fmt` -- canonicalize manifest formatting

```
pip install -e ../ocm-api  # in addition to ocm-core above -- fmt reuses
                            # ocm_api.workspace._new_yaml_rt directly, not
                            # a second copy of its indent config

ocm fmt                        # reformat ./modules ./components ./cells in place
ocm fmt path/to/module.yaml    # or specific files/directories
ocm fmt --check                # exit 1 and list anything not already canonical -- writes nothing
```

`ocm_api.workspace.write_yaml` (the GUI/agent write path) round-trips a
manifest through a ruamel `YAML(typ="rt")` instance configured with this
repo's own `sequence=2, offset=0` block-sequence indent. That config is
global to the YAML instance, not per-file -- so a manifest hand-authored
at a different indent (several of this repo's own were originally written
at `sequence=4, offset=2`) gets silently reformatted the moment anything
writes it back, even a genuine no-op save. `ocm fmt` does the same
round-trip deliberately and up front, so that reformat happens as its own
reviewable, formatting-only commit instead of hiding inside an unrelated
data change's diff. `--check` (no write) is what CI runs, so a
newly-hand-edited manifest can't merge un-canonical and cause that surprise
again.

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
