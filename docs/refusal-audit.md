# Refusal audit — worklist

Companion to `spec/11-refusals.md` / `spec/schema/ocm-refusals-1.0.yaml` (ADR-0025). For every
catalogue entry: where it is evaluated **today**, and the gap flag. This is a worklist, not an
essay.

**Counts.** 87 entries: 45 `live` (an engine emits them now), 42 `deferred` (an ADR names them;
no engine emits them yet). (ADR-0020 Erratum 1 split `OCM_IDENTITY_MISMATCH` into a local and a
store code, +1 deferred.)

## Namespace — RESOLVED by rename

The catalogue once carried two namespaces (bare live codes, `OCM_` deferred vocabulary). The
37 live codes were renamed to `OCM_<NAME>` — every engine, the composer, tests, spec, and the
catalogue keys — so ADR-0025 D4 now holds without exception. Done in this commit; there is one
namespace.

## Flag legend

- **unrunnable** — no phase/layer can evaluate it (the layer it needs does not exist).
- **store-dependent** — a cycle-phase refusal that needs the record store, which ADR-0021 D6
  permits to be unreachable.
- **cell-no-schema** — needs a field of the `cells/` JSON schema. **As of ADR-0026 that schema
  now exists** (`spec/schema/ocm-cell-1.0.schema.json`); these entries are no longer
  schema-blocked and now await *resolve logic* (the cross-check into contained modules). The
  label is kept so the family stays greppable until that logic lands.
- **declared-unimpl** — named by an ADR, in the catalogue, emitted by no engine.
- **emitted-uncatalogued** — an engine emits it; no ADR describes it.
- **spec/09-only** — an engine emits it; described narratively in spec/09 but in no ADR refusal
  list (nearest ADR of record: ADR-0007).

## Every entry

| Code | Phase/Outcome | Evaluated today | Flag |
|---|---|---|---|
| `OCM_ALREADY_EXISTS` | design/refuse | ocm-api verb (direct) | **emitted-uncatalogued** |
| `OCM_AUTHORED_COLLISION_MISSING` | design/refuse | ocm-generator collision_geometry → validate_module | — |
| `OCM_CELL_INVALID` | design/refuse | ocm-core loader → ocm-api/translate.py | — |
| `OCM_COLLISION_DETECTED` | design/refuse | ocm-generator (plan/scene) → ocm-api/generation.py | spec/09-only |
| `OCM_COLLISION_SOURCE_MISSING` | design/refuse | ocm-api verb (direct) | — |
| `OCM_COMPONENT_HAS_NO_CONNECTORS` | design/refuse | ocm-resolve → ocm-api/translate.py | — |
| `OCM_COMPONENT_OUTSIDE_COLLISION` | design/refuse | ocm-generator collision_geometry → validate_module | — |
| `OCM_CONDITION_UNKNOWN_SIGNAL` | design/refuse | ocm-resolve → ocm-api/translate.py | — |
| `OCM_DANGLING_MOUNT` | design/refuse | ocm-resolve → ocm-api/translate.py | — |
| `OCM_DERIVED_ENVELOPE_MISSING` | design/refuse | ocm-resolve → ocm-api/translate.py | — |
| `OCM_DERIVED_POSE_MISSING` | design/refuse | ocm-resolve → ocm-api/translate.py | — |
| `OCM_DRAFT_MODULE_REFERENCED` | design/refuse | ocm-api verb (direct) | — |
| `OCM_DRAFT_NOT_PUBLISHABLE` | design/refuse | ocm-api verb (direct) | — |
| `OCM_DUPLICATE_REFDES` | design/refuse | ocm-resolve → ocm-api/translate.py | — |
| `OCM_ENVELOPE_OVERLAP` | design/advise | ocm-generator collision_geometry → validate_module | — |
| `OCM_ETHERCAT_CHAIN_BROKEN` | design/refuse | ocm-resolve → ocm-api/translate.py | — |
| `OCM_HUMAN_SIGNATURE_REQUIRED` | design/refuse | ocm-api verb (direct) | — |
| `OCM_INVALID_ARGUMENT` | design/refuse | ocm-api verb (direct) | **emitted-uncatalogued** |
| `OCM_INVALID_SOURCE` | design/refuse | ocm-resolve → ocm-api/translate.py | — |
| `OCM_LINK_NON_COMMUNICATION_PORT` | design/refuse | ocm-resolve → ocm-api/translate.py | — |
| `OCM_LINK_PROTOCOL_MISMATCH` | design/refuse | ocm-resolve → ocm-api/translate.py | — |
| `OCM_LINK_UNKNOWN` | design/refuse | ocm-generator collision_geometry → validate_module | — |
| `OCM_NET_TOO_FEW_ENDPOINTS` | design/refuse | ocm-resolve → ocm-api/translate.py | — |
| `OCM_NOT_FOUND` | design/refuse | ocm-api verb (direct) | **emitted-uncatalogued** |
| `OCM_NO_FASTENING_STEP` | design/refuse | ocm-generator (plan/scene) → ocm-api/generation.py | spec/09-only |
| `OCM_PARAM_OUT_OF_BOUNDS` | design/refuse | ocm-resolve → ocm-api/translate.py | — |
| `OCM_PATH_COLLISION` | design/refuse | ocm-generator (plan/scene) → ocm-api/generation.py | spec/09-only |
| `OCM_PIN_ON_MULTIPLE_NETS` | design/refuse | ocm-resolve → ocm-api/translate.py | — |
| `OCM_PORT_UNCONNECTED` | design/refuse | ocm-resolve → ocm-api/translate.py | — |
| `OCM_POSE_UNREACHABLE` | design/refuse | ocm-generator (plan/scene) → ocm-api/generation.py | spec/09-only |
| `OCM_REQUIREMENT_UNBOUND` | design/refuse | ocm-resolve → ocm-api/translate.py | — |
| `OCM_REQUIREMENT_UNKNOWN_TARGET` | design/refuse | ocm-resolve → ocm-api/translate.py | — |
| `OCM_REVISION_MISMATCH` | design/refuse | ocm-resolve → ocm-api/translate.py | — |
| `OCM_SCHEMA_INVALID` | design/refuse | ocm-core loader → ocm-api/translate.py | — |
| `OCM_TIMEOUT_DISPOSITION_CONFLICT` | design/refuse | ocm-resolve → ocm-api/translate.py | — |
| `OCM_TOOL_SLOT_OCCUPIED` | design/refuse | ocm-api verb (direct) | — |
| `OCM_UNIT_UNRECOGNISED` | design/refuse | ocm-resolve → ocm-api/translate.py | — |
| `OCM_UNKNOWN_COMPONENT` | design/refuse | ocm-resolve → ocm-api/translate.py | — |
| `OCM_UNKNOWN_MODULE` | design/refuse | ocm-resolve → ocm-api/translate.py | — |
| `OCM_UNKNOWN_OP` | design/refuse | ocm-resolve → ocm-api/translate.py | — |
| `OCM_UNKNOWN_PARAM` | design/refuse | ocm-resolve → ocm-api/translate.py | — |
| `OCM_UNRESOLVED_ENDPOINT` | design/refuse | ocm-resolve → ocm-api/translate.py | — |
| `OCM_WORKSPACE_OVERHANG` | design/refuse | ocm-api verb (direct) | — |
| `OCM_ACTIVE_NOT_ON_NET` | design/refuse | — nowhere yet | structural (OCM_SCHEMA_INVALID) |
| `OCM_CARRIER_ENDURANCE_EXCEEDED` | design/refuse | — nowhere yet | **unrunnable** |
| `OCM_COMMS_CHAIN_BROKEN` | design/refuse | — nowhere yet | declared-unimpl |
| `OCM_DIRECTION_AT_CELL_LAYER` | design/refuse | — nowhere yet | structural (OCM_SCHEMA_INVALID) |
| `OCM_HANDOFF_DIRECTION_MISMATCH` | design/refuse | — nowhere yet | cell-no-schema · declared-unimpl |
| `OCM_HANDOFF_PORT_NO_IO` | design/refuse | — nowhere yet | cell-no-schema · declared-unimpl |
| `OCM_HANDOFF_SAME_ROLE` | design/refuse | — nowhere yet | cell-no-schema · declared-unimpl |
| `OCM_IDENTITY_DOUBLE_CREATION` | design/refuse | — nowhere yet | **unrunnable** |
| `OCM_IDENTITY_PORT_MISSING` | design/refuse | — nowhere yet | cell-no-schema · declared-unimpl |
| `OCM_LINK_ENDPOINT_NOT_A_PORT` | design/refuse | — nowhere yet | structural (OCM_SCHEMA_INVALID) |
| `OCM_MANUAL_MODE_SAFETY_UNRESOLVED` | design/refuse | — nowhere yet | cell-no-schema · declared-unimpl |
| `OCM_MEASUREMENT_NO_UNIT` | design/refuse | — nowhere yet | cell-no-schema · declared-unimpl |
| `OCM_MEASUREMENT_SOURCE_INVALID` | design/refuse | — nowhere yet | cell-no-schema · declared-unimpl |
| `OCM_NET_OVERPRESSURE` | design/refuse | — nowhere yet | declared-unimpl |
| `OCM_NET_PIN_NOT_EXPOSED` | design/refuse | — nowhere yet | cell-no-schema · declared-unimpl |
| `OCM_NET_SIGNAL_CLASS_MISMATCH` | design/refuse | — nowhere yet | declared-unimpl |
| `OCM_NET_TWO_DRIVERS` | design/refuse | — nowhere yet | declared-unimpl |
| `OCM_NO_RECORD_SINK` | design/refuse | — nowhere yet | cell-no-schema · declared-unimpl |
| `OCM_PIN_REQUIRED_UNCONNECTED` | design/refuse | — nowhere yet | declared-unimpl |
| `OCM_PNEUMATIC_PORT_MISMATCH` | design/refuse | — nowhere yet | declared-unimpl |
| `OCM_PORT_DOMAIN_IDENTIFICATION` | design/refuse | — nowhere yet | structural (OCM_SCHEMA_INVALID) |
| `OCM_PORT_HAS_SIGNALS_LIST` | design/refuse | — nowhere yet | structural (OCM_SCHEMA_INVALID) |
| `OCM_SAFETY_NET_UNRATED` | design/refuse | — nowhere yet | cell-no-schema · declared-unimpl |
| `OCM_SIGNAL_NO_ACTIVE_STATE` | design/refuse | — nowhere yet | cell-no-schema · declared-unimpl |
| `OCM_STRUCTURE_INCOMPLETE` | design/refuse | — nowhere yet | structural (OCM_SCHEMA_INVALID) |
| `OCM_AGENT_UNAVAILABLE` | load/refuse | ocm-api verb (direct) | **emitted-uncatalogued** |
| `OCM_UNAVAILABLE` | load/refuse | ocm-api verb (direct) | **emitted-uncatalogued** |
| `OCM_COMMISSIONING_EXIT_KEY_IN_EDIT` | load/refuse | — nowhere yet | declared-unimpl |
| `OCM_COMMISSIONING_NO_KEYSWITCH` | load/refuse | — nowhere yet | declared-unimpl |
| `OCM_JOURNAL_PATH_UNWRITABLE` | load/refuse | — nowhere yet | declared-unimpl |
| `OCM_MANIFEST_ROOT_UNREADABLE` | load/refuse | — nowhere yet | declared-unimpl |
| `OCM_MANIFEST_SHA_MISMATCH` | load/refuse | — nowhere yet | declared-unimpl |
| `OCM_NO_MODE_SELECTOR` | load/refuse | — nowhere yet | cell-no-schema · declared-unimpl |
| `OCM_REGENERATE_VERIFY_MISMATCH` | load/refuse | — nowhere yet | declared-unimpl |
| `OCM_BINDING_UNVERIFIED` | cycle/degrade | — nowhere yet | declared-unimpl |
| `OCM_BUFFER_FULL` | cycle/refuse | — nowhere yet | declared-unimpl |
| `OCM_CARRIER_BOUND_TO_SCRAP` | cycle/degrade | — nowhere yet | cell-no-schema · declared-unimpl |
| `OCM_CARRIER_STALE_BINDING` | cycle/refuse | — nowhere yet | cell-no-schema · declared-unimpl |
| `OCM_COMMAND_PARAM_OUT_OF_BOUNDS` | cycle/refuse | — nowhere yet | declared-unimpl |
| `OCM_DIAGNOSTIC_SOURCE_UNAVAILABLE` | cycle/advise | — nowhere yet | declared-unimpl |
| `OCM_IDENTITY_MISMATCH` | cycle/refuse | — nowhere yet | cell-no-schema · declared-unimpl |
| `OCM_IDENTITY_STORE_MISMATCH` | cycle/degrade | — nowhere yet | cell-no-schema · declared-unimpl |
| `OCM_MANUAL_OP_PRECONDITION_UNMET` | cycle/refuse | — nowhere yet | declared-unimpl |
| `OCM_TAG_READBACK_MISMATCH` | cycle/refuse | — nowhere yet | cell-no-schema · declared-unimpl |

## 1. Unrunnable — no phase can evaluate them

| Code | ADR | Why unrunnable |
|---|---|---|
| `OCM_CARRIER_ENDURANCE_EXCEEDED` | ADR-0020 | Fleet endurance vs the line's cycle-count budget is a **line-scoped** check. ADR-0019 D5 deferred the line layer, so there is no manifest object that spans the cells whose cycles it must sum. |
| `OCM_IDENTITY_DOUBLE_CREATION` | ADR-0020 | "Two cells in one line both create identity" can only be seen with all cells of a line in view. Same missing line layer. |

These are exactly the two ADR-0025 predicted. No others surfaced: every remaining deferred entry
has a phase that *could* run it once its schema field or runtime lands (below), whereas these two
have no layer to run in at all. **Fix:** they wait on the line layer (a new ADR), not on a schema
field.

## 2. Store-dependent in cycle phase — RESOLVED (ADR-0020 Erratum 1)

ADR-0021 D6 permits the record store to be unreachable without stopping the line. A **cycle**
refusal that needs the store therefore cannot simply `refuse` — it would halt production on a
store outage, the exact failure ADR-0021 rejects. **Fixed** in ADR-0020 Erratum 1 (Corrections
A–C) and reflected in the catalogue:

| Code | Now | Resolution |
|---|---|---|
| `OCM_CARRIER_BOUND_TO_SCRAP` | degrade (records `scrap_disposition_checked`) | Correction C: still `refuse` when the store **answers** `scrap`; `degrade` and record when the store is **unreachable**, so a database outage no longer stops the line. |
| `OCM_IDENTITY_MISMATCH` | refuse | Correction A: narrowed to the **local** disagreement (part mark vs carrier tag) — two channels the cell reads directly, needing no store. D4's no-tie-break rule untouched. |
| `OCM_IDENTITY_STORE_MISMATCH` *(new)* | degrade (records `store_binding_checked`) | Correction B: the store half, split out. Store disagreement or an unreachable store degrades and records, matching `OCM_BINDING_UNVERIFIED`. |
| `OCM_BINDING_UNVERIFIED` | degrade ✓ | Unchanged — the canonical case (records `binding_verified`). |

## 3. Cell-layer refusals — schema now authored (ADR-0026)

**Update:** `spec/schema/ocm-cell-1.0.schema.json` now exists (ADR-0026); `load_cell` validates
against it, and `cell.py` models every block. The fields below are all covered. So these
cell-layer refusals are **no longer blocked on a schema** — they now await *resolve logic* (the
cross-checks into contained modules), which is the next pass, not this one. The four structural
ADR-0026 refusals (`OCM_PORT_HAS_SIGNALS_LIST`, `OCM_PORT_DOMAIN_IDENTIFICATION`,
`OCM_ACTIVE_NOT_ON_NET`, `OCM_DIRECTION_AT_CELL_LAYER`) are already enforced by the schema
structurally, surfacing as `OCM_SCHEMA_INVALID`.

The fields the schema now covers, for the record:

| ADR | Cell field | For |
|---|---|---|
| ADR-0019 | `ports` — handoff ports (`smema-upstream`/`smema-downstream`, `role`, `domain`), handoff nets, safety-domain nets, signals with an `active` state | cell interconnect; the discrete-I/O handoff |
| ADR-0020 | `identity` — a port type (reader → transcribed component) | reading part identity at cell entry |
| ADR-0020 | `carriers` — fleet declaration (tag endurance, `warn`/`refuse` fractions, retirement) | carrier lifecycle and wear budget |
| ADR-0021 | `produces` — measurements, each with `source` (→ component) and `unit` | what the cell records |
| ADR-0021 | `record_sink` — where records drain to; buffer depth; `retention_days` | the journal sink |
| ADR-0024 | `mode_selector` — `component`, `positions: [auto, manual, edit]`, `manual_mode_safety` | AUTO/MANUAL/EDIT command authority |

**Precedent + anomaly:** ADR-0023 (plans-are-verbs) already added a per-instance `requires:` map
to the cell — and it landed **without** a cell schema, parsed structurally in `cell.py`. So today
cell fields are enforced by Python, not JSON Schema. Every refusal above is stuck behind that
same missing schema (or a hand-rolled Python check like `requires`). A cell schema is the single
biggest unblock in this audit.

## 4. Declared but unimplemented

All 34 `OCM_*` entries: named by an ADR, in the catalogue, emitted by no engine. They are the
catalogue's honest core — the vocabulary is complete; the implementation is not. Grouped by what
each waits on:

- **Component schema field** (ADR-0015 D5 table 2): `OCM_NET_TWO_DRIVERS`,
  `OCM_NET_SIGNAL_CLASS_MISMATCH`, `OCM_PIN_REQUIRED_UNCONNECTED`, `OCM_PNEUMATIC_PORT_MISMATCH`,
  `OCM_NET_OVERPRESSURE`, `OCM_COMMS_CHAIN_BROKEN`.
- **Cell schema field** (§3 above): the ADR-0019/0020/0021/0024 design-phase entries.
- **Runtime load/cycle engine** (generated PLC / coordinator, on the machine): the ADR-0021/0022
  load + cycle entries, and ADR-0024's command-path entries. These are the ones ADR-0025 D1 says
  are *generated from* the catalogue, not hand-written.
- **The line layer** (§1): the two unrunnables.

## 5. Emitted but uncatalogued (by any ADR)

Engines emit these; no ADR describes them. They are catalogued now (so CI passes and the
vocabulary is closed) but have no ADR of record:

| Code | Emitted by | Note |
|---|---|---|
| `OCM_NOT_FOUND`, `OCM_ALREADY_EXISTS`, `OCM_INVALID_ARGUMENT` | ocm-api verbs | API plumbing, not manifest refusals. Fine as-is; flagged so no one mistakes them for standardised vocabulary. |
| `OCM_UNAVAILABLE`, `OCM_AGENT_UNAVAILABLE` | ocm-api verbs | Environment/infra gates (a missing optional extra; no API key), not manifest defects. `phase: load` is the closest fit. |
| `OCM_POSE_UNREACHABLE`, `OCM_PATH_COLLISION`, `OCM_COLLISION_DETECTED`, `OCM_NO_FASTENING_STEP` | ocm-generator (plan/scene) | Described narratively in spec/09's `plan_cell` row but in **no ADR refusal list**. Nearest ADR of record: ADR-0007 (Tesseract). Candidate for a short "generation refusals" note in an ADR. |

## Summary worklist

1. ~~Reconcile the namespace (bare vs `OCM_`).~~ **Done** — the 37 live codes were renamed to
   `OCM_<NAME>` in this commit; one namespace now.
2. ~~Author a `cells/` JSON schema.~~ **Done** — `spec/schema/ocm-cell-1.0.schema.json` (ADR-0026);
   `load_cell` validates against it and `cell.py` models every block. The §3 refusals now await
   resolve logic, not a schema.
3. ~~Re-classify two store-dependent cycle refusals to `degrade`.~~ **Done** — ADR-0020 Erratum 1
   (`OCM_CARRIER_BOUND_TO_SCRAP` degrades when the store is unreachable; `OCM_IDENTITY_MISMATCH`
   split into a local `refuse` and a new `OCM_IDENTITY_STORE_MISMATCH` `degrade`).
4. **The line layer** (new ADR) — the only home for the two unrunnables.
5. **Give the four generation refusals an ADR of record** (or fold into ADR-0007).

