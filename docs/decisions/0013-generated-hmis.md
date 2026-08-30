# ADR-0013 — Operator and engineer HMIs are generated from manifests

**Status:** Accepted (direction locked; build after the cell composer, ADR-0012). ADR-0024
settles the write-authority question that had left engineer-HMI actuation ambiguous: manual
ops and jog are *commands* (available in MANUAL), distinct from manifest edits — so this ADR's
engineer HMI is unblocked and its scope stands.

## Context

Every integration job hand-builds two interfaces: an operator screen (run/stop/faults) and
an engineering screen (test, jog, parameters). It is a major cost line on every quote, it is
rebuilt per machine, and it drifts from the actual I/O the moment someone edits one without
the other.

## Decision

**Nobody draws screens.** Both HMIs are generated from the cell's resolved manifests — the
same source of truth as the robot program, the coordinator, and the tag list. Add a module
to `cell.yaml`, and its faceplates appear.

The manifest already contains everything the screens need:

| Screen element | Manifest source |
|---|---|
| Cell state, start/stop/hold, andon | PackML roles (`packml_cmd`/`packml_state`, ADR-0004) |
| Fault display, root-caused per channel | `fault_code` + per-channel diagnostics (ADR-0003) |
| Engineer: execute any op with guardrails | `capabilities` — typed, bounded parameters; **the manifest IS the form definition** |
| Interlock explanations ("why won't it start") | `preconditions`, rendered live against signal state |
| Maintenance due list | `maintenance.wear_items` intervals vs cycle counts |
| Traceability (torque/angle/volume per part) | `results` + the coordinator's JSON log |

## The two audiences

- **Operator HMI:** PackML state, start/stop, active fault in plain language, part count,
  andon. Deliberately sparse. Touch targets sized for gloves.
- **Engineer HMI:** everything above plus per-module faceplates — live signals, manual op
  execution (parameters constrained to manifest bounds; the same refusal engine gates a
  hand-typed torque), joint jog, traceability queries.

**Manual op execution is still gated by preconditions.** An engineer manually firing
`drive_screw` with no screw present is refused by the same rule that stops the robot
(spec/08). Engineering mode relaxes *sequencing*, never *interlocks*. Safety remains
hardwired and outside all of this (spec/06).

## Consequences

- HMIs are clients of `ocm-api` (ADR-0012) plus a live signal stream (WebSocket over the
  coordinator's SignalBus). No screen talks to hardware directly.
- A custom user-defined module gets a usable faceplate for free the moment its manifest
  validates. This is the plug-and-produce promise extended to the glass.
- Per-cell branding/layout tweaks are a config layer on top of generation, never hand-edited
  generated output (or they'd be destroyed on regeneration — same rule as all generated
  artifacts).
- Not started until the cell composer ships. This ADR exists so the direction survives
  scope pressure, not to authorize work now.
