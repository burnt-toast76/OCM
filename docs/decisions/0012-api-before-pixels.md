# ADR-0012 — The GUI and the AI agent are clients of one API

**Status:** Accepted. ADR-0025 restates what "singular" means here — one refusal *source*, not
one *process* — after runtime refusals (ADRs 0019–0024) made the literal "server-side" reading
false.

## Context

The platform's next phase: users define their own modules (cameras, screwdrivers, custom
tooling — each with its own protocols, parameters, I/O, geometry), compose them into a
machine definition, and do it through a GUI **or through an AI agent**.

The trap is building the GUI first and burying create/validate/place/check logic inside UI
event handlers — making the agent a second implementation that drifts from the first, and
making every rule (bounds, containment, collision) exist twice.

## Decision

**API before pixels.** One programmatic surface — `ocm-api` — wraps what already exists
(ocm-core load/validate, ocm-resolve refusals, the generator's scene/plan/collision) and adds
authoring verbs:

```
create_module_draft / update_module / validate_module
list_modules / describe_module
create_cell / place_instance / move_instance / set_plan
resolve_cell / build_scene / check_collision / plan_and_emit
```

Exposed two ways from day one:
1. **MCP server** — the agent surface. An AI agent authors a manifest from a datasheet, gets
   refused on mistakes, corrects, places the module, runs the plan.
2. **HTTP/JSON** — the GUI surface. The web composer calls the exact same verbs.

**The refusal engine stays server-side and singular.** A GUI drag that puts a feeder outside
the workspace is refused by the same code path that refuses the agent and the CLI. UI code
never re-implements a rule; it renders refusals.

## Why the agent comes before the GUI

- The MCP wrapper over existing code is days of work; a GUI is weeks.
- "An AI agent designed and validated a machine module" is the platform's most spectacular
  cheap demo — and it exercises the API exactly where a GUI will need it.
- Watching what the agent fumbles is free API usability testing before pixels harden it.

## Prerequisites (schema v1.1 — do these first, they unblock everything above)

1. **Open the protocol enum.** User hardware speaks things we didn't enumerate (GigE Vision,
   proprietary serial). Accept `x-<name>` custom protocols as opaque-but-valid.
2. **Structured signal types.** A camera's `part_pose` is six floats + a frame reference,
   not six disconnected scalars. Add composite types to `signals`/`results`.

## Consequences

- The CLI becomes a thin client of the same API (or shares the library layer). Three
  clients, one rule engine.
- GUI build order: **cell composer first** (place modules on the grid, live 3D via the
  existing viewer, live refusals), module-authoring forms second — driven by the JSON
  Schema itself, not hand-built per kind.
- AuthN/multi-user is explicitly out of scope for v1; single-user local service.
- This repeats ADR-0009's move one level up: spec the surface, not the client.
