# ocm-core

AGPL-3.0. See ../../LICENSING.md.

Manifest load + validate — the first link in the generator chain (see
[ROADMAP](../../ROADMAP.md) Step 1). `scene/`, `planner/`, and `emitters/`
are meant to consume a typed `Module` or `Cell` from here instead of walking
raw YAML.

- `load_module(path)` — parse a `module.yaml`, validate it against
  `spec/schema/ocm-module-1.0.schema.json`, return a typed `Module`. Raises
  `ManifestValidationError` (carrying every violation, not just the first)
  if it doesn't conform.
- `load_cell(path)` — parse a `cell.yaml` composition into a typed `Cell`.
  There is no published schema for the cell shape yet — ADR-0011's mount
  grid is still open, and everything hangs off it — so this does structural
  checks instead of full JSON Schema validation. `Cell.part` and `Cell.plan`
  are kept as raw dicts: that DSL belongs to the generator's planner, which
  this package does not touch.

## Usage

```python
from ocm_core import load_cell, load_module

sd50 = load_module("modules/com.accelsolutions.screwdriver.sd50/module.yaml")
drive = sd50.capability("drive_screw")
print(drive.parameters["torque_nm"].max)  # 5.0

cell = load_cell("cells/bracket-asm-01/cell.yaml")
print(cell.module("sd1").mount.on)  # "robot1.flange"
```

## Tests

```
pip install -e ".[test]"
pytest
```
