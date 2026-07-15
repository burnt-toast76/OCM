# ocm-resolve

AGPL-3.0. See ../../LICENSING.md.

Second stage of the generator pipeline (see [ROADMAP](../../ROADMAP.md) Step 1).
`ocm-core` loads and validates one manifest at a time; `ocm-resolve` takes a
`Cell` (from `ocm_core.load_cell`) and a module search path and produces a
`ResolvedCell` -- every module instance loaded, mount chains followed, and
the plan cross-checked against the resolved modules' declared capabilities
and parameter bounds. It does not touch geometry, collision, or Tesseract:
that's `ocm-generator`, once a cell resolves cleanly here.

- `resolve_cell(cell, search_path)` -- looks up every module a cell
  references as `<search_path>/<id>/module.yaml`, checks every plan step's
  `(module, op)` against the resolved module's capabilities, checks every
  plan param against the capability's declared `min`/`max`/`enum`, and
  resolves `mount.on` chains (e.g. `sd1` mounted `on: robot1.flange`).
  Raises `CellResolutionError` -- carrying *every* violation found, not just
  the first -- if any of that fails.

## Usage

```python
from ocm_core import load_cell
from ocm_resolve import resolve_cell

cell = load_cell("cells/bracket-asm-01/cell.yaml")
resolved = resolve_cell(cell, "modules")

sd1 = resolved.instance("sd1")
print(sd1.module.id)        # com.accelsolutions.screwdriver.sd50
print(sd1.mounted_on.name)  # robot1
```

## Tests

This is a sibling package to `ocm-core`, not published to an index --
install both editable from the same venv:

```
pip install -e ../ocm-core -e ".[test]"
pytest
```
