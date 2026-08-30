# ADR-0025 — One refusal source, three evaluation phases

**Status:** Accepted. Amends ADR-0012's singularity claim; adds an audit obligation to
ADR-0019, ADR-0020, ADR-0021, ADR-0022, ADR-0023, and ADR-0024.

## Context

ADR-0012 put the refusal engine server-side and called it singular. ADR-0016 sharpened that
into one validation verb that means validated. Both were reasoning about design time, when
design time was all there was.

ADRs 0019–0022 and 0024 then introduced refusals that cannot run there: buffer full, journal
unwritable, tag write read-back mismatch, carrier arriving with a live binding, `manifest_sha`
mismatch, a command outside declared bounds. These execute on the machine, most of them
inside cycle time, in generated PLC and coordinator logic. There is no laptop and no Python
service in the loop.

So "the refusal engine is singular and server-side" is now false as written, and each of
those ADRs closes with an undifferentiated list mixing checks that run in three different
places. ADR-0021 lists "a measurement declared without a unit" — pure schema — next to
"buffer full." ADR-0022 lists diagnostic queries that answer partially, which are not
refusals at all.

The property ADR-0012 was actually protecting survives this. Nothing in 0019–0022 and 0024
re-implements a design-time check at runtime. No rule is written twice. What grew a second
meaning was the word, not the architecture — but the word is load-bearing, and leaving it
ambiguous is how a second implementation eventually appears without anyone deciding to build
one.

## Decision 1 — Singular means one *source*, not one *process*

ADR-0012's claim is restated:

> There is one source of refusal rules. Every engine that evaluates them derives from that
> source. No rule is authored twice, in any language, for any target.

Three phases evaluate that source:

| Phase | Inputs | Executes in | Examples |
|---|---|---|---|
| **design** | manifests only | `ocm-resolve` / `validate_*`, anywhere | schema, connectivity, unresolvable endpoint, port unconnected, measurement without a unit |
| **load** | manifests + machine environment, once at start-up or state transition | the same Python engine, running on the machine | journal path unwritable, `manifest_sha` mismatch, manifest root unreadable, regenerate-and-verify |
| **cycle** | live machine state, inside the cycle path | generated PLC / coordinator logic | buffer full, tag read-back mismatch, stale carrier binding, starve/block, parameter outside bounds |

**design** and **load** share an implementation outright — ADR-0022 D5 already puts manifests
and the service on the machine, so this is a deployment difference, not a second engine.

**cycle** rules are *generated from manifests* by Cellwright's generator. They execute
elsewhere because they must, but they are emitted from the same catalogue, with the same
codes, and carry rung-level provenance back to it. One source, two implementations, zero
hand-written duplicates.

## Decision 2 — Rejected: route cycle checks through the Python service

The tidy-looking alternative is to have the coordinator call `ocm-api` for every check so
there is literally one process. It is rejected on two grounds.

It puts a network or IPC hop inside cycle time, which is the same mistake ADR-0021 D1
rejected for the record store and for the same reason: a service restart becomes a production
stoppage.

More decisively, ADR-0019 D4 requires the interlock to be derived rungs executing in the PLC.
A handshake that depends on a Python process being up is not an interlock. The debuggable-
with-a-multimeter property that ADR-0019 bought would be spent immediately.

## Decision 3 — Outcome is a declared property, not a per-site judgement

ADR-0021 D6 established that degrading is permitted when it is legible and absorbing is not.
That distinction is currently prose in one ADR. It becomes a field.

- **`refuse`** — the operation does not proceed. The default and the overwhelming majority.
- **`degrade`** — the operation proceeds and the degradation is recorded as a fact on the
  event. Permitted **only** where a query can later identify every affected unit. This is
  ADR-0021 D6, generalised.
- **`advise`** — surfaced to a human, no gating. ADR-0022 D6 diagnostics are `advise`. They
  currently sit in a refusal list and are not refusals; naming that stops them from drifting
  into gating behaviour by proximity.

A `degrade` entry without a recorded field is a defect. That is the entire content of "we do
not absorb," made checkable.

## Decision 4 — The catalogue is OCM. The engines are Cellwright.

ADR-0018 draws its line at `spec/` versus `software/`, and the refusal catalogue lands
squarely on it. The line is drawn deliberately here rather than by accident.

The **vocabulary** — codes, phases, outcomes, meanings — is the standard. A third party
writing their own generator against OCM manifests must be able to emit `OCM_NET_UNDER_TWO_
ENDPOINTS` and have it mean what it means here. A standard whose conformance signals are
private to one implementation is not independently implementable, which is ADR-0018's test.

The **engines** — the resolver, the generator's rung emission, the coordinator — are
Cellwright.

Location: `spec/11-refusals.md` (prose and rationale) with the machine-readable catalogue at
`spec/schema/ocm-refusals-1.0.yaml`. Codes are namespaced `OCM_`.

## Shape

```yaml
# spec/schema/ocm-refusals-1.0.yaml
OCM_NET_UNDER_TWO_ENDPOINTS:
  phase: design
  outcome: refuse
  adr: ADR-0015
  layer: module
  message: "Net {net_id} has {n} endpoint(s); a net requires at least 2"

OCM_MANIFEST_SHA_MISMATCH:
  phase: load
  outcome: refuse
  adr: ADR-0022
  layer: cell
  message: "Deployed manifest {manifest_sha} does not match running program {program_sha}"

OCM_CARRIER_STALE_BINDING:
  phase: cycle
  outcome: refuse
  adr: ADR-0020
  layer: cell
  message: "Carrier {carrier_id} arrived at load with live binding {unit_id}"

OCM_BINDING_UNVERIFIED:
  phase: cycle
  outcome: degrade
  adr: ADR-0021
  layer: cell
  records: binding_verified          # REQUIRED when outcome is degrade
  message: "Store unreachable; binding for {unit_id} not cross-checked"

OCM_DIAGNOSTIC_SOURCE_UNAVAILABLE:
  phase: cycle
  outcome: advise
  adr: ADR-0022
  layer: cell
  message: "Journal unavailable; answering explanation only, not diagnosis"
```

Refusals this admits (about the catalogue itself, checked in CI):

- A catalogue entry with `outcome: degrade` and no `records` field
- A code emitted by any engine that does not appear in the catalogue
- A catalogue entry no engine emits and no ADR cites — dead vocabulary
- A code whose `phase` is `design` emitted from generated cycle logic, or vice versa

## Consequences

- **An audit obligation falls due immediately.** Every refusal listed in ADR-0019, 0020,
  0021, 0022, 0023, and 0024 is tagged with a code, a phase, and an outcome. This is expected
  to surface entries with no phase that can evaluate them — ADR-0020's fleet-endurance and
  duplicate-identity-creation checks are line-scoped and ADR-0019 D5 deferred the line layer,
  so they have nowhere to run. Better to find that in a table than in commissioning.
- ADR-0016 is unaffected and its argument gets stronger. One `validate_module` still means
  validated; it now has a name for the scope of what it can see (`phase: design`), and the
  rejected weak sibling stays rejected.
- The generator gains a catalogue-driven emission path for cycle-phase rungs, and the rungs
  gain the refusal code in their provenance comment. A technician reading a fault at 02:00
  gets a code they can look up in a published spec.
- **The HMI fault display becomes generated from the catalogue**, not from a second list.
  ADR-0013's fault display and the agent's refusal list and the GUI checklist are one
  vocabulary, which is what ADR-0012 intended and what finding-level drift was eroding.
- Message strings live in the catalogue, so ADR-0015 Erratum 1's Correction D — a pneumatic
  endpoint must not be told its "pinout" is missing — becomes a data fix in one file rather
  than a code change.
- Third-party conformance becomes testable: emit the codes, in the right phase, with the
  right outcome. This is the first thing in the repo that makes ADR-0018's independence claim
  falsifiable.

## Related

ADR-0012 (one refusal engine), ADR-0013 (generated HMIs), ADR-0016 (one validation surface),
ADR-0018 (OCM vs Cellwright), ADR-0019 (cell interconnect), ADR-0020 (carrier identity),
ADR-0021 (journal), ADR-0022 (lifecycle and agent authority), ADR-0023 (plans are verbs),
ADR-0024 (command authority)
