# ADR-0019 — Cells interconnect by discrete I/O, not by fieldbus

**Status:** Accepted

## Context

A cell is the third context layer (ADR-0017): modules placed, connected, and driven by one
PLC. Nothing yet says what happens when two cells sit next to each other and a unit has to
travel from one to the next — a press-fit cell feeding a torque cell, both built by us,
possibly with a third-party machine between them.

EtherCAT is the fieldbus inside a cell (ADR-0002), so the obvious question is whether it is
also the fieldbus *between* cells. It cannot be, directly: EtherCAT is single-master, and
two cells that each own their PLC are two masters. Joining their segments with a cable is
not a configuration choice, it is invalid.

That leaves three real options, and they differ in how tightly they bind the two cells
together — which is the actual decision, not the wire.

## Decision 1 — Three independent channels cross the boundary

A cell boundary carries three things, and they do not share a medium:

**Safety.** Guard state and E-stop. Safety-rated devices only — TwinSAFE/FSoE or hardwired.
Never inferred from, or carried by, either channel below.

**Handoff interlock.** Two discrete signals in opposing directions: upstream asserts *part
available*, downstream asserts *ready to accept*. Opto-isolated, in the manner of
IPC-SMEMA-9851. This is the entire flow-control protocol.

**Data.** Unit records, recipes, traceability. TCP — the sink is declared, not assumed
(ADR-0021). Never time-critical, never an interlock.

Collapsing any two of these into one medium is what makes lines brittle. A safety function
riding a data link is unrated; an interlock riding a data link inherits the data link's
availability.

## Decision 2 — No EtherCAT segment crosses a cell boundary

The EL6692 bridge terminal is technically capable of exactly what the question asks: real-
time process data between EtherCAT strands with different masters, distributed-clock
synchronisation between strands, up to 480 bytes each direction. It is rejected as the
default anyway, on coupling rather than capability.

A bridge places Cell B's process image inside Cell A's TwinCAT configuration. The two cells
are then one machine in two frames: Cell B cannot be replaced by a different vendor's
machine, and cannot be sold separately, without re-engineering the interface. Discrete I/O
lets any machine that implements a two-wire handshake — which is nearly all of them — drop
into the line unchanged.

A bridge remains available as a **documented exception** for a specific cell pair that needs
coordinated motion across the seam. It is a per-line decision with a written justification,
not a platform default.

Also rejected: one master owning both cells' modules, with Hot Connect groups for physical
detachment. Cheapest and tightest, and it dissolves the independent-machine property
entirely.

## Decision 3 — Only good units cross the handshake

A unit crossing the interlock has passed the upstream cell. Failures are reconciled by the
operator **at the cell that found them** — removed, or fixed and sent forward.

This means the interlock carries a quality bit implicitly, and no cell needs to query
upstream verdicts before accepting a part. That is what allows a cell to run with the record
store unreachable (ADR-0021).

An operator sending a reworked unit forward is a distinct recorded action from a machine
pass. See ADR-0020 for the disposition vocabulary; the point here is that the interlock
itself does not encode the difference and must not be asked to.

## Decision 4 — The interlock is PackML's Suspended state, realised in copper

ADR-0004 already mandates PackML. PackML already distinguishes **Suspended** — stopped by
external conditions, starved of upstream input or blocked by a downstream machine that
cannot accept — from **Held**, which is internal.

Starved and blocked are precisely what the two handshake signals report. The interlock is
therefore not a new concept bolted onto the state model; it is the state model's external
boundary made physical. The generator derives interlock rungs from the PackML state model
rather than treating them as hand-written glue, and the tag names follow the same manifest-
derived convention as everything else generated.

## Decision 5 — Cells declare boundary ports; line composition is deferred

The ADR-0015 vocabulary applies one scope out. A module declares `ports`, with `nets` for
physical and `links` for communication; a cell declares the same at its own boundary. The
nets/links split does real work again — the handoff wiring is a net with direction and
active-state rules, the traceability session is a link with a protocol.

Whether `lines/` becomes a fourth registry is **explicitly deferred**. Cells declare boundary
ports now, because that is unavoidable and reusable regardless. A line manifest waits for a
real two-cell job to justify a fourth schema, a fourth registry, and a fourth thing the
composer must render. This is a recorded deferral, not an omission.

## Shape

```yaml
# cells/press-fit-01/cell.yaml
ports:
  - id: upstream-handoff
    domain: electrical
    role: smema-downstream          # this cell receives parts
    signals:
      - {name: part_available,  direction: in,  type: discrete, active: high}
      - {name: ready_to_accept, direction: out, type: discrete, active: high}

  - id: downstream-handoff
    domain: electrical
    role: smema-upstream            # this cell delivers parts
    signals:
      - {name: part_available,  direction: out, type: discrete, active: high}
      - {name: ready_to_accept, direction: in,  type: discrete, active: high}

  - id: safety-chain
    domain: safety
    role: fsoe-slave

  - id: traceability
    domain: communication
    protocol: opc-ua
```

Refusals this admits:

- A `smema-downstream` port whose signal directions do not oppose those of the
  `smema-upstream` port it is netted to
- A handoff net joining two ports of the same role
- A safety-domain net whose endpoints do not both resolve to safety-rated components
- A signal declared without an active state
- A handoff port whose signals do not resolve to real I/O on a transcribed component

## Consequences

- A cell is an independently shippable machine. It can be sold, replaced, or placed next to
  a third-party machine without re-engineering its neighbours.
- Coordinated motion across a cell boundary is not available by default. A line that needs
  it takes the bridge exception and accepts the coupling knowingly.
- The interlock is debuggable with a multimeter. This matters for the same reason readable
  generated code matters: the technician at 02:00 is not the person who built it.
- Cell manifests gain a `ports` block, which the current `cells/` schema does not have. That
  schema is considerably thinner than the module schema and this is the first substantial
  addition to it.
- Three channels means three things to install and three things to get wrong. The refusals
  above are the mitigation; without them this decision trades one failure mode for three.

## Related

ADR-0002 (EtherCAT fieldbus), ADR-0004 (PackML mandatory), ADR-0012 (one refusal engine),
ADR-0015 (module connectivity), ADR-0017 (context is layered), ADR-0020 (carrier identity),
ADR-0021 (journal and record sink)
