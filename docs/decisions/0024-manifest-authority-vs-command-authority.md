# ADR-0024 — Manifest authority and command authority are different axes

**Status:** Accepted. Supersedes ADR-0022 Decisions 1, 3, and 6 in part; unblocks ADR-0013.

## Context

ADR-0022 governs "writes" with a single axis and concludes that a Deployed machine exposes a
read-only verb set with no actuation path in any state. ADR-0013 gives the engineer HMI
manual op execution, joint jog, and hand-typed parameters gated by the refusal engine. Both
are Accepted and they cannot both be true.

The collision is not a disagreement about safety. It is one word covering two different
things:

- **Changing what the machine *is*** — poses, connectivity, bounds, capabilities, tolerances.
  Regeneration follows. This is what ADR-0022 D4 is actually reasoning about.
- **Telling the machine to do something it is already declared able to do** — PackML
  start/stop, `drive_screw` at a torque inside a declared bound, a jog inside declared
  limits. No regeneration follows, and nothing about the manifest changes.

Collapsing them makes operator start/stop a "write" requiring a keyswitch, which is not how
any line runs, and it deletes the engineer HMI on every deployed cell.

ADR-0022 D3 also half-borrowed its own prior art. On a teach pendant the keyswitch governs
**motion**, not file editing. Using it to gate manifest edits while forbidding motion
entirely inverts the mechanism it cites.

## Decision 1 — Two axes, governed by two different mechanisms

**Manifest authority** is a property of the API binding, exactly as ADR-0022 D1 established.
Mutating verbs are absent from a Deployed binding, not filtered. That construction property
is preserved unchanged and is the reason the agent cannot reason its way around it.

**Command authority** is a property of the **client class** and the **physical mode
selector**. It is not carried in cell data and not derived from lifecycle state.

The agent's endpoint carries no command verbs in **any** binding, in **any** state. This is a
separate endpoint, not a filtered one — the same construction argument, applied to a second
surface.

## Decision 2 — A three-position keyswitch: AUTO / MANUAL / EDIT

One physical selector on the machine, three positions, key removable **only in AUTO**.

| Position | Manifest writes | Commands available | Motion |
|---|---|---|---|
| **AUTO** | none | PackML only (start/stop/hold/reset) | production speed, guards closed |
| **MANUAL** | none | PackML + manual ops + jog, parameters within declared bounds | hazard-relevant; safety mode per spec/06 |
| **EDIT** | enabled — this **is** the Commissioning entry of ADR-0022 D3 | as MANUAL | as MANUAL |

Key removable only in AUTO is the whole point of a physical selector and is standard
practice. A machine cannot be left in MANUAL or EDIT unattended, because leaving requires
taking the key, and taking the key requires returning to AUTO.

**MANUAL is where ADR-0013's engineer HMI lives.** Manifests stay read-only; commands become
available. That is the combination ADR-0022 had no way to express, and it is the ordinary
state of a technician debugging a running machine.

**EDIT replaces the separate keyswitch assertion of ADR-0022 D3.** There is one physical
control, not two. Deployed → Commissioning is the key turning to EDIT; Commissioning →
Deployed remains software, and still forces regenerate-and-verify.

## Decision 3 — A value inside a declared bound is a command. Changing the bound is a manifest edit.

This is the test, and it is checkable rather than negotiable.

An engineer typing 2.4 N·m into a faceplate whose capability declares `0.5–3.0 N·m` is
issuing a command; it is available in MANUAL. Changing that capability to permit 4.0 N·m is a
manifest edit and requires EDIT. The refusal engine gates the first against the declared
bound — which is exactly what ADR-0013 said it would do — and the binding gates the second by
not exposing the verb.

The same rule settles recipes: a recipe that selects among declared values is data and moves
in MANUAL. A recipe that widens an envelope is a manifest change. If recipes later need their
own versioned artifact, that is a new ADR; this rule is what tells us when we have hit that
need rather than guessing now.

## Decision 4 — Safety is unchanged and stays outside this

The mode selector declares **intent**. It does not implement a safety function.

Reduced-speed enforcement, enabling devices, and guard interlocks in MANUAL are hardwired
safety-rated functions per spec/06, sourced from certified components, and the selector is an
input to them. OCM declares that a machine has a mode selector and what commands each
position admits. It does not certify the mode.

Restated because it is the most likely thing to erode: **the manifest is not a risk
assessment.** A three-position selector on a machine that can move under a technician's hands
is a risk-assessment input, not a substitute for one.

## Decision 5 — Every command in MANUAL or EDIT is journalled

ADR-0022 D4 already journals override-tag writes with the authorising operator. Extend it to
all commands issued outside AUTO: event, parameters, operator, keyswitch position,
`manifest_sha`.

This is the same argument as ADR-0020's `override_pass` versus `rework`. A unit produced
under a hand-typed parameter in MANUAL and one produced by the program in AUTO are different
liability positions, and a traceability record that cannot distinguish them is useless in the
one audit where it matters.

## Decision 6 — ADR-0022 D6 is narrowed, not reversed

D6's absolute — "there is no actuation path in any state" — overreached into the HMI by
accident. The paragraph argues about the **agent**, and that argument stands in full:

> The agent cannot write a live tag, force an output, or command motion, in any lifecycle
> state and in any keyswitch position. An agent that can actuate running automation is a
> safety-relevant actor; that is a different decision requiring risk assessment and a
> different liability posture, and it is not made here.

What changes is that a human at a keyswitch was never the subject of that sentence.

**Rejected:** giving the agent command authority in MANUAL on the grounds that a human turned
the key. The human turned the key to work on the machine, not to authorise an autonomous
actor to move it. Nothing about a key position tells us a human is watching what the agent
does with it.

## Shape

```yaml
# machine-side binding, not part of any manifest
binding:
  lifecycle: deployed             # in_development | commissioning | deployed
  keyswitch:
    input: safety-io.mode_select  # resolvable component ref, 3-position
    position: auto                # auto | manual | edit — read, never written
  verbs:
    read:    [get_cell, get_module, get_component, read_tags, query_journal]
    command: []                   # agent endpoint: empty in every state
    write:   []                   # empty unless keyswitch == edit
  on_key_absent_in_manual: refuse
```

```yaml
# cells/press-fit-01/cell.yaml
mode_selector:
  component: com.<vendor>.keyswitch.<part>   # transcribed, ADR-0014
  positions: [auto, manual, edit]
  manual_mode_safety: hardwired              # spec/06; declared, not implemented
```

Refusals this admits:

- Manifest-mutating verb reachable while keyswitch is not EDIT (a defect, not a refusal case
  — the verb should be absent)
- Command issued with a parameter outside the capability's declared bounds, in any position
- Manual op issued whose `preconditions` are unsatisfied — ADR-0013's rule, unchanged:
  MANUAL relaxes sequencing, never interlocks
- Cell declaring `manual_mode_safety` that does not resolve to a safety-rated component
- Commissioning → Deployed attempted while the key is still in EDIT
- Cell with capabilities but no `mode_selector` in a Deployed binding

## Consequences

- **ADR-0013 is unblocked and its status is unchanged.** The engineer HMI works on deployed
  machines, in MANUAL, gated by the same refusal engine it always specified.
- ADR-0022 D2's lifecycle table is unchanged for manifest authority. It gains no column;
  command authority is simply not that table's subject.
- One physical control, three positions, instead of a keyswitch plus an unspecified mode
  concept. Hardware cost is a 3-position keyed selector and two safety-rated inputs.
- The agent's surface gets smaller and more defensible: it reads in every state, writes
  manifests in two, and commands in none. That is a sentence a customer's safety officer can
  read in one pass.
- The `mode_selector` block is another addition to a `cells/` schema that does not yet exist
  (see ADR-0025's consequence on the same subject).

## Related

ADR-0012 (one API, three clients), ADR-0013 (generated HMIs), ADR-0020 (disposition
vocabulary), ADR-0021 (journal), ADR-0022 (lifecycle and agent authority), spec/06 (safety)
