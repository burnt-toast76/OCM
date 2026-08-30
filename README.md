# OCM — Open Cell Module

**OCM (Open Cell Module) is an open standard: an assembly cell described as
machine-readable manifests — component, module, cell.**
**Cellwright** is Accel Solutions' implementation of the standard — the software that
reads those manifests and generates what runs the cell.

---

## The thesis, in one paragraph

Everything needed to build an assembly cell already exists — it just isn't anywhere
a program can read it. The screwdriver's torque curve is in a PDF. Its approach
vector is in the engineer's head. Its I/O map is in the PLC project. Its TCP is in
the robot pendant. Four places, four transcriptions, four chances to be wrong, and
400 hours per cell.

**OCM writes that knowledge down in a form software can read, in three layers.**
A **component** is transcribed from its datasheet — what the part is. A **module**
declares which components it contains, how they are wired to each other, and what
the assembly does. A **cell** declares which modules are in it and how they connect.
Each layer is a manifest. Each layer is validated. Each layer is the only place its
facts are written.

**An AI agent is a first-class reader of all three**, through the same API the GUI
uses. When the manifests are incomplete, the agent gets a refusal — not a plausible
guess. **Cellwright** generates everything downstream from those manifests: the
collision scene, the robot program, the PLC sequence, the tag list, the cycle-time
estimate.

If that's true, the cell takes 40 hours.

See [ROADMAP.md](ROADMAP.md) — what to build to prove it, in what order.

## Repo map

The three registries are the three **context layers** — component, module, cell —
not just three folders (ADR-0017). `software/` is **Cellwright**.

| Directory | Contains | License |
|---|---|---|
| [`spec/`](spec/) | **The OCM standard.** Manifest schema, mechanical/electrical/fieldbus interfaces, PackML profile. Independently implementable. | CC BY-SA 4.0 |
| [`components/`](components/) | **Context layer 1 — component.** What each part is, transcribed from its datasheet. One directory per part. | CC BY-SA 4.0 |
| [`modules/`](modules/) | **Context layer 2 — module.** What an assembly does, and how its components are wired to each other. One directory per module. | CC BY-SA 4.0 |
| [`cells/`](cells/) | **Context layer 3 — cell.** Which modules are present and how they connect — including the cells we build for paying customers. | CC BY-SA 4.0 |
| [`software/`](software/) | **Cellwright** — Accel Solutions' implementation of the standard: resolver, generator, API, refusal engine, composer. | AGPL-3.0 |
| [`hardware/`](hardware/) | Frame, datum plate, gantry, panel, module designs. DXF/STEP/CAD. | CERN-OHL-S v2 |
| [`reference/`](reference/) | Tested BOMs, verified drive list, **measured** frame and sync data. | CC BY-SA 4.0 |
| [`docs/decisions/`](docs/decisions/) | **Architecture Decision Records.** Why every choice was made. Read these first. | CC BY-SA 4.0 |
| [`Fusion360 Designs/`](Fusion360 Designs/) | **Architecture Decision Records.** Why every choice was made. Read these first. | CERN-OHL-S v2 |

⚠️ **Licensing is structural, not decorative.** Three licenses, three directories, three
`LICENSE` files. Putting a CAD file in `software/` or a Python module in `hardware/` makes
the licensing ambiguous. See [LICENSING.md](LICENSING.md) — and note the hard constraint
that we must use **GPLv3, never GPLv2**.

## Start here

1. [`docs/decisions/`](docs/decisions/) — every architectural choice, with the reasoning
2. [`spec/02-mechanical-interface.md`](spec/02-mechanical-interface.md) — the bolt grid *(FREEZE THIS FIRST)*
3. [`spec/schema/ocm-module-1.0.schema.json`](spec/schema/ocm-module-1.0.schema.json) — the manifest schema
4. [`modules/`](modules/) — worked examples: a screwdriver and a dispense head
5. [`ROADMAP.md`](ROADMAP.md) — what to build, in what order, and why *not* the frame first

## Status

**Pre-alpha — but the software chain is real, and none of it has touched hardware.**
As of this commit:

- **Manifests validate.** `ocm-core` loads and validates component, module, and cell
  manifests against the schema.
- **The generator exists** (`ocm-resolve` + `ocm-api` + `ocm-generator`): a resolved
  cell builds a Tesseract collision scene from URDF fragments, plans a
  collision-checked joint-space motion (IK — needs the Tesseract extra), and emits a
  URScript robot program, a cycle-time estimate, and an animation. A generated PackML
  coordinator runs the spec/08 handshake — against **simulated** I/O. The refusal
  engine (ADR-0012, ADR-0016) is the one validation surface.
- **Not built yet:** the PLCopen-XML / PLC-sequence emitter.
- **The web composer** (`ocm-composer`) is a working React/TypeScript app under active
  development — cell composition and module wiring.
- **Empty placeholders:** `ocm-agent`, `ocm-runtime`, `ocm-viewer` are `.gitkeep`
  stubs. The runtime handshake currently lives, simulated, inside the generator's
  coordinator.
- **Registries:** 2 components, 8 modules, 1 cell (`bracket-asm-01`).
- **No hardware has been built.** Every `hardware/` subtree is a placeholder, and
  nothing here has run on a physical machine — the coordinator's I/O is simulated.

We will say so plainly until it isn't true.
