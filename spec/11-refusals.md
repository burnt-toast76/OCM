# 11 — Refusals

A refusal is how OCM says *no, and why*. The **vocabulary** of refusals — the codes, the phase
each is evaluated in, the outcome it produces, and what it means — is part of the standard, not
an implementation detail of any one engine. A third party writing their own generator against
OCM manifests must be able to emit these codes and have them mean what they mean here; that is
the test ADR-0018 sets for independent implementability, and this vocabulary is the first thing
that makes it falsifiable.

The rationale lives in **ADR-0025** (one refusal source, three evaluation phases) and
**ADR-0012** (one refusal engine). This page is the spec-side statement of the vocabulary. The
machine-readable catalogue is **[`spec/schema/ocm-refusals-1.0.yaml`](schema/ocm-refusals-1.0.yaml)**
and is the source of truth; the table below is rendered from it.

## Phases

One source of rules; three phases evaluate it. A code belongs to exactly one phase.

- **design** — inputs are manifests only. Runs in `ocm-resolve` / `validate_*`, anywhere.
- **load** — inputs are manifests plus the machine environment, evaluated once at start-up or a
  state transition. Runs in the same engine, on the machine.
- **cycle** — inputs are live machine state, inside the cycle path. Emitted as generated
  PLC / coordinator logic, from the same catalogue, with the same codes.

## Outcomes

- **refuse** — the operation does not proceed. The default and the overwhelming majority.
- **degrade** — the operation proceeds and the degradation is recorded as a fact on the event.
  Permitted **only** where a later query can identify every affected unit, so every `degrade`
  entry MUST name the field it records (`records:`). A `degrade` without a `records` field is a
  defect, checked in CI.
- **advise** — surfaced to a human, no gating. Not a refusal; catalogued so it cannot drift into
  gating behaviour by proximity.

## Namespaces (transitional)

ADR-0025 D4 namespaces codes `OCM_`. Two namespaces currently coexist, and the split is
deliberate and honest:

- **Bare codes** (`SCHEMA_INVALID`, `NET_TOO_FEW_ENDPOINTS`, …) are the codes `ocm-resolve` and
  `ocm-api` already emit today. Their existing names are kept rather than renamed to a parallel
  scheme.
- **`OCM_` codes** are vocabulary an ADR names but no engine emits yet. Each is `status:
  deferred` with a `requires:` note stating what must land first.

The migration of the live codes onto the `OCM_` prefix, and the per-code gaps, are tracked in
**[`docs/refusal-audit.md`](../docs/refusal-audit.md)**.

## Catalogue

`status` is `live` (an engine emits it today) or `deferred` (named by an ADR; awaiting a schema
field, a layer, or a runtime that does not exist yet).

| Code | Phase | Outcome | Layer | ADR | Status |
|---|---|---|---|---|---|
| `ALREADY_EXISTS` | design | refuse | api | ADR-0012 | live |
| `CELL_INVALID` | design | refuse | cell | ADR-0012 | live |
| `COLLISION_DETECTED` | design | refuse | cell | ADR-0007 | live |
| `COMPONENT_HAS_NO_CONNECTORS` | design | refuse | module | ADR-0015 | live |
| `CONDITION_UNKNOWN_SIGNAL` | design | refuse | module | ADR-0023 | live |
| `DANGLING_MOUNT` | design | refuse | cell | ADR-0012 | live |
| `DRAFT_MODULE_REFERENCED` | design | refuse | cell | ADR-0016 | live |
| `DRAFT_NOT_PUBLISHABLE` | design | refuse | module | ADR-0016 | live |
| `DUPLICATE_REFDES` | design | refuse | module | ADR-0014 | live |
| `ETHERCAT_CHAIN_BROKEN` | design | refuse | module | ADR-0015 | live |
| `HUMAN_SIGNATURE_REQUIRED` | design | refuse | cell | ADR-0012 | live |
| `INVALID_ARGUMENT` | design | refuse | api | ADR-0012 | live |
| `INVALID_SOURCE` | design | refuse | module | ADR-0014 | live |
| `LINK_NON_COMMUNICATION_PORT` | design | refuse | module | ADR-0015 | live |
| `LINK_PROTOCOL_MISMATCH` | design | refuse | module | ADR-0015 | live |
| `NET_TOO_FEW_ENDPOINTS` | design | refuse | module | ADR-0015 | live |
| `NOT_FOUND` | design | refuse | api | ADR-0012 | live |
| `NO_FASTENING_STEP` | design | refuse | cell | ADR-0012 | live |
| `PARAM_OUT_OF_BOUNDS` | design | refuse | cell | ADR-0013 | live |
| `PATH_COLLISION` | design | refuse | cell | ADR-0007 | live |
| `PIN_ON_MULTIPLE_NETS` | design | refuse | module | ADR-0015 | live |
| `PORT_UNCONNECTED` | design | refuse | module | ADR-0015 | live |
| `POSE_UNREACHABLE` | design | refuse | cell | ADR-0007 | live |
| `REQUIREMENT_UNBOUND` | design | refuse | cell | ADR-0023 | live |
| `REQUIREMENT_UNKNOWN_TARGET` | design | refuse | cell | ADR-0023 | live |
| `REVISION_MISMATCH` | design | refuse | cell | ADR-0012 | live |
| `SCHEMA_INVALID` | design | refuse | module | ADR-0016 | live |
| `TIMEOUT_DISPOSITION_CONFLICT` | design | refuse | module | ADR-0023 | live |
| `TOOL_SLOT_OCCUPIED` | design | refuse | cell | ADR-0012 | live |
| `UNKNOWN_COMPONENT` | design | refuse | module | ADR-0014 | live |
| `UNKNOWN_MODULE` | design | refuse | cell | ADR-0012 | live |
| `UNKNOWN_OP` | design | refuse | cell | ADR-0012 | live |
| `UNKNOWN_PARAM` | design | refuse | cell | ADR-0012 | live |
| `UNRESOLVED_ENDPOINT` | design | refuse | module | ADR-0015 | live |
| `WORKSPACE_OVERHANG` | design | refuse | cell | ADR-0012 | live |
| `OCM_CARRIER_ENDURANCE_EXCEEDED` | design | refuse | line | ADR-0020 | deferred |
| `OCM_COMMS_CHAIN_BROKEN` | design | refuse | module | ADR-0015 | deferred |
| `OCM_HANDOFF_DIRECTION_MISMATCH` | design | refuse | cell | ADR-0019 | deferred |
| `OCM_HANDOFF_PORT_NO_IO` | design | refuse | cell | ADR-0019 | deferred |
| `OCM_HANDOFF_SAME_ROLE` | design | refuse | cell | ADR-0019 | deferred |
| `OCM_IDENTITY_DOUBLE_CREATION` | design | refuse | line | ADR-0020 | deferred |
| `OCM_IDENTITY_PORT_MISSING` | design | refuse | cell | ADR-0020 | deferred |
| `OCM_MANUAL_MODE_SAFETY_UNRESOLVED` | design | refuse | cell | ADR-0024 | deferred |
| `OCM_MEASUREMENT_NO_UNIT` | design | refuse | cell | ADR-0021 | deferred |
| `OCM_MEASUREMENT_SOURCE_INVALID` | design | refuse | cell | ADR-0021 | deferred |
| `OCM_NET_OVERPRESSURE` | design | refuse | module | ADR-0015 | deferred |
| `OCM_NET_SIGNAL_CLASS_MISMATCH` | design | refuse | module | ADR-0015 | deferred |
| `OCM_NET_TWO_DRIVERS` | design | refuse | module | ADR-0015 | deferred |
| `OCM_NO_RECORD_SINK` | design | refuse | cell | ADR-0021 | deferred |
| `OCM_PIN_REQUIRED_UNCONNECTED` | design | refuse | module | ADR-0015 | deferred |
| `OCM_PNEUMATIC_PORT_MISMATCH` | design | refuse | module | ADR-0015 | deferred |
| `OCM_SAFETY_NET_UNRATED` | design | refuse | cell | ADR-0019 | deferred |
| `OCM_SIGNAL_NO_ACTIVE_STATE` | design | refuse | cell | ADR-0019 | deferred |
| `AGENT_UNAVAILABLE` | load | refuse | api | ADR-0012 | live |
| `UNAVAILABLE` | load | refuse | api | ADR-0012 | live |
| `OCM_COMMISSIONING_EXIT_KEY_IN_EDIT` | load | refuse | cell | ADR-0024 | deferred |
| `OCM_COMMISSIONING_NO_KEYSWITCH` | load | refuse | cell | ADR-0022 | deferred |
| `OCM_JOURNAL_PATH_UNWRITABLE` | load | refuse | cell | ADR-0021 | deferred |
| `OCM_MANIFEST_ROOT_UNREADABLE` | load | refuse | cell | ADR-0022 | deferred |
| `OCM_MANIFEST_SHA_MISMATCH` | load | refuse | cell | ADR-0022 | deferred |
| `OCM_NO_MODE_SELECTOR` | load | refuse | cell | ADR-0024 | deferred |
| `OCM_REGENERATE_VERIFY_MISMATCH` | load | refuse | cell | ADR-0022 | deferred |
| `OCM_BINDING_UNVERIFIED` | cycle | degrade | cell | ADR-0021 | deferred |
| `OCM_BUFFER_FULL` | cycle | refuse | cell | ADR-0021 | deferred |
| `OCM_CARRIER_BOUND_TO_SCRAP` | cycle | refuse | cell | ADR-0020 | deferred |
| `OCM_CARRIER_STALE_BINDING` | cycle | refuse | cell | ADR-0020 | deferred |
| `OCM_COMMAND_PARAM_OUT_OF_BOUNDS` | cycle | refuse | cell | ADR-0024 | deferred |
| `OCM_DIAGNOSTIC_SOURCE_UNAVAILABLE` | cycle | advise | cell | ADR-0022 | deferred |
| `OCM_IDENTITY_MISMATCH` | cycle | refuse | cell | ADR-0020 | deferred |
| `OCM_MANUAL_OP_PRECONDITION_UNMET` | cycle | refuse | cell | ADR-0024 | deferred |
| `OCM_TAG_READBACK_MISMATCH` | cycle | refuse | cell | ADR-0020 | deferred |

Message strings and `requires:` notes are in the YAML. Keeping the strings there means a message
fix — such as ADR-0015 Erratum 1's Correction D (a pneumatic endpoint must not be told its
"pinout" is missing) — is a data change in one file, not a code change.
