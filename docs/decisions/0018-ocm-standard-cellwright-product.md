# ADR-0018: OCM is the standard, Cellwright is the product

## Status
Accepted

## Context

One name has been carrying two jobs: the open interchange format that anyone may
implement, and Accel Solutions' implementation of it. That conflation makes the
open-standard claim unfalsifiable — if the standard and the only implementation
share a name, "independently implementable" is a promise with nothing behind it.

The license structure already draws the line. `spec/` and the registries are
CC BY-SA; `software/` is AGPL-3.0. The naming should follow the boundary that
licensing already enforces.

## Decision

**OCM** is the standard: the manifest schemas, the mechanical, electrical, and
fieldbus interfaces, the PackML profile, and the component/module/cell registries.
Independently implementable by anyone.

**Cellwright** is Accel Solutions' implementation: everything in `software/` —
the resolver, generator, API, refusal engine, composer, agent, runtime, viewer.

A third party may write their own generator against OCM manifests. That is the
point of publishing the spec separately, and it is the test of whether the
standard is real.

## Consequences

- Python package names remain `ocm-*`. They implement the OCM standard;
  Cellwright is the product that bundles them. Renaming would touch every import
  for a distinction invisible outside packaging metadata. Revisit only if a
  second independent implementation appears.
- The repository stays `OCM`. The standard holds the durable name.
- Documentation must not use the names interchangeably. Manifests are OCM.
  Generation, validation, and refusal are Cellwright.
- Marketing and customer-facing material leads with Cellwright. Specification
  and registry material leads with OCM.

## Related
ADR-0001 (licensing), ADR-0012 (API before pixels), ADR-0017 (context is layered)
