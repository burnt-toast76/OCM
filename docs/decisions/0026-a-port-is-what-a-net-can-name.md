# ADR-0026 — A port is what a net can name. Everything else is a subsystem block.

**Status:** Accepted, with Errata 1–2 — see the end of this document. Erratum 1 (2026-08-03):
the Shape block's `{sink: record_sink}` link endpoint contradicted D1's own test (a link named
a non-port); the erratum retires it — the `traceability` port is the endpoint, and the sink is
reached from the port via `record_sink.port`. Erratum 2 (2026-08-04, from ADR-0034): D5's
premise — a safety chain netted between cells — no longer holds; the Shape block's
`safety-chain` port is withdrawn, and `domain: safety` names no cell port. Supersedes the
`ports` shapes in ADR-0019 and ADR-0020; retroactively justifies ADR-0024's `mode_selector`.
Prerequisite to the `cells/` schema.

## Context

`ports` currently means three incompatible things.

**ADR-0015 (module).** A flat connection point — `{id, domain, type}`. It holds no
connectivity. Nets and links name it as an endpoint from outside: `{port: PWR_IN, pin: '1'}`.

**ADR-0019 (cell).** A port carrying a nested `signals[]` array, each with `name`,
`direction`, `type`, and `active`. Connectivity is partly inside the port.

**ADR-0020 (cell).** `domain: identification`, carrying a nested `carrier:` block plus
`read_at`, `on_mismatch`, `on_absent`. Nothing can be netted to it at all. It is reader
configuration wearing a connectivity noun.

ADR-0019 asserts that it applies ADR-0015's vocabulary one scope out. It does not — it is a
different shape, and the assertion is what let the divergence pass unnoticed. ADR-0024 then
put `mode_selector` at the top level rather than making it a port, which was the right
instinct with no stated rule behind it: a keyswitch is as much a physical boundary input as a
safety chain, and nothing said why one is a port and the other is not.

Ten deferred design-phase refusals across ADRs 0019, 0020, 0021, and 0024 are blocked on a
`cells/` schema (`docs/refusal-audit.md` §3). That schema cannot be written first. JSON
Schema is where an ambiguity stops being a documentation problem and becomes a migration.

## Decision 1 — A port is an endpoint that a net or a link can name

One test, one shape, every layer:

> If a `net` or a `link` can name it as an endpoint, it is a **port**. If it cannot, it is
> not a port, whatever else it is.

`ports` therefore keeps ADR-0015's shape unchanged at both scopes: an identifier, a domain,
and the domain's own descriptor. It holds no connectivity, no signal list, and no behaviour.

## Decision 2 — Everything else is a subsystem block

Top-level siblings of `ports`, not entries within it:

| Block | ADR | Why not a port |
|---|---|---|
| `identity` | ADR-0020 | Reader configuration. Nothing is netted to a reader; it reads a tag that arrives on a carrier. |
| `carriers` | ADR-0020 | A fleet declaration. Not a boundary object at all. |
| `record_sink` | ADR-0021 | Where records drain. Declared, not wired. |
| `produces` | ADR-0021 | What the cell measures. Derived from components, not connected to anything. |
| `mode_selector` | ADR-0024 | A keyswitch **is** wired — but to this cell's own safety circuit, not across a boundary. Its I/O point resolves like any other; the mode declaration is behaviour. |

`domain: identification` is deleted. It existed only to let a configuration block sit in a
list of connection points.

**Rejected: make everything a port**, on the grounds that it keeps one list. It forces
invented domains for things that connect to nothing, and it makes `ports` mean "boundary-ish
stuff," which is what we are here to stop.

## Decision 3 — Cell port pins resolve downward. Handoff signals are pins, not port fields.

A handoff is **one port** — one connector, one cable — with pins, exactly like a module port.
ADR-0019's `signals[]` array is removed. The two SMEMA signals become pins named by nets:

Where a module port's pins resolve to a component's transcribed connector pins (ADR-0015 D4),
a **cell** port's pins resolve to the module ports of the modules it contains. That is
ADR-0017's reference-downward rule doing the work: component → module → cell, each layer
naming the layer below, none restating it.

The consequence is that ADR-0015 D4 now holds at the cell layer too, without being restated:
**a cell's wiring surface cannot create a pin either.** A handoff pin exists because a module
exposes it, which exists because a component was transcribed.

## Decision 4 — `direction` is derived. `active` is declared.

ADR-0019 declared `direction` inline on cell signals while ADR-0015 D5 deferred pin
`direction` at the component layer as untranscribed. Both cannot be right, and the module
layer is the one with the honest position.

- **`direction`** is a fact about the underlying I/O point. It is transcribed at the
  component layer and derived upward. It is not declared at the cell layer, and until the
  component pin field lands, direction-dependent refusals do not exist and are not faked.
- **`active`** (high/low) is a design choice the integrator makes about a net. It is declared
  on the **net**, not on the port and not on the pin.

This makes an existing dependency visible rather than creating one.
`OCM_HANDOFF_DIRECTION_MISMATCH` and `OCM_HANDOFF_PORT_NO_IO` currently record only the cell
schema as their blocker; both also require component pin `direction`, the same field
`OCM_NET_TWO_DRIVERS` correctly names. Writing the cell schema will not light them up, and
the catalogue should say so.

## Decision 5 — `safety` stays a port; the FSoE question is untouched

*(Erratum 2: the premise below no longer holds — ADR-0034 makes the safety domain internal to
a cell, so no safety chain is netted between cells and `domain: safety` names no cell port.
The decision record this section anticipated is ADR-0034. See the end of this document.)*

A safety chain is netted between cells, so by D1 it is a port. Nothing here settles ADR-0019
D1's offer of FSoE against D2's prohibition on EtherCAT crossing a boundary, or against
spec/06's "FSoE… not for v1." That is a separate, real contradiction and it gets its own
decision record. This ADR is about shape, not transport.

## Shape

```yaml
# cells/press-fit-01/cell.yaml
ports:
  - {id: upstream-handoff,   domain: electrical,    type: smema-14,  role: smema-downstream}
  - {id: downstream-handoff, domain: electrical,    type: smema-14,  role: smema-upstream}
  - {id: safety-chain,       domain: safety,        role: fsoe-slave}   # withdrawn — see Erratum 2
  - {id: traceability,       domain: communication, protocol: opc-ua}

nets:
  electrical:
    - id: N_HANDOFF_IN_AVAIL
      active: high
      endpoints:
        - {port: upstream-handoff, pin: '1'}
        - {instance: infeed, port: DI_IN, pin: '3'}     # resolves into a module port

links:
  - {id: L_TRACE, protocol: opc-ua, a: {port: traceability}, b: {sink: record_sink}}

identity:
  reader: fixture.rfid-head
  protocol: iso-15693
  carrier_id_source: uid
  unit_id_source: user_memory
  read_at: entry
  on_mismatch: refuse
  on_absent: refuse

carriers:      {…}   # ADR-0020
record_sink:   {…}   # ADR-0021
produces:      {…}   # ADR-0021
mode_selector: {…}   # ADR-0024
```

Refusals this admits:

- A `ports` entry carrying a nested `signals` list (the superseded ADR-0019 shape)
- A `ports` entry with `domain: identification` (the superseded ADR-0020 shape)
- A net endpoint naming a cell port pin that no contained module port exposes
- `active` declared on a port or a pin rather than on a net
- `direction` declared anywhere at the cell layer

## Consequences

- **The `cells/` schema is unblocked**, and it inherits the module schema's port shape rather
  than inventing a second one. The wiring canvas ADR-0015 parameterised by domain becomes
  reusable one scope up, which is what ADR-0019 D5 predicted and the divergent shape would
  have prevented.
- ADR-0019's and ADR-0020's Shape blocks are superseded. Their decisions stand; the YAML
  written under them does not. Both get a status line pointing here — the ADR-0015 Erratum 1
  pattern.
- Two catalogue entries gain a second blocker in `requires`. This makes the cell-schema work
  honest about what it will and will not light up.
- `OCM_SIGNAL_NO_ACTIVE_STATE` moves from the port to the net and its message changes.
- A fourth layer, if `lines/` ever lands (ADR-0019 D5), inherits the same test rather than
  inventing a fourth shape. That is the whole return on doing this now.

## Related

ADR-0015 (module connectivity), ADR-0017 (context is layered), ADR-0019 (cell interconnect),
ADR-0020 (carrier identity), ADR-0021 (journal), ADR-0024 (command authority),
ADR-0025 (refusal phases and catalogue)

---

## Erratum 1 (2026-08-03) — the `sink` endpoint let a link name a non-port

Found while wiring the cell schema's endpoint shape into the refusal audit: the schema (and
`ocm_core.cell.Endpoint`) let a link endpoint say `{sink: record_sink}`, following this ADR's
own Shape block (`L_TRACE`).

**What was wrong.** Decision 1 is a partition: what a net or link can name is a port; what it
cannot name is not one. Decision 2 then made `record_sink` a subsystem block — not a port. The
Shape block contradicted both by having a link name the sink directly, so the one test this ADR
exists to state no longer partitioned cleanly: a link could name a non-port, and `record_sink`
was half a port after all. The schema faithfully implemented the contradiction.

**Correction — the `traceability` port is the link endpoint; the sink is reached from the
port, not named directly.** A link endpoint names a port (a cell `ports[].id`, or a contained
module's port via `{instance, port, pin}`) and nothing else. The `sink` field is removed from
the endpoint shape. Where the record sink drains through the cell boundary, that association is
declared on the **subsystem block**, pointing at the port — `record_sink.port: traceability` —
which is the same reference-downward direction every other block uses. The Shape block's
`L_TRACE` link is retired, not rewired: a link with only one real end was never a link.

**Refusal this admits.** A link endpoint naming a non-port. With `sink` removed the schema
enforces this structurally (`additionalProperties: false` on the endpoint), surfacing as
`OCM_SCHEMA_INVALID`; catalogued as `OCM_LINK_ENDPOINT_NOT_A_PORT` so the rule has a name.

**Unchanged.** Decision 1's test, verbatim — this erratum exists to keep it intact rather than
carve out an exception. Decision 2's block list (`record_sink` stays a subsystem block).
Decision 3's downward pin resolution. The `endpoint` shape's other fields.

## Erratum 2 (2026-08-04) — D5's premise no longer holds: no safety chain is netted between cells

Recorded when ADR-0034 landed. This is the "separate, real contradiction" D5 itself deferred
to its own decision record; ADR-0034 is that record, and it resolves the question by removing
the premise rather than choosing a transport.

**What was wrong.** D5 reasoned soundly from a shape it inherited: ADR-0026 modelled the
safety chain as a net between cells, and by D1's own test anything netted across a boundary
is a port. But a net is N unordered endpoints sharing one common node, and the manifest has no
partitioning vocabulary — so `safety-chain` on every cell in a line resolves to a single node,
and an E-stop anywhere drops power everywhere. That contradicts ADR-0019's own consequence
that a cell is an independently shippable machine, and it left ADR-0019 D1's FSoE offer,
ADR-0019 D2's prohibition on EtherCAT crossing a boundary, and spec/06's v1 exclusion in a
standing three-way contradiction.

**Correction — the safety domain is internal to a cell (ADR-0034 D1).** Every safety net
endpoint resolves within the declaring cell; no safety net, port, or shared node crosses a
boundary. The Shape block's `{id: safety-chain, domain: safety, role: fsoe-slave}` entry is
**withdrawn** (annotated above, not silently rewritten). A cell boundary carries the handoff
interlock and the data link, and an E-stop reaches neighbours as deasserted handoff signals —
information, never loss of power, and never a safety function (ADR-0034 D2).

**Unchanged.** D5's reasoning about port-vs-net SHAPE stands for every other domain: what a
net can name is a port, and the test partitions exactly as D1 states it. D1–D4 and both
Shape-block handoff/traceability ports are untouched. The FSoE question closes by removal —
nothing needs a safety transport across a boundary — so spec/06's v1 exclusion and ADR-0019 D2
stand without exception.
