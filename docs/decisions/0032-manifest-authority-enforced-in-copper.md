# ADR-0032 — Manifest authority is enforced in copper

**Status:** Proposed. Extends ADR-0024's manifest-authority axis with a physical enforcement
layer. Does not amend ADR-0022, and does not touch the certification boundary held in
`spec/06-safety.md` — nothing here is a safety function.

## Context

ADR-0024 split authority onto two axes: changing what the machine *is* (manifest authority)
and telling it to do something it is already declared able to do (command authority). The
split is right and the refusal engine implements it. But every enforcement layer built so far
is software. ADR-0012 makes that a virtue — one refusal engine, three clients — and it is a
virtue right up until someone asks what happens when a client stops going through the API.

Three things are wrong with software-only enforcement here.

**ADS is routed, not port-bound.** A route entry in `StaticRoutes.xml` that nobody audited is
an authority path that the refusal engine never sees, because the refusal engine is not in
that path. The single-surface guarantee holds for clients of the surface. It says nothing
about a client that isn't one.

**The argument is not sellable.** A customer evaluating whether an AI system may touch their
line is not evaluating our architecture; they are evaluating their exposure. An architecture
diagram answers "we thought about this." It does not answer "it cannot happen." Those are
different products, and only one of them closes.

**"The agent can't change the program" hides two claims.** Downloading logic is one thing.
Writing tag values that change behaviour without touching logic is another. A gate on the
engineering port stops the first and not the second — a strong door next to an open window.

There is also a plain observation: the cell already has a safety-rated mode selector, because
ISO 10218 requires one, and ADR-0026 D2 already put `mode_selector` at cell top level as a
subsystem block. The signal we need exists and is already declared. We are not adding a
mechanism; we are terminating one we already own.

## Decision 1 — The engineering link is a permissive, not a firewall rule

The physical link carrying ADS to the cell is powered through a contact that closes only in
PROGRAM. In AUTO and in MANUAL the link is down at layer 1 — not filtered, not dropped, not
authenticated-and-denied. Down.

Wire it as a permissive: energize to allow. Never as an inhibit. Loss of the wire must leave
writes blocked, not enable them.

## Decision 2 — The permissive is driven by a safe output, and it is not a safety function

The mode selector lands on a safe input terminal, TwinSAFE logic derives the permissive, and
a safe output drives the interrupting relay. We take this route for three properties we would
otherwise have to build: fail-safe behaviour by construction, dark-test diagnostics, and a
logged, inspectable state.

We do **not** claim it as a safety function. It performs no risk reduction, it enters no risk
assessment, and it must be documented as a non-safety load on a safety-rated output so that
the person validating the cell is not surprised by it. Borrowing the hardware's properties is
not the same as extending the hardware's scope.

The TwinSAFE project carries its own CRC and its own login, separate from the standard
runtime. The layer that gates the engineering port therefore cannot be modified through the
engineering port. That is the property that closes the loop, and it is the sentence to put in
front of a customer.

## Decision 3 — Observation rides a physically unidirectional channel

Diagnosis, explanation, and the whole read half of ADR-0022 must keep working while the cell
runs. They ride a separate channel that is unidirectional in copper: the PLC publishes a
fixed state frame at a fixed rate out a serial terminal, and the return conductors are absent
from the cable.

Serial, not fiber. A single-strand fiber pair generally will not establish link — most
converters need RX before they transmit, and link-fault pass-through kills the TX side too.
RS-422 has no negotiation to defeat, costs less, and the missing conductor is visible to a
person standing at the panel.

The consequence is that the read path is publish-only. No request/response, no query surface,
no acknowledgement. The manifest already bounds the tag set, so "publish everything" is a
known finite frame rather than an open question. Design to that; do not reintroduce a request
channel to work around it.

## Decision 4 — Mode knowledge is for message quality, never for enforcement

The mode word travels in the published frame, so the refusal engine knows the cell is in AUTO
and can say so. That knowledge exists to make the refusal legible — `OCM_WRITE_PATH_DOWN`
instead of a TCP timeout — and for no other purpose.

Three layers hold independently:

1. The API refuses the verb.
2. The PLC rejects the write.
3. The conductor is open.

Each is sufficient alone. None may be implemented in a way that depends on another, and in
particular no layer may be relaxed on the grounds that a lower one will catch it.

## Decision 5 — The cell declares the link, so a mismatch is refusable

An unaudited ADS route makes the relay decorative. The cell therefore declares what the
enforcement path is supposed to be, the live route count is published through the diode, and
a mismatch refuses at load.

## Shape

```yaml
# cells/press-fit-01/cell.yaml
mode_selector:
  channels: 2
  positions: [program, manual, auto]
  safe_input: EL1904

engineering_link:
  permissive_from: EL2904.1        # safe output driving the interrupting relay
  interrupt_device: K1             # forcibly-guided; contact in the 24 V feed
  closed_in: [program]             # the only positions in which writes are possible
  ads_routes_expected: 1           # audited; live count arrives on the read path
  observation:
    transport: rs422
    terminal: EL6021
    conductors: [tx_p, tx_n]       # rx absent from the cable — this is the diode
    frame_rate_hz: 10
```

`closed_in` is declared rather than assumed so that a cell which legitimately allows writes in
MANUAL — a bench cell, a development frame — says so in the manifest instead of quietly
differing from the shipped configuration.

## Consequences

**What this buys.** The IP question gets a physical answer. A customer can be shown the absent
conductor. An auditor gets one sentence. Neither depends on trusting our software, which is
the only kind of assurance that survives a procurement review.

**What this does not cover.** Writes on the process network — setpoints, recipe selection, HMI
tags — change cell behaviour without touching the program and are entirely outside this
decision. They remain governed by ADR-0024's command-authority axis in software. Do not cite
ADR-0032 as though it covered them.

**Development friction is the point.** Every program download now requires a physical mode
change. This is not incidental cost to be engineered away; it is the mechanism. Any proposal
to add a software bypass for convenience is a proposal to delete this ADR.

**Serial bandwidth bounds the frame.** 115.2 kbaud at 10 Hz is roughly a 1 kB frame. That is
ample for the declared tag set today and is a real ceiling later. When it binds, raise the
baud rate or lower the rate — do not add a second channel.

**Panel scope grows.** `hardware/panel/` acquires its first real contents: the relay, the safe
output wiring, and a cable specification whose defining feature is a conductor that is not
there.

## Related

- **ADR-0012** — one refusal engine, three clients. This adds a fourth layer *below* the API,
  not a fourth client of it.
- **ADR-0022** — the read half of the diagnosis case is what Decision 3 exists to preserve.
- **ADR-0024** — supplies the manifest-authority axis this enforces, and retains sole
  authority over command-axis writes.
- **ADR-0026 D2** — `mode_selector` is a subsystem block, not a port. `engineering_link` is
  declared beside it for the same reason: it is wired to this cell's own circuit, not across a
  boundary.
- **`spec/06-safety.md`** — the STO architecture makes the same argument for the same reason:
  a physical wire, not a network message.
