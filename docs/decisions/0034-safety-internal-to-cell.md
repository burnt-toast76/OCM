# ADR-0034 — The safety domain does not cross a cell boundary

**Status:** Proposed

**Supersedes in part:** ADR-0019 D1 (safety as a boundary channel)
**Errata:** ADR-0026 D5 (`safety` as a cell port)

## Context

ADR-0019 D1 named three channels crossing a cell boundary: safety, handoff interlock, and
data. ADR-0026 D5 then modelled the safety chain as a net between cells, and by its own D1
rule anything netted across a boundary is a port — giving the cell manifest a
`{id: safety-chain, domain: safety, role: fsoe-slave}` entry.

That shape has a consequence nobody chose. A net is N unordered endpoints sharing one common
node (ADR-0026). There is no partitioning vocabulary in the manifest — no zone, no group, no
scope. So `safety-chain` on every cell in a line resolves to a single node, and an E-stop
anywhere drops power everywhere. A three-cell line where cell 03 cannot run because someone
pressed a button on cell 02 contradicts ADR-0019's own stated consequence that a cell is an
independently shippable machine.

It also left a live three-way contradiction: ADR-0019 D1 offers FSoE for the safety channel,
ADR-0019 D2 prohibits any EtherCAT segment crossing a cell boundary, and `spec/06` excludes
FSoE from v1. FSoE rides on EtherCAT, so D1 and D2 cannot both hold.

The target installations resolve this by construction. Cells are physically distinct. No
robot reaches across a boundary. No conveyor spans one. No resource is shared. The only thing
that crosses is the carrier itself, and it crosses under the handoff interlock. Given that,
there is no hazard in cell 02 that cell 01's safety function needs to control, and the reason
for a shared chain disappears.

## Decision 1 — Every safety net endpoint resolves within the declaring cell

The `safety` domain is internal. A safety net may join any number of endpoints inside one
cell; it may not name an endpoint in another cell, in a line manifest, or in any scope above
the cell.

`domain: safety` is therefore removed from the cell `ports` list. A port is a connection point
at a boundary, and safety no longer reaches one. A cell boundary carries two things: the
handoff interlock and the data link.

This makes the guarantee structural rather than procedural. The manifest cannot express a
cross-cell safety dependency, so one cannot be built by accident. That sentence is the one to
put in front of a safety validator.

The FSoE contradiction closes as a side effect. Nothing needs a safety transport across a
boundary, so ADR-0019 D2 stands unchallenged and `spec/06` is satisfied without a decision.

## Decision 2 — The interlock carries the consequence, and it is not a safety function

An E-stop in one cell reaches its neighbours as information, not as loss of power.

A cell entering a safe state deasserts both handoff signals: `part_available` to its
downstream neighbour and `ready_to_accept` to its upstream neighbour. Material stops crossing
in both directions. Nothing else propagates.

This is fail-safe by construction and needs no added logic. ADR-0019 declares both handoff
signals `active: high`, so a cell whose outputs are de-energised asserts nothing, and both
neighbours read that as "not available" and "not ready." A cell that is dead, powered down,
or disconnected is indistinguishable from a cell that is stopped — which is the correct
reading in all three cases.

**The interlock is an availability signal and must not be documented, generated, or certified
as a safety function.** It is not safety-rated, it does not appear in the risk assessment, and
no protective measure may depend on it. ADR-0019 D1's prohibition on safety being inferred
from or carried by a lower channel is unchanged by this ADR and is restated here because the
behaviour above will invite exactly that misreading.

## Decision 3 — A blocked neighbour is Suspended, not faulted

A cell that cannot hand off, or cannot receive, completes the cycle in progress and every
further cycle for which it already holds material. It then comes to rest at a clean cycle
boundary in the PackML **Suspended** state — stopped by an external condition, machine still
ready — never Held and never Aborted.

Suspended is self-clearing. When the neighbour's interlock reasserts, the cell transitions
Unsuspending → Execute on its own. Restarting a line after a single-cell E-stop therefore
requires one deliberate local safety reset at the stopped cell and no coordinating action
anywhere else. Line resumption is emergent, not orchestrated.

The observable behaviour is an effective pause that propagates outward at the rate material
is consumed, not an immediate line stop.

## Decision 4 — Each cell guards its own side of the transfer aperture

The seam between two cells has an opening wide enough to pass a carrier, and therefore wide
enough to reach through. It is not one shared aperture owned jointly; it is two apertures back
to back, each inside its own cell's safety scope, each guarded by the cell whose hazardous
motion is reachable through it.

A cell declaring a handoff port must declare the guarding for its own side. This keeps D1's
disjointness intact — no guard device is shared, no safety net crosses — while leaving no
hazard without a declared owner.

Physical separation is an install-time property, not a CAD-time one. A cell declares the
minimum separation its guarding assumes, so that a customer bolting two cells closer than
that is a commissioning refusal rather than an undetected assumption.

## Decision 5 — A line-level E-stop is a replicated local input, never a net

Where a single button must stop the whole line, it is wired as a hard-contact input to every
cell and declared as a local safe input in each cell's manifest. Each cell evaluates it in its
own safety logic and reaches its own stop state independently.

It is not a net, not a port, and not a shared node. D1's invariant holds unchanged: no
endpoint of any safety net lies outside its cell. A line E-stop is N independent local
functions that happen to share a button.

## Shape

```yaml
# cells/screwdrive-01/cell.yaml
ports:
  - {id: upstream-handoff,   domain: electrical,    type: smema-14, role: smema-downstream}
  - {id: downstream-handoff, domain: electrical,    type: smema-14, role: smema-upstream}
  - {id: traceability,       domain: communication, protocol: opc-ua}
  # no safety port — D1

safety:
  stop_category: 1                    # declared, never defaulted
  reset: manual-local
  nets:
    - id: N_ESTOP
      domain: safety
      endpoints:
        - {instance: hmi-panel,   port: ESTOP}
        - {instance: safety-logic, port: SI_1}
    - id: N_GUARD_INFEED
      domain: safety
      endpoints:
        - {instance: infeed-curtain, port: OSSD}
        - {instance: safety-logic,   port: SI_2}
  inputs:
    - {id: SI_LINE_ESTOP, source: line-hardwired, replicated: true}   # D5
  apertures:
    - port: upstream-handoff
      guarded_by: infeed-curtain
      min_separation_mm: 0
    - port: downstream-handoff
      guarded_by: outfeed-tunnel
      min_separation_mm: 0

on_safe_state:
  deassert: [part_available, ready_to_accept]     # D2
  packml: Suspended                                # neighbours, D3
```

## Refusals this admits

| Code | Condition |
|---|---|
| `OCM_SAFETY_NET_CROSSES_CELL` | A safety net endpoint resolves outside the declaring cell |
| `OCM_SAFETY_PORT_DECLARED` | A cell `ports` entry with `domain: safety` (superseded shape) |
| `OCM_SAFETY_NO_STOP_CATEGORY` | `safety.stop_category` absent |
| `OCM_SAFETY_ENDPOINT_NOT_RATED` | A safety net endpoint does not resolve to a safety-rated component |
| `OCM_SAFETY_APERTURE_UNGUARDED` | A handoff port with no matching `apertures` entry |
| `OCM_SAFETY_SEPARATION_UNDECLARED` | An aperture without `min_separation_mm` |
| `OCM_HANDOFF_NOT_FAIL_SAFE` | A handoff signal declared `active: low` |

`OCM_HANDOFF_NOT_FAIL_SAFE` is the one worth keeping visible. D2's whole guarantee rests on
active-high signalling, and an active-low handoff would silently invert it — a dead cell would
assert availability.

## Rejected alternatives

**Safety zones as a line-level object.** A `lines/` registry with zones, cell membership, and
`reaches_into` declarations for cross-boundary motion. Correct for lines where a robot reaches
across a seam or a conveyor spans cells. Rejected because the target installations have
neither, and it would build a fourth registry and a zone resolver to express a partition that
is already one-to-one with cells. Revisit if a job ever requires shared mechanism across a
boundary — the vocabulary above does not preclude it.

**A shared chain with a documented operating procedure.** Keep the global net, accept that the
line stops together, and handle it in the manual. Rejected because it makes cell 03's
availability depend on cell 02's button, which is the coupling ADR-0019 exists to prevent, and
because it is enforced by prose rather than by refusal.

**Propagating safe state over the data link.** Cell 02 publishes its safety status; neighbours
subscribe and stop. Rejected outright — this is ADR-0019 D1's prohibited case, an unrated
protective function riding an availability channel.

## Consequences

- **The cell schema loses a port entry and gains a `safety` block.** The block is substantial:
  nets, inputs, apertures, stop category, reset mode.
- **The FSoE question is closed by removal,** not by decision. `spec/06`'s v1 exclusion needs
  no revisiting and ADR-0019 D2 needs no exception.
- **A cell is now genuinely independently shippable.** Nothing outside it can prevent it from
  running. This is the claim ADR-0019 made and this ADR is what makes it true.
- **Line behaviour on a single-cell stop is derivable from the manifests alone** — no line
  manifest, no coordinator, no orchestration. The pause propagates as material is consumed.
- **A carrier stranded at a seam is an open case.** If a cell stops between the interlock
  handshake and the carrier fully arriving, ownership on resume is ambiguous. ADR-0020's
  bind/unbind lifecycle already refuses on a stale binding; whether that refusal fires
  correctly for a half-completed transfer is untested and should be a cold-test case before
  this ADR moves to Accepted.
- **The safety validator sees a simpler system,** and the argument is structural: the schema
  cannot express a cross-cell safety dependency.
