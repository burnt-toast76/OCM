# ADR-0014 — Components are transcribed; modules are designed

**Status:** Accepted

## Context

Cold-testing the agent authoring surface exposed two coupled problems:

1. The agent fabricated plausible values (purge bounds copied from another module, invented
   needle orientation, schema-coerced nominal current) because datasheets don't answer
   everything a *module* manifest asks — and the manifest asks design questions.
2. What a datasheet describes is not a module. It is a **component** — an ejector, an IO
   block, a valve island. A real module is frequently an **assembly** of several.

## Decision

Two artifact types, two authoring rules:

| | Component | Module |
|---|---|---|
| Is | A purchasable part: catalog facts | An assembly: components + judgment |
| Contains | electrical, pneumatic, signals, geometry, mass, intrinsic hazards, datasheet ref | mount, frames/TCP, capabilities, PackML, safety (PL/guarding/safe_state), process, `components:` list |
| Authored by | **AI or human, by transcription. ZERO assumption.** | Human, or agent with human approval — this is design |
| Lives in | `components/<id>/component.yaml` | `modules/<id>/module.yaml` (unchanged) |

**The zero-assumption rule (components):** a value appears in a component definition only if
the source document states it. Units are never converted — every value is recorded in the
exact unit the source prints, verbatim (`bar`, `psi`, `VDC`); conversion is a downstream-code
concern, not a transcription one. **Choosing within a stated range is design** — the component
records the range (`pressure_min`/`pressure_max` = `4`/`6`, `pressure_units: bar`); a module
picks the operating point. Anything the datasheet doesn't answer is OMITTED. Incomplete
components remain drafts; the validation refusals ARE the handoff list of what a human must
supply. No "ASSUMED:" markers — omission, not annotation.

*(Amended after initial acceptance: the rule originally read "unit conversion and
restatement are transcription" — reversed once real datasheet extraction showed converting
introduces its own assumptions, e.g. a rounding or reference-temperature choice. Restatement
alone is still fine; conversion is not.)*

**Modules may reference components** via an optional `components:` list (refdes + id@rev).
Module-boundary signals may declare provenance (`source: VG1.part_present`). Aggregations —
power budget, air consumption, the purchasable BOM — derive from the list.

**A module with no components list stays valid.** Some purchased devices genuinely are whole
modules (a smart benchtop dispenser with its own fieldbus and behavior). No forced migration;
the flat form is the degenerate single-component case.

## Why this dissolves the fabrication problem

Every fabrication observed in testing was the agent doing design inside a transcription
task: the schema demanded a TCP, capabilities, a nominal current — questions a datasheet
doesn't answer. Component definitions ask only datasheet questions, so transcription can be
honest. Design questions move to the module layer, where a human is in the loop by policy.

## Consequences

- New `components/` registry + component schema (spec/10). API grows
  `create_component_draft` / `update_component` / `validate_component` / `publish_component`
  mirroring the module verbs; the module verbs gain component referencing.
- The agent-facing steering changes from "mark assumptions" to "omit; leave the draft
  incomplete; report the refusals as the human's completion list."
- BOM generation and per-module power/air budgets become derivable — this is also the kit
  tier's parts list (ADR-0011 business model).
- Component reuse across modules is the point: one tested IO-Link master definition serves
  every module that carries one. Pairs with ADR-0009's tested-hardware lists.
