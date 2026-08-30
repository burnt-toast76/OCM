# OCM Spec — Overview

See the [root README](../README.md) for the thesis.

## Manifests are YAML 1.2 (core schema). This is normative, not advisory.

Every OCM manifest — component, module, cell — is parsed under **YAML 1.2 core schema**
resolution. Only `true`/`false` (and their Title/UPPER case forms) are booleans; the YAML 1.1
legacy tokens `on`, `off`, `yes`, `no`, `y`, `n` are **plain strings**, as keys and as values.

This is load-bearing, not pedantry. A cell manifest writes `mount: {on: robot1.flange}`. A
parser using YAML 1.1 resolution — which is what stock PyYAML's `safe_load` does — resolves
that bare `on` key to boolean `True`, and the mount **silently vanishes**: no error, no
warning, an instance floating unmounted. An implementation that parses OCM manifests with
1.1-era resolution is non-conformant and will mis-read valid manifests without noticing.

Implementers: use a YAML 1.2 parser, or restrict your 1.1 parser's implicit boolean resolution
to `true`/`false` (Cellwright's `ocm-core` does exactly this — see
`ocm_core/loader.py::_Loader`). The repo carries a test asserting its own manifests round-trip
identically under 1.2 resolution and demonstrably would not under 1.1, so the hazard stays
visible.

## Three layers, kept strictly separate

| Layer | File | Authored by | Analogy |
|---|---|---|---|
| **Definition** | `modules/<id>/module.yaml` | module designer | a class |
| **Instance** | `cells/<id>/cell.yaml` | cell integrator | an object |
| **Plan** | `cells/<id>/plan.yaml` | process engineer *or agent* | a program |

Keeping these separate is what makes a module reusable. A screwdriver definition never
mentions a cell; a cell never mentions a part; a plan never mentions an I/O address.

## The four things every module MUST declare

1. **Geometry** — collision mesh + named frames + **`urdf_fragment`**. Feeds the planner.
2. **Capabilities** — verbs, with typed parameters, pre/postconditions, results. Feeds the agent.
3. **Signals** — the I/O map with *semantic* names. Feeds the PLC codegen.
4. **State machine** — PackML. Feeds the cell coordinator.

## What the generator produces

1. Tesseract scene ← union of every module's `urdf_fragment`, at its mount pose
2. Robot program ← planned moves honoring each op's approach/clearance/hold_still
3. PLC program ← PackML coordinator + interlocks derived from `preconditions`
4. Tag list ← union of all `signals`
5. Cycle time estimate ← `nominal_duration_s` + planned motion
6. Consumable rates ← from `consumes`
7. **A refusal** ← if torque exceeds the tool's limit, or the safety circuit doesn't meet the
   union of declared PL requirements, the build **FAILS**.

> **The generator's most valuable output is "no."**
