# ADR-0023 — The plan is verbs; conditions belong to modules

**Status:** Accepted

## Context

`cell.yaml`'s `plan:` block is the layer a human or an agent authors. It names what the cell
does. Everything it must *wait for* — a part seated in the nest, jaws confirmed closed, a
screw fed to the bit — is declared elsewhere, on the capability whose module owns the
sensing signal.

That rule is currently inferable from four places (spec/00 item 3, spec/08 "Interlocks become
motion gates", spec/09's `set_plan` row, and the `preconditions` description in
`ocm-module-1.0.schema.json`) and stated in none of them. It is the reason a plan author
cannot skip an interlock: there is no syntax for one. That is a load-bearing architectural
constraint and it deserves a decision record.

Writing it down surfaced four gaps between the rule as designed and the code as built:

1. **Postconditions are never verified.** `ocm_core.Capability` loads them; the only consumer
   is `coordinator/simulated_module.py`, which *sets* signals to match the declared
   postcondition. The simulator asserts what the coordinator should be checking. Against real
   hardware a step advances on PackML Complete alone — nobody re-reads `clamped`.
2. **Conditions are checked at runtime, not at resolve.** `_check_condition` raises
   `PreconditionError` when an expression names a signal the module doesn't declare. Nothing
   in `ocm-resolve` touches conditions at all. spec/09 already claims `set_plan` resolves
   "precondition references." That claim is not true.
3. **Cross-module conditions are inexpressible.** `drive_screw` lives on sd50; `clamped` lives
   on the pneumatic nest. sd50 is a general-purpose screwdriver and cannot name a peer it does
   not know exists, so the single most important interlock in the dogfood cell — do not apply
   torque to an unheld part — cannot currently be declared.
4. **Every wait is unbounded.** `program.py` has three `while … await asyncio.sleep(poll)`
   loops (`_wait_for_at_step`, `_wait_for_preconditions`, `_wait_for_state`). The coordinator's
   only timeout is `heartbeat_timeout_s`, which watches the robot program's liveness, not op
   completion. A clamp that never confirms hangs the cell silently and forever.

## Decision 1 — The plan is a list of verb invocations, and nothing else

A plan step is exactly: `step` (label), `module`, `op`, `params`, `at`, `binds`, `for_each` +
`sequence`, and `on_fail`. `plan_walk.py`'s `_NESTED_KEYS = ("sequence", "on_fail")` defines
where recursion happens.

**There is no wait, guard, `when`, or `until` key, and there will not be one.** The plan
declares intent. It does not declare conditions, because a plan author who can write a
condition can also omit one.

## Decision 2 — A step is not complete until its postconditions read true

The coordinator verifies `postconditions` against the live bus before advancing. PackML
Complete is necessary and not sufficient. A module that reports Complete while its own
declared postcondition reads false is faulted, not believed.

This is what "hold the step until the clamp confirms" means in implementation terms, and it
is the reason the plan needs no wait syntax: the wait is already inside the verb.

## Decision 3 — Preconditions are re-verified at every invocation

Preconditions are evaluated fresh each time an op runs. They are never inferred from the fact
that earlier plan steps completed.

The plan is not the authority on the state of the world. A coordinator resuming at step 3
after a stop, an operator who opened the jaws to clear a jam and returned the cell to
production mid-sequence, and a pneumatic clamp whose supply pressure drooped between `clamp`
and `drive_screw` all produce a true plan history and a false `clamped`. Re-reading costs the
plan author nothing, because they never wrote the precondition in the first place.

## Decision 4 — Modules declare abstract requirements; cells bind them to signals

A capability may declare `requires:` — named boolean facts it needs, without naming who
provides them. The cell binds each requirement on each instance to a concrete
`instance.signal`.

This is ADR-0015's ports-and-nets pattern applied to logic: the module states an external
interface, the cell wires it. It makes cross-module interlocks expressible without giving the
plan any condition syntax, and without sd50's manifest acquiring knowledge of a nest.

An instance carrying a capability with an unbound requirement refuses at resolve
(`OCM_REQUIREMENT_UNBOUND`), with a hint naming the instances that declare a bool of the right
shape. A binding pointing at an instance or signal that does not exist refuses
(`OCM_REQUIREMENT_UNKNOWN_TARGET`).

## Decision 5 — Conditions resolve statically

A `precondition`, `postcondition`, or `requires` reference naming a signal the module does not
declare in `comms.signals` — and does not bind, per Decision 4 — is a **resolve-time refusal**
(`OCM_CONDITION_UNKNOWN_SIGNAL`), surfaced by `validate_module` and `set_plan`. It is not a runtime
`PreconditionError`.

Per ADR-0016, there is one validation surface. A manifest that will fault the coordinator on
first contact with hardware must not validate clean.

## Decision 6 — `timeout_s` and `on_timeout` are module facts, not plan parameters

Every capability declares `timeout_s` alongside `nominal_duration_s`, and `on_timeout` as one
of `hold` or `abort`.

- `hold` → PackML Held. Nothing is damaged, the part is where it was, an operator clears the
  cause and resumes. This is a clamp that did not confirm.
- `abort` → the part is compromised and routes to reject.

`on_timeout: hold` on a capability declaring `abort_safe: false` is incoherent and refuses at
validate (`OCM_TIMEOUT_DISPOSITION_CONFLICT`).

**A plan may not override `timeout_s`.** A part that legitimately needs a longer clamp travel
is a module revision, not a plan tweak. One source of truth for how long the hardware takes.

`timeout_s` is a different axis from the plan's `on_fail`. `timeout_s` is a module fact — how
long before this is wrong. `on_fail` is the plan's disposition — what to do with this part.
They compose: the timeout fires, the module goes Held or Aborted per `on_timeout`, and the
plan's `on_fail` decides eject and reject.

## Decision 7 — The expression grammar stays `signal == literal`; binding resolves first

`_check_condition`'s grammar is deliberately not extended. Requirement bindings are resolved
to concrete `(instance, signal)` pairs *before* any expression reaches the parser, so the
comparison primitive stays dumb and every condition it sees is local.

The read path becomes instance-qualified — `read_signals` may be asked for a signal on a peer
instance — but the expression syntax does not change. Extending the grammar (`and`, `>`,
ranges) remains open and is out of scope here.

## Shape

```yaml
# modules/com.accelsolutions.screwdriver.sd50/module.yaml
capabilities:
- name: drive_screw
  summary: "Drive one screw to torque at the current pose."
  requires:
    workpiece_secured:
      type: bool
      summary: "Something holds the part against drive torque. The cell says what."
  preconditions:
  - screw_present == true
  - workpiece_secured == true
  postconditions:
  - screw_present == false
  - result_ok == true
  nominal_duration_s: 1.8
  timeout_s: 6.0
  on_timeout: abort          # a screw stalled mid-drive is not resumable
```

```yaml
# modules/com.accelsolutions.fixture.pneumatic-nest/module.yaml
comms:
  signals:
  - {name: clamped, direction: input, type: bool}
  - {name: part_present, direction: input, type: bool}

capabilities:
- name: clamp
  preconditions:
  - clamped == false
  - part_present == true     # do not clamp an empty nest
  postconditions:
  - clamped == true
  nominal_duration_s: 0.6
  timeout_s: 3.0
  on_timeout: hold           # nothing broken; operator clears and resumes
```

```yaml
# cells/bracket-asm-01/cell.yaml
modules:
- instance: sd1
  module: com.accelsolutions.screwdriver.sd50@1.2.0
  requires:
    workpiece_secured: nest1.clamped

plan:                        # unchanged: verbs only
- step: clamp
  module: nest1
  op: clamp
  params: {force_n: 120}
```

## Consequences

- The coordinator gains postcondition verification and per-op timeouts. Three unbounded loops
  in `program.py` become bounded.
- `read_signals` becomes instance-qualified. `preconditions_met` takes a resolved binding map
  rather than a bare instance name.
- `simulated_module.py` must stop deriving its behavior from `postconditions`, or the new
  verification tests nothing. The simulator drives signals from its own script; the
  coordinator checks them against the manifest.
- Four new refusal codes: `OCM_REQUIREMENT_UNBOUND`, `OCM_REQUIREMENT_UNKNOWN_TARGET`,
  `OCM_CONDITION_UNKNOWN_SIGNAL`, `OCM_TIMEOUT_DISPOSITION_CONFLICT`.
- Existing committed modules become incomplete — none declares `timeout_s`. Per ADR-0014 the
  refusals are the completion list, not a reason to default the value.
- spec/09's `set_plan` row becomes true rather than aspirational. spec/08 gains a paragraph on
  timeout disposition and should cite this ADR rather than ADR-0004 for the interlock rule.
- The dogfood cell can finally declare its most important interlock: sd1 will not descend to
  contact unless nest1 reports the part clamped.
- **A cell JSON schema does not exist.** Components and modules have published schemas; cells
  are validated only by Python in `ocm-core`. Decision 1 is a convention until there is an
  `ocm-cell-1.0.schema.json` with `additionalProperties: false` on a plan step. Authoring that
  schema is deferred to its own ADR, and until it lands, "there is no wait syntax" is enforced
  by absence rather than by refusal.

## Related

- ADR-0004 — PackML is mandatory. Decision 2 tightens what Complete is allowed to mean.
- ADR-0012 — one API, one refusal engine. `set_plan` and `validate_module` are its surfaces.
- ADR-0015 — ports and nets. Decision 4 is the same pattern applied to logic.
- ADR-0016 — one validation surface. Decision 5 is that principle applied to conditions.
- ADR-0019 — cell interconnect; PackML Suspended realised in copper.
- spec/00 item 3, spec/08 "Interlocks become motion gates", spec/09 `set_plan`.
