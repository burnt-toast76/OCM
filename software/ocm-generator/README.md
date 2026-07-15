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
exist. It currently refuses on the real `bracket-asm-01` cell: no module in
`modules/` has real URDF/mesh assets checked in yet, only placeholder
paths. See `tests/test_scene_build_real_bracket_cell.py`.

```
pip install -e ../ocm-core -e ../ocm-resolve -e ".[test]"
pytest
```
