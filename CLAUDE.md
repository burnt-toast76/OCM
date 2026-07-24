# Notes for Claude

**Read `docs/decisions/` before proposing changes.** Most "obvious" alternatives were
considered and rejected for non-obvious reasons. The ADRs record the *context*, not just the
conclusion — if the context changes, the decision should be revisited, but don't relitigate it
blind.

## Things that look like good ideas and are not

- **LinuxCNC / Machinekit for gantry motion** — GPLv2. Breaks the Apache-2.0 planning chain.
  Use Ruckig (MIT). See ADR-0001, ADR-0007.
- **IgH EtherCAT Master** — GPLv2. Same trap. Use SOEM 2.0 (GPLv3).
- **RoboDK** — good tool, but a proprietary dependency poisons an open platform. See ADR-0007.
- **A welded frame** — kills the DIY and kit tiers. Bolted tab-and-slot. See ADR-0005.
- **Central I/O panel** — breaks plug-and-produce. I/O lives on the module. See ADR-0003.
- **Building the frame first** — the frame is the part we're least likely to get wrong, so it
  carries no information. The generator comes first. See ADR-0010.

## Current state

Pre-alpha. Schema validates; generator does not exist; no hardware built.
Next: freeze the bolt grid (ADR-0011, still open), then build the generator (ROADMAP step 1).

## Conventions

- Licensing is enforced by directory. A CAD file in `software/` or a Python module in
  `hardware/` makes its license ambiguous. See LICENSING.md.
- Module manifests must validate against `spec/schema/ocm-module-1.0.schema.json`.
- Claims in `reference/` are **measured**, not from datasheets. Keep it that way.

Module authoring goes through the ocm MCP tools (create_module_draft → update_module → generate_geometry_stub → validate_module → publish_module) — never by writing module files directly. Storage location is derived from the module id; geometry is generated, never declared as paths to files that don't exist.

## Authoring from datasheets (ADR-0014)

A datasheet describes a COMPONENT. Author it as one (components/ registry), by
TRANSCRIPTION ONLY: a value appears only if the source states it. Never convert units --
record every value in the exact unit the source prints, verbatim ("bar", "inH2O", "VDC");
conversion happens downstream in code, not here. Choosing within a stated range is design --
record the range, do not pick. Anything unanswered is OMITTED, never estimated, never
copied from other definitions. Leave the draft incomplete and report the validation
refusals as the list of what the human must supply.

This applies just as much to a connector's pinout (`pin`/`function`/`wire_color`), a
pneumatic port (`port` label/`thread`/`function` -- each independently optional; a
sensor's process-pressure tap has no correct `function` at all, so leave it out), and a
comms connector (`ref`/`type`/`protocol`/`role`, e.g. an EtherCAT IN/OUT pair) as to any
other field. Ask for all of them. A component whose datasheet states none of these stays
that way -- absence is the correct, honest answer, not a gap to fill in from a similar part.

MODULES are assemblies and design work: TCP placement, capabilities, PackML, safety.
Do not author or modify modules from a datasheet alone; propose, and let the human
decide. Never publish an incomplete definition.
