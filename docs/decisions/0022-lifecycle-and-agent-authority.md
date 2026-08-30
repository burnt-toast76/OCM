# ADR-0022 — Lifecycle state governs write authority; the agent edits manifests only

**Status:** Accepted. Decisions 1, 3, and 6 are amended in part by ADR-0024 (manifest
authority and command authority are separated onto two axes; the D6 absolute is narrowed to
the agent). The decisions below stay as written and readable as history — ADR-0024 carries the
superseding reasoning (the house pattern; cf. ADR-0015 Erratum 1).

## Context

The context built to let an agent *program* a cell — component transcriptions, module
connectivity, cell composition, PackML state, generated-code provenance — is the same
context needed to *explain* and *diagnose* one. A cell runs for a decade. The people who
built it leave, the people maintaining it were not there, and the modifications nobody
documented accumulate. Manifests that can answer "why is this rung here" three years later
are worth more over the machine's life than the build-time saving that justified them.

Nothing currently supports this. Manifests are build-time artifacts: the generator consumes
them, emits code, and the code goes to the machine. The manifests stay in a repo, on a
laptop, in a project folder. An agent asked about a running cell would answer from a
manifest that may no longer describe it.

There is also an unresolved authority question. In development an agent must be able to
create and modify freely. On a running machine it must not. And a naive reading — put the
state in the manifest and have the agent check it — fails immediately: in development the
agent can edit manifests, so it can edit its own permission. A cold test would find that
path in an afternoon.

## Decision 1 — Write authority is a property of the API binding, not of cell data

ADR-0012 makes the refusal engine singular and server-side, with the GUI and the agent as
clients of one API. The same mechanism governs authority here.

A deployed machine exposes a **read-only verb set**. The mutating verbs are not present.
There is no field the agent reads to decide whether it may write, because there is no
decision to make — an unreachable verb cannot be reasoned around, prompted around, or
edited.

Consequence, and it is deliberate: **the same agent, the same manifests, and the same
prompts work in every state.** The only difference is which verbs the endpoint exposes.
Building a separate "diagnostic agent" is rejected — it would drift from the authoring
surface, and the two would come to disagree about what the cell is.

## Decision 2 — Three lifecycle states, not two

Development and Deployed are the easy cases. The state that consumes schedules is the one
between them: the machine is physically built, energised, and being edited. Commissioning,
or a modification to a running line six months later.

That is not Development — real hardware can move and injure someone. It is not Deployed —
writes are required. It is where the risk actually lives, and a binary model forces it to be
mislabelled as one of the two.

| State | Manifests | Live tags | Journal | Agent writes | Hazard present |
|---|---|---|---|---|---|
| **In development** | edit | — (simulated) | — | full | none |
| **Commissioning** | edit | read | read | full, keyed | yes |
| **Deployed** | read-only | read | read | none | yes |

## Decision 3 — Entry to Commissioning is physical, not software

Automation solved this problem already, and the solution is borrowed rather than reinvented.
A robot teach pendant uses a physical keyswitch — reduced-speed teach versus automatic —
precisely because "sometimes you must edit a machine that can move" is unavoidable and
cannot be left to software.

**Deployed → Commissioning requires a physical key.** No API verb, no GUI control, no agent
action can make that transition. Someone is standing at the machine.

**Commissioning → Deployed** may be software, and forces a regenerate-and-verify: the
generator re-emits from current manifests and the result must match what is installed.
Nothing reaches Deployed that was hand-touched and not regenerated.

## Decision 4 — The agent's write surface is manifests. Generated artifacts stay generated.

An agent in a writable state edits **manifests**. It does not edit rungs, waypoints, or
generated tags.

This is not a restriction bolted on for safety; it is what makes the rest of the
architecture hold. Generated code is separated from user-authored code, overrides are
expressed as data rather than code edits to preserve checksums and read-only status, and
`manifest_sha` on every journal event (ADR-0021) is the provenance chain. An agent editing a
rung directly breaks all three at once: the code no longer derives from the manifest, the
hash stops meaning anything, and the traceability claim becomes false.

So the agent edits a declared pose with declared tolerances and the resolver produces the
motion. It edits module connectivity and the generator produces the rungs. Every change it
makes is validated by the single validation surface (ADR-0016), refused when incomplete, and
traceable to a manifest version.

**User-owned override tags are the one legitimate exception**, and only because they are
already a separate namespace by design. Whether the agent may write them is settled
explicitly here rather than by accident: it may, in Development and Commissioning, and the
write is journalled with the operator who authorised the session.

## Decision 5 — Deployed manifests live on the machine and are hash-matched

A cell in Deployed or Commissioning holds its own manifests, resolvable locally. They are
not fetched from a repo, a laptop, or a network share.

The deployed manifest set carries a hash, and the running program carries the
`manifest_sha` it was generated from. **A mismatch is a refusal to answer, not a caveat.**
An agent that explains a cell from a manifest that no longer describes it is producing
confident, fluent, wrong output — the exact failure this platform exists to prevent, arriving
by a new route.

This also makes the local inference tier the natural deployment model rather than a
concession: manifests on the machine, agent on the machine, air-gapped, with the
IP-exposure objection largely dissolved.

## Decision 6 — Explanation is available now. Diagnosis needs three inputs and stays advisory.

These are different capabilities and are scoped differently.

**Explanation** is answerable from manifests alone. What does this module do, what is it
connected to, why does this rung exist, what is the torque spec on this fastener. Static
context, no runtime state, high confidence. This works with what is already built.

**Diagnosis** requires manifests *plus* journal *plus* live tags. Manifests say what should
happen; finding out what did happen needs the other two. An agent with manifests alone can
say what a symptom is consistent with — it cannot say what is wrong, and must not imply that
it can.

Diagnostic output is **advisory**. There is no actuation path in any state: the agent cannot
write a live tag, force an output, or command motion. An agent that can write tags on
running automation equipment is a safety-relevant actor, and that is a different decision
requiring risk assessment and a different liability posture. It is not made here, and the
absence of the capability is the point.

## Shape

```yaml
# machine-side binding, not part of any manifest
binding:
  state: deployed              # in_development | commissioning | deployed
  verbs:
    read:  [get_cell, get_module, get_component, read_tags, query_journal]
    write: []                  # empty in deployed; not filtered — absent
  manifest_root: /var/ocm/manifests
  manifest_sha: "a3f19c…"
  running_program_sha: "a3f19c…"
  on_sha_mismatch: refuse
```

Refusals this admits:

- Deployed manifest hash does not match the running program's `manifest_sha`
- A mutating verb invoked against a Deployed binding (unreachable by construction; if it is
  ever reachable, that is a defect, not a refusal case)
- Commissioning entered without a keyswitch assertion
- Commissioning → Deployed attempted when regenerate-and-verify does not reproduce the
  installed program
- Manifest root absent or unreadable on a machine in Deployed or Commissioning
- Diagnostic query requiring journal or live tags where that source is unavailable — answer
  the explanation part, refuse the diagnostic part, do not blend them

## Consequences

- Manifests become deployed artifacts with a lifecycle, not build-time intermediates. The
  generator gains a deployment step and the runtime gains a manifest root.
- The product has a post-build life. This is a larger value pool than the build-time saving,
  and it is not reachable by a competitor who only generates code faster.
- The demo gains its closing move: after the refusals, a machine that can still explain
  itself to whoever is standing in front of it.
- Commissioning is a real state with real cost — a keyswitch input, a state machine, and a
  regenerate-and-verify path. Shipping the binary model first was considered and rejected:
  the middle state is where hazard and write authority coexist, and discovering that during
  a commissioning job is the wrong time to design it.
- "Diagnoses your machine" must not be promised ahead of the journal and live-tag
  integration. A customer will test it in the first week, and the first miss costs more than
  the feature earns. "Explains your machine" is a promise that can be kept today.

## Related

ADR-0012 (one refusal engine), ADR-0013 (generated HMIs), ADR-0016 (one validation surface),
ADR-0017 (context is layered), ADR-0021 (journal and record sink), ADR-0024 (manifest
authority vs command authority — amends D1, D3, D6)
