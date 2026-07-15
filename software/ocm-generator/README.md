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
python -m ocm_generator scene cells/bracket-asm-01/cell.yaml --modules modules --out /tmp/cell.urdf
```

Three subcommands, one per stage: `validate` (a module manifest against the
schema), `resolve` (a cell against a module search path), `scene` (resolve +
build the Tesseract environment, optionally writing the combined URDF for
inspection). Each prints every collected violation on failure, matching the
libraries underneath -- see `ocm_generator/cli.py`.
