# ADR-0021 — The journal is the write; the store is declared

**Status:** Accepted

## Context

Each cell in a line produces measurements for the unit it just worked on (ADR-0020). A
press-fit cell records peak force and final position; a torque cell records torque and
angle. The customer wants one record per unit spanning the whole line.

The obvious implementation — every cell writes to a shared SQL database — has two problems.
It puts a network round trip inside cycle time, so a database restart becomes a production
stoppage. And it makes OCM the system of record, which many customers will not permit:
automotive and medical sites frequently mandate an existing MES or QMS, and a hard-coded
store turns into an integration fight on every one of those jobs.

## Decision 1 — The local journal is the commit

Each cell appends to a local append-only JSONL file, fsynced, **before the cycle is allowed
to complete**. If that write fails, the cell refuses.

```
/var/ocm/journal/press-fit-01/2026-08-02.jsonl
```

JSONL rather than a local database, deliberately: a field technician can `tail -f` it. That
is the same reasoning that governs generated PLC code — the artifact a technician debugs at
02:00 must not require a client tool to read.

Every line carries a per-cell monotonic `seq`.

## Decision 2 — Forwarding is asynchronous, and the sink is declared

A forwarder ships journal events onward. It is not in the cycle path, and the cell does not
wait for it.

The sink is a **declaration in the cell manifest, not an architectural assumption**.
Postgres ships as the reference sink and is what we demo with; MQTT, an OPC UA historian, an
MES file drop, and HTTP POST are peers, not afterthoughts. A customer with an existing MES
gets a different forwarder and an unchanged journal.

Where the central store physically lives — a box in the line panel, or the customer's IT —
is **deliberately not decided here**. It varies per customer, and the journal design makes
it reversible: the forwarder points somewhere else and nothing upstream changes.

## Decision 3 — Events are immutable. The unit record is a query.

No cell ever updates a row. Each cell appends its own events, keyed by `unit_id` and
carrying `carrier_id`.

A shared mutable row per unit was considered and rejected: it recreates, one layer up,
exactly the coupling that ADR-0019 removed from the cell boundary. Two cells contending for
one row means partial writes, lock waits, and a cell that cannot run because a neighbour
holds a lock.

Immutability also handles rework without special-casing. A second attempt is another event
with `attempt: 2`; the disposition that preceded it is its own event (ADR-0020). Nothing
overwrites the failed attempt, so a reworked unit cannot be made to look like a first-pass
success.

Every event carries the `manifest_sha` of the cell manifest that produced it. A measurement
is always traceable to the manifest version that generated the program that took it — the
data equivalent of rung-level provenance comments.

## Decision 4 — `(cell_id, seq)` makes forwarding idempotent

The per-cell monotonic sequence number is the deduplication key. A retry after a half-failed
batch cannot duplicate rows, because the sink rejects a `(cell_id, seq)` it already holds.
No coordination between cells is required to achieve this, because the key is scoped per
cell.

`occurred_at` (cell clock) and `received_at` (sink clock) are separate fields and are never
conflated. Under store-and-forward they can differ by hours, and collapsing them would make
a drained buffer look like a burst of simultaneous production.

## Decision 5 — Buffer depth is declared, and a full buffer is a refusal

A cell states how many unsent events it can hold. When the buffer is full, the cell
**refuses to start a cycle it cannot record**.

This is the honest form of store-and-forward. Without a declared bound and a refusal at the
limit, a long outage silently discards production data — which is the precise failure this
platform exists to prevent.

## Decision 6 — Degrading is permitted when it is legible; absorbing is not

The binding cross-check of ADR-0020 (tag `unit_id` against store binding) is a read against
the store at cell entry. With the store unreachable there are three options: refuse and stop
the line because a database is down; skip the check silently; or **record the degradation**.

The third. The cell proceeds and writes `binding_verified: false` on the event. A query can
then find every unit produced during the outage window and treat it as lower-confidence.

This is not a softening of the refusal principle, and the distinction generalises beyond
this subsystem: **absorption is when degraded output is indistinguishable from good output.**
A recorded degradation is a fact in the data. A skipped check that leaves no trace is not.

## Shape

```yaml
# cells/press-fit-01/cell.yaml
record_sink:
  journal:
    path: /var/ocm/journal
    fsync: per_event
    retention_days: 90
  forward:
    - type: postgres
      dsn_env: OCM_RECORD_DSN
  on_journal_unavailable: refuse
  on_forward_unavailable: buffer
  buffer_max_events: 50000
  on_buffer_full: refuse

produces:
  measurements:
    - {name: peak_force,     unit: N,  source: press-head.load-cell}
    - {name: final_position, unit: mm, source: press-head.encoder}
    - {name: force_curve,    type: series, source: press-head.load-cell}
  verdict:
    name: press_result
    values: [pass, fail]
  record_keys:
    primary: unit_id
    include: [carrier_id]
```

Reference sink schema:

```sql
CREATE TABLE events (
  cell_id      TEXT        NOT NULL,
  seq          BIGINT      NOT NULL,
  event_type   TEXT        NOT NULL,   -- measurement | disposition | unit_bound | unbind
  unit_id      TEXT,
  carrier_id   TEXT,
  occurred_at  TIMESTAMPTZ NOT NULL,   -- cell clock
  received_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  manifest_sha TEXT        NOT NULL,
  payload      JSONB       NOT NULL,
  PRIMARY KEY (cell_id, seq)
);
CREATE INDEX ON events (unit_id);
CREATE INDEX ON events (carrier_id);
```

Refusals this admits:

- A `produces` measurement whose `source` resolves to a component that cannot produce it —
  a force reading sourced from an encoder. ADR-0014 transcription already records what the
  load cell measures; if the datasheet does not support the claim, refuse.
- A measurement declared without a unit
- A cell with `produces` but no `record_sink`
- A journal path that is unwritable at start-up
- Buffer full

## Consequences

- A store outage does not stop the line. Cells keep running, keep recording, and drain when
  the link returns.
- OCM is not the system of record and does not need to be. The customer's MES can be the
  sink from day one.
- The record schema is generated from manifests rather than hand-configured — the cell
  already declares the components that do the measuring.
- `carrier_id` on every measurement makes fixture-level analysis possible ("is carrier 0207
  failing more than the fleet"), which is otherwise unanswerable.
- Journals accumulate on cell hardware and need retention management. `retention_days` is
  declared, not assumed, and disk exhaustion is a refusal like any other.
- Cell manifests gain `record_sink` and `produces` blocks. With ADR-0019's `ports` and
  ADR-0020's `identity` and `carriers`, this is a substantial expansion of a `cells/` schema
  that is currently much thinner than the module schema.

## Possible extension, not decided

Including the previous event's hash in each journal line would make the journal tamper-
evident for a few lines of code, which converts "we log to a file" into an auditable chain
for regulated customers. Signing and anything heavier waits until a customer asks.

## Related

ADR-0012 (one refusal engine), ADR-0014 (zero-assumption transcription), ADR-0017 (context
is layered), ADR-0019 (cell interconnect), ADR-0020 (carrier identity)
