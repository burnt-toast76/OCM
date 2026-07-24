# ADR-0015 — Module connectivity: nets, links, and transcribed pins

**Status:** Accepted (schema additions in ADR-0014's registry precede the wiring UI)

## Context

The Modules page can now place component instances into a module assembly. What it cannot
do is say how those components are *connected* — which is most of what makes an assembly a
module rather than a pile of parts. Three tabs are planned (electrical, pneumatic,
communication), and none of them has a backing data model.

Three questions have to be settled before any of that is built, and an audit of the current
schemas against real transcribed components (`com.nordson-kline.dispenser.dp8`,
`com.automation-direct.eps25-100wc-1001`) answers a fourth that was not anticipated:

1. How do component instances relate to the module's geometry?
2. What shape does connectivity take — one model for all three domains, or more than one?
3. Where do pins come from, and who is allowed to create them?
4. Which refusals are actually implementable, given what a datasheet answers?

The fourth question turns out to be the constraining one. A pin today carries `pin`,
`function` (free text, as printed), and `wire_color`. It carries no direction and no signal
class. A component declares a single pneumatic `port` string, so a valve manifold's P/A/B/R
cannot be expressed. And there is no communication connector list at all — DP-8 declares
`protocol: ethercat` and has zero connectors, so an EtherCAT chain is not representable.

## Decision 1 — Instances are placed by pose. The STEP file is a backdrop.

A module's uploaded STEP file is converted whole to a single GLB and used as a visual
reference. Component instances carry their own `pose` in the module's origin frame and are
positioned against that backdrop.

**Rejected:** parsing the STEP assembly tree into node paths and binding each instance to a
node, with placement derived from the node's transform.

That approach reads better on paper — the geometry becomes the source of truth and nobody
types a transform — but it buys a dependency on node path stability across CAD revisions.
Any re-export that renames, reorders, or re-nests a subassembly silently breaks every
binding, which forces a rebind-diff mechanism, a matching heuristic, and a refusal class
that exists only to service the mechanism. It is a large amount of machinery guarding
against a problem that pose placement does not have.

Pose is also already the idiom one layer up: `cell.yaml` places module instances with
`mount.pose`. A module placing component instances by pose is the same operation at a
smaller scale, not a new concept.

**The accepted cost:** the manifest is authoritative for placement and the STEP is
documentation. If they disagree, nothing detects it. This is the same trade the cell
composer already makes, and it is acceptable for the same reason — the manifest is what
generates code, and the geometry is what a human looks at.

## Decision 2 — Electrical and pneumatic are nets. Communication is links.

Two shapes, not one, and not three:

| | Net | Link |
|---|---|---|
| Domains | electrical, pneumatic | communication |
| Endpoints | N, unordered | exactly 2 |
| Models | a common node — a rail, a shared supply line | a cable between two ports |
| Topology | none; membership is the whole story | **derived** by walking, never declared |

A net with N unordered endpoints is the right model for a 24 V rail or an air supply
header: every endpoint on it is at the same potential or pressure, and the order they were
added in means nothing. Bus rails fall straight out of this — a module port is just another
endpoint on the net, and the UI draws it as a rail rather than a pin because of what it is,
not because the data model is different.

Communication is not that. EtherCAT is an **ordered chain**, and the order determines slave
addressing. An unordered net cannot express order, so a module wired as a net would be
unable to say which slave is second. Modelling each cable as a 2-endpoint link and deriving
the chain by walking IN → OUT recovers the order, and — more importantly — the walk is what
makes the chain refusals possible: a slave the walk never reaches, a loop, an OUT port left
dangling with devices beyond it. None of those are detectable in an unordered model.

The derived chain is never stored. It is recomputed from the links on every validate.

## Decision 3 — Module ports are the external interface, and they are design

A module declares `ports`, one entry per external connection it exposes, per domain. These
are what the wiring canvas draws as bus rails, and they are what a cell-level wiring pass
will eventually connect to.

Ports are a **module-layer decision** in the ADR-0014 sense: choosing that a module presents
one 24 V feed rather than three, or one air inlet rather than a manifold per device, is
design judgment, not transcription. A port is therefore authored, not derived from any
component.

## Decision 4 — Pins are transcribed. The wiring UI cannot create one.

Every pin drawn on the wiring canvas comes from a component's own transcribed connector
list. The canvas provides **no path** to create, rename, or add a pin — not a hidden one,
not an "advanced" one.

This is the single most likely place for ADR-0014 to leak, and the leak is predictable in
its shape: someone is mid-wiring, the datasheet is on the desk, adding the pin by hand takes
four seconds and reading it properly takes four minutes. Do that twice and pinouts stop
being transcribed and start being remembered.

A component with no transcribed connectors renders as a card stating the pinout is missing,
carrying the refusal, with a link to that component's authoring page. The missing pinout is
a completion-list item, exactly as ADR-0014 intends — not an obstacle to route around inside
the wiring tool.

## Decision 5 — Refusals are limited to what is transcribed

The refusal set is bounded by the fields that exist. Inferring a pin's direction from free
text like `"OUT1 (switching output)"` would be the module layer doing transcription's job,
which is the failure ADR-0014 was written to prevent.

Implementable against the current schema — structural only:

| Refusal | Basis |
|---|---|
| net with fewer than 2 endpoints | membership |
| pin appearing in more than one net | membership |
| endpoint naming an unknown refdes, connector, or pin | resolution |
| instance whose component declares no connectors | absence |
| module port declared but internally unconnected | membership |
| link with other than exactly 2 endpoints | shape |
| protocol mismatch across a link | comms connector `protocol` |
| EtherCAT chain not reaching a master, loop, dangling OUT | derived walk |

Deferred until the supporting field is transcribed:

| Refusal | Requires | Datasheet-answerable? |
|---|---|---|
| two driving pins on one net | pin `direction` | Yes — pinout tables state it |
| signal-class mismatch on a net | pin signal class | Yes |
| required pin left unconnected | pin `required` | Yes |
| pneumatic port function/size mismatch | `pneumatic.ports[]` list | Yes |
| net pressure above an endpoint's rating | existing `pressure_max` + ports | Yes |
| comms chain of any kind | `comms.connectors[]` with `role` | Yes |

All six are datasheet-answerable, so all six belong in the **component** schema and are
added there, not worked around at the module layer. Until each lands, the corresponding
refusal does not exist and is not faked.

## Shape

Endpoints reference existing field names — `refdes` from the module's `components:` list,
`ref` and `pin` from the component's own connector entries. No renaming, no alias layer.

```yaml
ports:
  - {id: PWR_IN, domain: electrical, type: M12-A-4P}
  - {id: AIR_IN, domain: pneumatic, thread: G1/8, function: supply}
  - {id: NET_IN, domain: communication, protocol: ethercat, role: slave_in}

nets:
  electrical:
    - id: N_24V
      endpoints:
        - {port: PWR_IN, pin: '1'}
        - {refdes: PS1, connector: electrical, pin: '1'}
  pneumatic:
    - id: C_SUPPLY
      pressure: 6
      pressure_units: bar
      endpoints:
        - {port: AIR_IN}
        - {refdes: DP1, connector: air_in}

links:
  - {id: L_EC_1, protocol: ethercat,
     a: {port: NET_IN}, b: {refdes: DP1, connector: X1}}
```

`nets` and `links` are optional. A module that declares neither stays valid, the same way a
module with no `components:` list stays valid under ADR-0014 — a purchased device that is
genuinely a whole module has no internal wiring to describe.

## Consequences

- **Component schema grows** `pneumatic.ports[]` (label, thread, function) and
  `comms.connectors[]` (ref, type, protocol, role). Pin `direction` is added when the
  contention refusal is wanted. The component authoring agent asks for all of them; absence
  stays absence.
- **`ComponentConnector` must carry `pins`.** It currently does not — the schema and the
  on-disk YAML both have them, and the typed model drops them, leaving the resolver blind to
  every pinout. Server-side refusal (ADR-0012) is impossible until this is fixed. A
  schema-vs-model coverage test should make this class of bug unfindable by hand.
- **One wiring canvas, parameterized by domain**, not three. Electrical and pneumatic differ
  in what an endpoint is called and what a net carries; communication differs in arity and
  in drawing a derived overlay. None of that justifies three implementations.
- **Chain order is derived, never authored.** No `position` or `index` field appears
  anywhere in `links`. If the walk cannot determine an order, that is a refusal, not a
  prompt for the user to supply one.
- **A cell-level wiring pass becomes possible later** on the same two shapes: module ports
  are already the boundary objects, so connecting modules to each other is the same
  operation one layer up. Out of scope here; the port model is chosen so it does not have to
  change.
