# ocm-generator

**This is the thesis.** See [ROADMAP Step 1](../../ROADMAP.md).

```
cell.yaml + plan.yaml
  -> scene/    URDF fragments -> Tesseract environment   <- built
  -> planner/  Tesseract + Ruckig
  -> emitters/ URScript, PLCopen XML
  -> validate/ THE REFUSAL LOGIC
```

**The most valuable output of this tool is "no."**

## scene/ (`ocm_generator.scene`)

Takes a `ResolvedCell` (from `ocm-resolve`) and a module search path and
compiles it into a real `tesseract_robotics.tesseract_environment.Environment`
-- ADR-0007's "cell.yaml compiles directly into a Tesseract scene graph,"
built. Every instance's `mechanical.geometry.urdf_fragment` gets namespaced
and spliced into one combined URDF, attached either to `world` (mount.pose,
converted from the schema's mm/deg to URDF's m/rad) or, for `mount.on`
chains (e.g. `sd1` on `robot1.flange`), kinematically parented to the
target's own named link with an identity offset -- not a computed
world-frame pose, since a tool's position on a moving robot depends on live
joint state.

`build_scene(resolved, modules_root)` raises `SceneBuildError` -- carrying
every violation found, not just the first -- if any urdf_fragment is
missing/malformed or any `mount.on` names an attachment link that doesn't
exist. It builds cleanly end-to-end on the real `bracket-asm-01` cell: every
module it references has real collision geometry now -- six box primitives
derived from each manifest's own `footprint_mm`/frame offsets, and a real
vendored-and-flattened UR5e (see `modules/com.universal-robots.ur5e/NOTICE.md`).
See `tests/test_scene_build_real_bracket_cell.py`.

## CLI

```
pip install -e ../ocm-core -e ../ocm-resolve -e ".[test]"
pytest

# either of these work -- the console script needs Scripts/ on PATH,
# `python -m` doesn't:
ocm validate modules/com.accelsolutions.screwdriver.sd50/module.yaml
python -m ocm_generator resolve cells/bracket-asm-01/cell.yaml --modules modules
python -m ocm_generator scene cells/bracket-asm-01/cell.yaml --modules modules --view /tmp/cell.html
```

Three subcommands, one per stage: `validate` (a module manifest against the
schema), `resolve` (a cell against a module search path), `scene` (resolve +
build the Tesseract environment). Each prints every collected violation on
failure, matching the libraries underneath -- see `ocm_generator/cli.py`.

`scene` takes two optional outputs, either or both at once:

- `--dump-urdf FILE.urdf` -- the composed URDF as a plain file, e.g. to
  cross-check in another URDF tool.
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
