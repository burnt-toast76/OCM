# ADR-0017: Context is layered — component, module, cell

## Status
Accepted

## Context

ADR-0014 separated components from modules, on the grounds that a datasheet
describes a part and a manifest describes an assembly. ADR-0015 added module
connectivity — ports, nets, links. Both were solving local problems. Neither
stated the general principle, so the repo's shape (`components/`, `modules/`,
`cells/`) reads as filing convenience rather than architecture.

It is architecture. The three directories are three layers of context, each
answering a different question, each sourced differently, each validated
separately.

## Decision

Context is authored in three layers. A layer may reference the layer below it.
A layer never restates what the layer below already declares.

**Component — what the part is.**
Source: the manufacturer's datasheet. Authored by transcription only, under the
zero-assumption discipline of ADR-0014. Values appear in the units the source
prints. Gaps stay absent.

**Module — what the assembly does and how it is wired.**
Source: the integrator. Declares which components it contains, the nets and
links between them (ADR-0015), and the function the assembly performs. Component
facts are referenced, never copied.

**Cell — what modules are present and how they connect.**
Source: the integrator. Declares module placement and inter-module connectivity.
Module internals are referenced, never copied.

Each layer is a manifest validated by a single validation surface (ADR-0016).
Incompleteness at any layer surfaces as a refusal, which is the human's
completion list.

## Consequences

- A fact has exactly one home. Duplication across layers is a defect, not a
  convenience.
- An AI agent reading a cell can descend to any component fact without a human
  in the loop, because every layer is machine-readable and every gap is explicit.
- Adding a fourth layer (line? plant?) is possible but must follow the same rule:
  reference downward, never restate.
- The layering is a documentation commitment as much as a schema one. README and
  the registry READMEs name the layers, not just the directories.

## Related
ADR-0012 (one refusal engine), ADR-0014 (components vs modules),
ADR-0015 (module connectivity), ADR-0016 (one validation surface)
