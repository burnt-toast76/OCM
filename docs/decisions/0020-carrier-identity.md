# ADR-0020 — Unit identity travels on the carrier

**Status:** Accepted, with Erratum 1 (2026-08-03) — see the end of this document. It narrows the
store-dependent identity refusals (D4/D5) from `refuse` to `degrade` when the record store is
unreachable, so a store outage no longer stops the line (ADR-0021 D2). The decisions below stay
as written; the erratum carries the correction.

## Context

The handoff interlock (ADR-0019) carries no identity. `part_available` says a part is there;
it does not say which part. A line that captures press-fit force in one cell and torque in
the next needs both measurements attributed to the same unit, and the interlock cannot do
it.

Target parts are frequently **not markable** — too small, coated, or cosmetically sensitive.
So the common case is that the unit itself carries no readable identity, and identity has to
live somewhere else that travels with it.

## Decision 1 — Identity is read at every cell, never inferred from position

Positional tracking — each handshake shifts a queue, so the line knows unit N is at station
3 because it counted — is rejected outright.

It works until a part is lifted for inspection, a restart loses the register, or a sensor
double-triggers. Then the line keeps running and keeps writing records, confidently
attributing every unit's data to its neighbour, and nothing reports an error. That is silent
absorption, which is architecturally incompatible with this platform regardless of what it
costs to avoid (ADR-0012).

Every cell reads identity at entry. A read that fails is a refusal, not a fallback to
inference.

## Decision 2 — One tag, two regions

The carrier (pallet, nest, fixture) carries a single RFID tag. Two memory regions, two
different roles:

- **Factory-locked region** (Gen2 TID, ISO 15693 UID) is `carrier_id`. Permanently
  programmed, unwritable, cannot drift or be spoofed.
- **User memory** holds `unit_id`, written at bind and cleared at unbind.

One tag, not two. A second tag on the same carrier adds an antenna-collision failure mode
and a second way for two on-carrier sources to disagree, and buys nothing.

Keeping `unit_id` off the tag entirely — factory ID only, binding resolved from the record
store — was considered and rejected. It makes the store a hard runtime dependency: a cell
could not know what it was holding without a successful query. That contradicts ADR-0021,
where the store is the customer's and is allowed to be unreachable. **The tag write is what
lets the line run correctly with the store down.**

## Decision 3 — Serials are received. Manual entry is marked as such.

OCM does not allocate serial numbers. They arrive from ERP, from a pre-printed batch, or
pre-marked on the unit. A marking cell in the line writes what it was given; it is otherwise
a cell like any other.

Where no upstream source exists, an operator keys the ID at the first cell. That binding
carries `source: operator-keyed` and is **not** equivalent to a verified mark: a keyed ID
has no physical verification and a typo is undetectable at entry. Downstream analysis must
be able to distinguish the two, so the distinction is recorded on the event rather than
normalised away.

## Decision 4 — Channels have an authority order; disagreement is a refusal

Where more than one identity channel is present, authority runs:

1. **Part mark** (DMC on the unit) — physically bound to the unit, survives any carrier swap
2. **Carrier tag user memory** — fast, available offline, but a cache
3. **Store binding** — authoritative across the line, but may be unreachable

A cell declares which channels it reads. Where two or more are present and **disagree, the
cell refuses**. It does not tie-break, and it does not prefer the higher-authority channel
silently — disagreement means the part moved between carriers, or a write went wrong, and
either is a fact the operator needs.

For markable parts this yields a free integrity check and lets a tag write failure degrade
to reading the part mark. For unmarkable parts — the common case here — the carrier tag is
the sole on-line channel, which is why the read-back rule below is not optional.

## Decision 5 — The carrier has a lifecycle, and a stale binding is a refusal

**bind → travels → unbind → returns empty.** Every transition is an event.

If the operator removes a bad unit (ADR-0019, Decision 3), the carrier retains a live
`unit_id` in user memory. It cycles back to the load station, a new unit goes on, and if
nothing cleared the tag the new unit inherits a dead identity — and every downstream
measurement is written to the wrong record, silently, for as long as it takes someone to
notice.

Therefore: **an empty carrier arriving at a load station with a live binding is a refusal.**
The cell will not load onto it until the previous unit is dispositioned. This is the highest-
value refusal in this subsystem, and it exists only because carriers are tracked rather than
positions inferred.

Single-write-per-trip — bind only, no clear on unbind, on the grounds that the load station
overwrites the stale value anyway — halves tag wear and is **rejected**. Every returning
carrier would carry a live binding, so the refusal above would fire constantly and mean
nothing, and empty-vs-bound would have to come from the store. That reintroduces the runtime
store dependency Decision 2 exists to avoid. Two writes per trip is the floor for offline
detection of a stale binding.

## Decision 6 — A tag write is not complete until read back

An interrupted write can leave user memory indeterminate. The binding cell writes, reads
back, and compares. A failed verify is a refusal at the binding cell.

This is what makes tag wear-out **disruptive rather than dangerous**: a worn tag produces a
stopped cell and a swapped pallet, not a corrupted identity.

## Decision 7 — Carrier tags are wear items with a declared rating

At two writes per trip and a continuous cycle, an EEPROM-based tag is a consumable on a
timescale of weeks, not years. This is accepted for now — the failure mode is safe
(Decision 6) — but it is accepted **visibly**.

Rated write endurance is transcribed from the tag datasheet under ADR-0014 discipline. It is
not estimated, and it stays absent until someone reads it off the datasheet; the refusal is
the completion list.

Write count per carrier needs no counter on the tag and no new mechanism: every event
carries `carrier_id`, and bind/unbind are events, so the count is a query over the journal
(ADR-0021). Warn and refuse thresholds are fleet-level declarations. A carrier is retired on
a number, not on the day three units in a row fail read-back for no apparent reason.

**Procurement constraint:** tag form factor and air-interface protocol must be chosen so
that a high-endurance (FRAM) part exists as a drop-in. Then accepting consumability stays a
purchasing decision — swap inserts, transcribe a new component, change one manifest
reference — rather than hardening into a fixture redesign. A form factor with no high-
endurance option turns this shortcut into architecture.

## Shape

```yaml
# cells/press-fit-01/cell.yaml
ports:
  - id: identity
    domain: identification
    carrier:
      reader: fixture.rfid-head       # resolvable component ref
      protocol: iso-15693
      carrier_id_source: uid          # factory-locked, read-only
      unit_id_source: user_memory
    read_at: entry
    on_mismatch: refuse
    on_absent: refuse
```

```yaml
# carrier fleet declaration
carriers:
  tag: com.<vendor>.rfid-tag.<part>
  warn_at_fraction:   0.8
  refuse_at_fraction: 1.0
```

```yaml
# events
event: unit_bound
unit_id:    "SN-4471-0093"
carrier_id: "E280-1160-6000-020F-9B1A"
bound_at:   2026-08-02T14:19:02.331Z
bound_by:   marking-01
source:     laser-mark                # | pre-marked | operator-keyed
verified:   read_back_ok
---
event: disposition
unit_id: "SN-4471-0093"
cell: press-fit-01
after_attempt: 1
action: rework                        # rework | scrap | override_pass
operator: "mreimer"
reason_code: "misaligned-insert"
```

`override_pass` is deliberately distinct from `rework`. Rework means the cell re-ran and the
machine passed the unit. Override means a human passed a unit the machine failed. Those are
different liability positions, and collapsing them into "pass" is how a traceability record
becomes useless in the one audit where it matters.

Refusals this admits:

- Carrier tag `unit_id` disagrees with the part mark, or with the store binding
- Carrier arrives at a load station with a live binding
- Carrier bound to a unit already dispositioned as `scrap`
- Tag write read-back mismatch
- Cell in a traceability line with no `identity` port, or a reader that does not resolve to
  a transcribed component
- Carrier fleet whose declared tag endurance cannot sustain the line's cycle count
- Two cells in one line declaring identity *creation*

## Consequences

- The line runs correctly with the record store unreachable. That is the property this whole
  design buys, and every decision above is subordinate to it.
- Pallets become a consumable line item with a replacement interval. This is an easy
  conversation in a quote and a bad one as unexplained downtime at week six — it goes to the
  customer early.
- A line design can be refused because the pallets would wear out. This is the demonstrable
  form of the wear decision, and a good one to show.
- Cell manifests gain an `identity` port type and a `carriers` fleet declaration. Neither
  exists in the current `cells/` schema.
- Unmarkable parts have exactly one on-line identity channel. Decisions 4 and 6 are what
  keep that from being a single point of silent failure; neither can be dropped as an
  optimisation.

## Related

ADR-0012 (one refusal engine), ADR-0014 (zero-assumption transcription), ADR-0017 (context
is layered), ADR-0019 (cell interconnect), ADR-0021 (journal and record sink)

---

## Erratum 1 (2026-08-03) — store-dependent identity refusals stop the line ADR-0021 keeps running

Found by the refusal-catalogue audit (`docs/refusal-audit.md` §2) when ADR-0025 forced every
refusal to declare a `phase` and an `outcome`. The identity refusals, tagged `phase: cycle`,
were caught assuming a channel that ADR-0021 explicitly permits to be absent.

**What was wrong.** Decision 4's authority order and Decision 5's scrap check both treat every
*declared* channel as *readable at cell entry*. The store binding is a declared channel, and
ADR-0021 Decision 2 permits the record store to be unreachable without stopping the line — that
is the property ADR-0021 exists to buy. So `OCM_IDENTITY_MISMATCH` and `OCM_CARRIER_BOUND_TO_
SCRAP`, written as unconditional `refuse`, stop the line on a database outage: the exact failure
ADR-0021 was built to prevent. This ADR's own headline consequence — *"the line runs correctly
with the record store unreachable"* — is contradicted by its own refusal list. Two channels the
cell can physically hold in its hand (the part mark and the carrier tag) are a different case
from a channel on the far end of a link that may be down, and Decision 4 conflated them.

**Correction A — `OCM_IDENTITY_MISMATCH` is the LOCAL disagreement, and stays `refuse`.**
Disagreement between two channels the cell reads directly — the part mark on the unit and the
carrier tag's user memory — remains an unconditional refusal. The part moved between carriers or
a write went wrong; either is a fact the operator needs, and neither depends on the store being
up. Decision 4's no-tie-break rule is **untouched here**, and this is the case Decision 4 was
actually reasoning about.

**Correction B — store disagreement, or an unreachable store, is `degrade`, not `refuse`.**
Split out as `OCM_IDENTITY_STORE_MISMATCH` (`phase: cycle`, `outcome: degrade`): where the
carrier tag disagrees with the *store* binding, or the store cannot be reached to compare at
all, the cell proceeds and records the fact rather than halting. It records
**`store_binding_checked`** — `true` when the store answered and disagreed, `false` when it was
unreachable — so a later query finds every unit that ran without a confirmed store cross-check.
This is `OCM_BINDING_UNVERIFIED` generalised to the identity comparison, and it is what keeps a
store outage from stopping a line whose local channels agree.

**Correction C — `OCM_CARRIER_BOUND_TO_SCRAP` degrades only when the store is unreachable.**
When the store **answers** and reports the bound unit dispositioned `scrap`, the cell still
`refuse`s — building on a known-scrap carrier is exactly the mistake this refusal exists to
stop, and nothing about it is softened. When the store is **unreachable**, the cell cannot know
the disposition, so it `degrade`s: it proceeds and records **`scrap_disposition_checked: false`**,
rather than halting the line because a database is down. The catalogue entry carries
`outcome: degrade` (the outcome that requires a recorded field) with the conditional stated in
its message; the refuse-when-answered behaviour is not optional.

**Unchanged.** The authority order itself (part mark › carrier tag › store binding). Decision 5's
stale-binding refusal — an empty carrier arriving with a live binding — which is read entirely
from the carrier tag, needs no store, and stays an unconditional `refuse`. Decision 6's write /
read-back / verify, also local. And the principle behind Decision 4: disagreement is never
tie-broken silently. What changes is only that a *store-involving* disagreement is recorded and
survivable instead of line-stopping, because the store is the one channel that is allowed to be
absent.
