# Spec changelog

## v1.1 (additive — every valid 1.0 manifest remains valid)

**Custom protocols.** `comms.protocol` accepts `x-<name>` (e.g. `x-gocator-gsdk`,
`x-my-serial`) alongside the enumerated transports. Authoring, resolve, scene, and plan all
work with custom protocols (they never touch transports); the runtime coordinator refuses to
go live unless a driver is registered for the protocol, naming it. Per ADR-0012.

**Composite types.** Signals, capability parameters, and results may now be:
- `pose6d` — a 6-DOF pose. **`frame` is REQUIRED** (schema-enforced): a pose without a
  declared reference frame is a latent bug, so it is not representable.
- `vec3` — three reals.
- `struct` — general composite with a `fields:` name→scalar map, wire layout in declaration
  order.

Motivating case: `com.lmi.gocator.2350`'s `locate_part` now returns
`part_pose: {type: pose6d, frame: nest1.part_datum}` — the thing the plan's `binds:` actually
consumes — plus a `confidence` result the coordinator can gate on, replacing six unrelated
scalars and a comment.

Manifests using v1.1 features declare `ocm_version: "1.1"`.
