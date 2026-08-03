# Spec changelog

## Refusal codes namespaced `OCM_` (ADR-0025 D4) — **breaking** for the API surface

Every refusal code is now prefixed `OCM_`. The 37 codes the engines emitted bare
(`SCHEMA_INVALID` → `OCM_SCHEMA_INVALID`, `PARAM_OUT_OF_BOUNDS` → `OCM_PARAM_OUT_OF_BOUNDS`, …)
were renamed everywhere they appear: `ocm-api`'s `Codes` and every emitted string, the
`ocm-composer` frontend that switches on them, tests, spec text, and the catalogue keys. This
is a breaking change to the API's refusal contract — a client matching on `"SCHEMA_INVALID"`
will no longer match. Nothing external consumes it yet (ADR-0012 scopes v1 as a single-user
local service), which is why the rename is cheap now and would not be later; it is filed as a
breaking change regardless, not a tidy-up. The catalogue (`spec/schema/ocm-refusals-1.0.yaml`)
is now single-namespace.

## Conditions belong to modules (ADR-0023) — **breaking** for capabilities

The plan is verbs; everything a step must wait for is declared on the capability whose module
owns the sensing signal. Three additions to the capability schema
(`spec/schema/ocm-module-1.0.schema.json`):

- **`timeout_s`** (number, > 0) and **`on_timeout`** (`hold` | `abort`) are now **REQUIRED on
  every capability** — how long before the operation is wrong, and how to dispose the part when
  it is. This is a breaking change: a capability without them no longer validates. Per ADR-0014
  the refusals are the completion list, not a reason to default the value; a plan may not
  override `timeout_s`.
- **`requires`** (optional map, `name → {type: bool, summary}`) lets a capability declare an
  abstract boolean fact it needs without naming who provides it. The cell binds each requirement
  on each instance to a concrete `instance.signal` (the cell model gains a per-instance
  `requires:` map). This is ADR-0015's ports-and-nets pattern applied to logic — it makes a
  cross-module interlock (`drive_screw` needs `workpiece_secured`, bound to `nest1.clamped`)
  expressible with no new plan syntax.

`preconditions`/`postconditions`/`requires` references now resolve **statically**
(`validate_module`, `set_plan`): a condition naming an unknown signal, an unbound requirement, a
dangling binding, or `on_timeout: hold` on a not-`abort_safe` capability all refuse at resolve
time rather than at first contact with hardware. The expression grammar is unchanged
(`signal == literal`); binding resolves to `(instance, signal)` before evaluation.

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
