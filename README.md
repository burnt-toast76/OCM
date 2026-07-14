# OCM — Open Cell Module

**An open-source modular assembly automation platform.**
Machine base, control architecture, motion, and a generator that turns a declarative
cell description into a working robot program and PLC sequence — with no human
hand-writing waypoints or interlocks.

Build it yourself from the files. Buy a kit. Or have us build it complete.

---

## The thesis, in one paragraph

An assembly cell is bespoke because every module is opaque. The screwdriver knows its
torque curve; the engineer knows its approach vector; the PLC knows its I/O map; the robot
program knows its TCP — and none of that is written anywhere a *tool* can read. So a human
retypes it into four places and the cell takes 400 hours.

**OCM says the module ships with a manifest.** The manifest is the single source of truth.
Everything downstream — the collision scene, the robot program, the PLC sequence, the tag
list, the cycle-time estimate — is generated from it.

If that's true, the cell takes 40 hours. If it isn't, this project is just a nice open frame
design. **Proving it is job #1, and it's provable on a laptop.** See [ROADMAP.md](ROADMAP.md).

## Repo map

| Directory | Contains | License |
|---|---|---|
| [`spec/`](spec/) | **The standard.** Manifest schema, mechanical/electrical/fieldbus interfaces, PackML profile. Independently implementable. | CC BY-SA 4.0 |
| [`software/`](software/) | Generator, runtime, agent, viewer. | AGPL-3.0 |
| [`hardware/`](hardware/) | Frame, datum plate, gantry, panel, module designs. DXF/STEP/CAD. | CERN-OHL-S v2 |
| [`modules/`](modules/) | The manifest registry. One directory per module. | CC BY-SA 4.0 |
| [`cells/`](cells/) | Real cell definitions, including the ones we build for paying customers. | CC BY-SA 4.0 |
| [`reference/`](reference/) | Tested BOMs, verified drive list, **measured** frame and sync data. | CC BY-SA 4.0 |
| [`docs/decisions/`](docs/decisions/) | **Architecture Decision Records.** Why every choice was made. Read these first. | CC BY-SA 4.0 |

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

**Pre-alpha.** The schema validates. The generator does not exist yet. No hardware has been
built. Nothing here has been proven on a machine.

We will say so plainly until it isn't true.
