# Glossary

OCM uses ordinary words in narrow ways. This page is the on-ramp: read it before the ADRs,
and come back to it when a decision record uses a word as though you already agree on what
it means.

Each entry gives the plain meaning first, then the sharp edge — the thing the word does
*not* mean here. ADR references point at where the decision was actually made.

**Six words carry more than their weight.** If you only read part of this page, read these:
[port](#port), [net](#net), [link](#link), [plan](#plan), [frame](#frame), and
[refusal](#refusal). Each of them means something specific and each has been the source of a
real ambiguity that cost an ADR to resolve.

---

## The layers

OCM authors context in layers. A layer may reference the layer below it. **A layer never
restates what the layer below already declares** — a fact has exactly one home, and
duplication across layers is a defect (ADR-0017).

### Component
A purchasable part — a valve, a sensor, an I/O block. Its manifest is *transcribed* from the
manufacturer's datasheet and contains only what the datasheet answers.

*Not:* a thing you design. If you find yourself deciding a value rather than reading it, you
are authoring at the wrong layer. (ADR-0014, ADR-0017)

### Module
An assembly the integrator designs — which components it contains, how they are wired to each
other, what the assembly does. Component facts are referenced, never copied.

*Not:* a bag of parts. A module declares behaviour ([capabilities](#capability)) and speaks
[PackML](#packml). (ADR-0014, ADR-0017)

### Cell
A set of placed modules on a base, plus the connections between them and the
[plan](#plan) they execute.

*Not:* a line. Line composition is deliberately deferred; cells connect to each other by
discrete I/O, never by fieldbus. (ADR-0017, ADR-0019)

### Carrier
The passive fixture that carries a part through the cell — a pallet, a nest, a spring clamp.
It has its own manifest kind.

*Not:* a module and not just a fleet fact. A carrier is passive, it passes through, and it
**locates itself** against machined features on the conveyor rather than being told where it
is. (ADR-0031 D1)

### Manifest
The YAML file declaring one component, module, cell, or carrier. Manifests are the authored
surface — the only thing an agent is permitted to write. (ADR-0022 D4)

### Transcription (vs. design)
Transcription is copying facts out of a source. Design is deciding facts. OCM keeps them in
different schemas on purpose, because a schema that demands a design answer from a
transcriber invites a plausible-looking invention.

**Gaps stay absent.** An unknown field is omitted, never filled with a marker or a guess; the
resulting [refusals](#refusal) become the human's completion list. (ADR-0014)

### Provenance
Every component names where its facts came from (`source.kind`, `source.ref`, `source.date`).
Mandatory. A component with no stated source is not a component.

### Verbatim units
Units are recorded exactly as the source prints them — `bar`, `psi`, `Nl/min`, `G1/8` — and
never converted during authoring. Conversion happens later, deterministically, outside the
model. (ADR-0014)

### refdes
A module's own short name for one component instance — `VG1`, `IO1`. How a module points at
a part it contains without restating the part's facts.

---

## Connectivity

### Port
**An endpoint that a [net](#net) or a [link](#link) can name.** That is the whole test. If a
net or link can point at it, it is a port; if not, it is something else, whatever it looks
like.

A port holds no connectivity, no signal list, and no behaviour — just an id, a domain
(electrical / pneumatic / communication), and that domain's descriptor. Same shape at module
scope and cell scope.

*History worth knowing:* `ports` previously meant three incompatible things across ADRs
0015, 0019, and 0020. ADR-0026 collapsed them to one. If you read an older ADR and the shape
looks wrong, that is why.

### Subsystem block
A top-level section that lives *beside* `ports`, not inside it, because nothing can be wired
to it: `identity` (reader configuration), `carriers` (a fleet declaration), `record_sink`
(where records drain), `produces` (what the cell measures), `mode_selector` (the keyswitch).

The old `domain: identification` was deleted — it existed only to let a configuration block
sit in a list of connection points. (ADR-0026 D2)

### Net
**N unordered endpoints sharing one common node** — a power rail, a shared air supply, a
safety chain. Order is meaningless; membership is everything. Domains: electrical, pneumatic,
safety.

### Link
**Exactly two endpoints, each naming a port** — one cable between two ports. Communication
only. **Order matters**, which is the entire reason links are not nets: an EtherCAT chain is
a sequence, and modelling it as an unordered net would lose the topology. (ADR-0015 D2)

### Pin
A numbered contact inside a connector, transcribed from the datasheet. **The wiring UI has no
path to create one.** If a pin you need doesn't exist, the component transcription is
incomplete — fix it there. (ADR-0015 D4)

### Signal
An entry in a module's semantic I/O map. Signal names become PLC tag names in generated code,
so they must be meaningful — `part_present`, not `IN_00`.

**Direction is from the PLC's point of view** at module scope, but from the *device's* point
of view in a component manifest (`direction_device`). The mapping between them happens at the
module layer. This trips people up.

### Requirement / binding
A module declares an abstract fact it needs (`requires`) without naming who provides it. The
cell binds each key to a concrete signal. Lets a module be written once and dropped into
different cells. (ADR-0023 D4)

---

## Geometry and motion

### Frame — *two meanings, watch out*
**1. A named coordinate frame** (`mechanical.frames`). `origin` is required and is the
module's mounting datum; every other frame is relative to it. `tcp` is the tool center point,
required for end effectors.

**2. In ADR-0029 only: a namespaced joint-state dict** — one snapshot of every joint's
position at one instant on the [timeline](#timeline).

These are unrelated concepts wearing the same word. Context disambiguates, but read
ADR-0029's use of "frame" as *animation frame*, not *coordinate frame*.

### Datum
The reference the rest of the geometry is measured from. The frame carries load; a separate
ground plate carries precision — deliberately not the same surface. (ADR-0006)

### Base grid
The bolt pattern modules mount against (`ocm-base-grid-50`). Every placement in a cell is
expressed against it. (ADR-0011, still open)

### urdf_fragment
A snippet declaring one module's links and joints. **The key field for kinematics** — it is
what allows a cell manifest to compile into a single simulable scene rather than a pile of
unrelated meshes.

### Collision geometry: derived vs. authored
Every module declares *how* its collision proxy is produced. `derived` — the resolver builds
it from posed component envelopes, and **refuses rather than approximating** if the inputs are
incomplete. `authored` — you supply a mesh, and component envelopes must be provably
contained inside it. Publishing requires a collision *source*, not a collision *mesh*.
(ADR-0027)

### Structure
Module-owned brackets, plates, and standoffs, declared as posed primitives (box, cylinder,
mesh) rather than transcribed. We fabricate these, so we own the CAD and there is no
datasheet to transcribe from. (ADR-0027 D3)

### Located / locating module
The module that physically seats a carrier — usually the conveyor. It declares the frame a
correctly seated carrier lands at, plus the constraint features doing the locating and each
one's tolerance. That pose is the **root** of the carrier's position chain; transit is
described as a departure from it. (ADR-0031 D2, D3)

### Keepout
Service clearance required around a module's footprint. Enforced by the cell layout
validator, not advisory.

---

## Behaviour

### Capability
**A verb a module offers** — `dispense`, `screw`, `pick`. Deliberately shaped like a tool
schema, because the agent is a first-class reader of it. Carries typed parameters (ranges are
**hard limits**, not suggestions), motion requirements, pre/postconditions, timeout, and
results.

### actuates
The geometric half of a verb: which joints it drives, and the value each holds when the
postcondition is true. Absence renders the module static and advises; it does not refuse.
(ADR-0028)

### Precondition / postcondition
Boolean expressions over signals. **The generator emits real interlock logic from
preconditions** — they are not documentation. A step is not complete until its postconditions
read true. Preconditions are re-verified at every invocation, not just the first.
(ADR-0023 D2, D3)

### Plan
**A list of verb invocations, and nothing else.** No conditions, no branching, no inline
logic. Conditions belong to modules; the plan only says what happens in what order.
(ADR-0023 D1)

*Not:* a program. If you want to express "only if X," that belongs in the module's
preconditions.

### Timeline
The plan walked in order, producing typed rows of joint states. Strictly serial — the overlap
special case was removed. Every row is collision-checked, including actuation rows. The
emitted artifact is a **trace**; the HTML animation is just one consumer of it. (ADR-0029)

### PackML
The ISA-TR88 state machine every OCM module must implement. Mandatory and rigid — it is what
makes the cell coordinator generatable once instead of per-module. (ADR-0004)

### Mode
The AUTO / MANUAL / EDIT keyswitch position. Governs [command authority](#command-authority),
never safety. (ADR-0024 D2)

---

## Authority and lifecycle

### Lifecycle state
Three, not two — because the risky state is the one in the middle:

| State | Manifests | Live tags | Agent writes | Hazard |
|---|---|---|---|---|
| In development | edit | simulated | full | none |
| **Commissioning** | edit | read | full, keyed | **yes** |
| Deployed | read-only | read | none | yes |

Commissioning is a machine that is physically built, energised, and being edited. Entry to it
is a **physical** act, not a software toggle. (ADR-0022 D2, D3)

### Manifest authority vs. command authority
Two different axes, governed by two different mechanisms. Setting a value *inside* a declared
bound is a **command**. Changing the bound is a **manifest edit**. Confusing them is how a
"quick tweak" silently becomes a design change. (ADR-0024 D1, D3)

### manifest_sha
The hash tying deployed manifests to the machine running them. A mismatch is a load-phase
refusal. (ADR-0022 D5)

### Permissive
The copper-level enforcement of manifest authority: the engineering link is a *permissive*
driven by a safe output, not a firewall rule. Observation rides a physically unidirectional
channel. Mode knowledge is used for message quality, **never** for enforcement.
(ADR-0033)

---

## Records

### Journal
The local append-only log. **The journal write is the commit** — nothing is considered
recorded until it lands there. Forwarding to anywhere else is asynchronous and downstream.
(ADR-0021 D1)

### Event vs. unit record
Events are immutable and append-only. The **unit record is a query** over them, not a stored
document that gets updated. (ADR-0021 D3)

### record_sink
Where a cell's records drain to — declared in the manifest, not wired. Includes the journal
path, forwarding targets, buffer depth, and what to do when each becomes unavailable.

### produces
What the cell measures: measurements (with [verbatim units](#verbatim-units)), a verdict, and
the keys records are filed under. Derived from components, not connected to anything.

### Degrading vs. absorbing
Degrading is permitted **when it is legible** — the system does less and says so. Absorbing —
carrying on as though nothing happened — is never permitted. This is the general principle
behind most of OCM's error handling. (ADR-0021 D6)

---

## Refusals and the toolchain

### Refusal
The system's response when it cannot proceed honestly: it **declines, with a code and a
reason**, rather than guessing a value, silently absorbing an error, or reporting green on an
incomplete manifest.

Refusals are not failures. **They are the completion list** — the mechanism by which the
system tells a human (or an agent) what work remains. The premise of the whole platform is
that an agent proposes and the refusal engine corrects, converging on a manifest that is
right.

### Refusal code
A stable identifier of the form `OCM_*` — `OCM_SCHEMA_*`, `OCM_PORT_*`, `OCM_NET_*`,
`OCM_LINK_*`, `OCM_UNIT_*`, `OCM_JOINT_*`, `OCM_ACTUATION_*`, `OCM_CARRIER_*`, and others.
Codes are shared across phases and carry rung-level provenance into generated PLC code.

### The three phases
One *source* of refusal rules, three places they are evaluated (ADR-0025):

| Phase | Inputs | Runs in | Example |
|---|---|---|---|
| **design** | manifests only | `ocm-resolve` / `validate_*`, anywhere | unresolvable endpoint, measurement with no unit |
| **load** | manifests + machine environment, at start-up | same engine, on the machine | journal path unwritable, `manifest_sha` mismatch |
| **cycle** | live machine state, inside cycle time | generated PLC / coordinator logic | buffer full, tag read-back mismatch, parameter out of bounds |

"Singular" means **one source, not one process**. No rule is authored twice, in any language,
for any target.

### Validate vs. resolve
`validate_*` checks a manifest. `resolve_*` follows every reference and connection through to
the layer below. The two used to disagree — a module could read green during authoring and
raise five connectivity refusals the moment a cell resolved it.

**ADR-0016 closed that: there is one validation surface, and authoring sees what resolution
sees.** There is no weaker sibling verb.

### Cold test
A regression practice: hand an agent only the authoring verbs and a real-hardware brief, then
watch it iterate against refusals. Originally used to discover that fabricated connectors
validated exactly as clean as honest ones; now used to confirm the loop still closes after
changes. (`docs/cold-test-module-authoring.md`)

### Packages
| Package | Does | State |
|---|---|---|
| `ocm-core` | Schemas, units, shared types | built |
| `ocm-resolve` | Reference resolution, connectivity | built |
| `ocm-generator` | Scene composition, planning, collision checking — and PLC emission when it exists | built; **collision and scene work live here today**, not in `ocm-resolve` |
| `ocm-api` | The server; the one surface both GUI and agent call | built |
| `ocm-composer` | React front end | built |
| `ocm-agent` | MCP-facing agent client | placeholder |
| `ocm-runtime` | On-machine execution | placeholder |
| `ocm-viewer` | Scene / trace visualisation | placeholder (ADR-0030 reserved) |

> Package boundaries here reflect current layout. The glossary otherwise
> describes what the decisions say; anywhere it names a file, package, or
> path, it tracks disk.

### Verbs
The API surface, identical for a human clicking and an agent calling: `create_*_draft`,
`update_*`, `validate_*`, `resolve_*`, `publish_*`, `list_*`, `check_*`.

**API before pixels** — the GUI is a client of this surface, never a privileged path around
it. (ADR-0012)

---

## Related

- `docs/decisions/README.md` — the ADR index, with status
- ADR-0017 — the layering principle
- ADR-0025 — the refusal catalogue and phases
- ADR-0026 — what a port is, and what everything else is
