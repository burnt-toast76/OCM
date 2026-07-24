# ADR-0016 — One validation surface: authoring sees what resolution sees

**Status:** Accepted

## Context

ADR-0012 put the refusal engine on the server and made the GUI and the AI agent co-equal
clients of it. That settled *where* refusals are computed. It did not settle *when*, and the
module-authoring cold test (`docs/cold-test-module-authoring.md`) showed the difference
matters more than expected.

`validate_module` runs schema validation plus artifact-file existence. It does not resolve
connectivity — `ocm_api/authoring.py` contains no reference to `ocm_resolve` at all. The
ADR-0015 connectivity refusals fire only inside `resolve_cell`. So a module reads green
while it is being authored and raises five refusals the moment a cell resolves it.

The cold test demonstrated the consequence directly: a module with **fabricated** dispenser
connectors (`X_PWR`, `air_in`, `X1` — none of which exist) validated exactly as clean as an
honest one. Three agents authored honest modules, called the verb they were given, received
green-except-geometry, and stopped. They stopped correctly given what they were told. Every
one of their modules raises five connectivity refusals under `resolve_cell`.

The three agents did not fabricate. That result is worth keeping in view: the discipline held
because `describe_component` honestly reports absence, not because any check enforced it.
Finding 3 of the cold test states it plainly — the honesty was volunteered, not enforced. A
refusal engine the authoring loop cannot reach is not a safeguard. It is documentation.

This matters most for the thing OCM is for. The premise is that an agent proposes and the
refusal engine corrects, converging on a manifest that is right. If the checks the agent can
see are not the checks that decide, the loop does not close, and the platform's guarantee
degrades to whichever agent happens to be conscientious that day.

A second, smaller problem surfaced in the same test. Every fresh draft ships a placeholder
`mechanical.geometry.collision` path, `collision` is schema-required, and `validate_module`
checks it as a real file on disk. An agent holding only authoring verbs can never clear it.
All three runs terminated at that wall. There is no machine-checkable definition of
"authoring is finished."

## Decision 1 — `validate_module` resolves connectivity

`validate_module` checks the module's `ports`, `nets`, and `links` against the components
they reference, using `check_module_connectivity`, and returns those refusals alongside the
schema and artifact ones. It needs a components search path; the plumbing
`_check_module_components` already threads is the one to use, not a second path.

There is one verb named `validate_module`, and it means validated.

## Decision 2 — no second, weaker verb

**Rejected:** leaving `validate_module` as-is and adding a sibling — `resolve_module`,
`check_connectivity`, or similar — that performs the deeper check.

This is the option the cold test already ran, by accident, and it failed. When two verbs
exist and one is named for the obvious thing, a caller invokes the obvious one and believes
the answer. Three independent agents did exactly that. A design whose safety depends on the
client choosing the stronger of two similarly-named verbs has no safety property at all — it
has a convention, and the whole point of a refusal engine is to not rely on conventions.

The same argument applies to the GUI. A wiring canvas calling `validate_module` for its
completion checklist would show green on a module that cannot resolve, which is the failure
this platform exists to prevent, rendered as a checkmark.

If a caller genuinely needs the cheap check — a fast keystroke-level lint, say — it can be
added later under a name that says what it is (`lint_module`) and that nobody will mistake
for validation. It is not needed now.

## Decision 3 — a draft may omit artifact claims; publish requires them

The geometry wall is not a validation problem. It is the platform violating its own rule at
draft creation: `create_module_draft` writes a `collision` path pointing at a file that does
not exist. Under ADR-0014 that is a claim nothing backs — an assumed value wearing a
placeholder's clothes — and the correct treatment of an unknown is absence, not a
placeholder.

Therefore: a **draft revision** may omit `mechanical.geometry.collision` and the other
artifact claims. `publish_module` requires them. The existing `is_draft_revision` machinery
already distinguishes the two states and spec/09 already excludes drafts from cell
resolution; nothing new is needed to express this.

Nothing is weakened. A published module still cannot claim geometry it does not have. What
changes is that a draft stops making a claim it was never in a position to make, which gives
an authoring agent a reachable, machine-checkable done state: *the manifest is complete;
artifacts are pending.*

**Rejected:** adding `generate_geometry_stub` to the authoring verb set. It clears the wall
by manufacturing a stub — geometry invented to satisfy a check, which is the refusal-
satisfying move rather than the correct one. It also widens an agent's authority from
authoring to artifact production for no reason connected to the problem.

## Consequences

- `validate_module` gets slower and needs the components registry available. Acceptable: it
  is called on demand, not per keystroke.
- **Existing modules may start refusing.** Any module whose nets reference components with
  untranscribed connectors will now say so during authoring rather than at cell resolution.
  That is the intended effect and should not be softened — it is ADR-0014's completion list
  arriving at the moment it is useful instead of long after.
- The ADR-0015 Erratum 1 corrections must land with or before this, or `validate_module`
  will start reporting the unresolvable-pneumatic-endpoint defect to every author.
- **The cold test becomes a regression test.** Re-running it — same brief, same six verbs —
  should now surface connectivity refusals during authoring, resolve the pneumatic net, and
  reach a definite done state. If it does not, this ADR did not achieve its purpose.
- A future `lint_module` remains available if a cheap check is ever wanted, under a name that
  cannot be mistaken for the real one.
- The GUI's completion checklist and the agent's refusal list become the same list, computed
  once, which is what ADR-0012 intended.
