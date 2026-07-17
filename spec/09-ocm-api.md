# OCM Spec — ocm-api Tool Surface v1.0

**Status: draft for implementation.** The single programmatic surface per ADR-0012: the MCP
server (agents), the HTTP API (GUI), and eventually the CLI are all thin clients of these
verbs. **The refusal engine lives behind this surface and nowhere else.**

## Design principles

1. **Refusals are results, not errors.** Every mutating or checking verb returns the same
   envelope. Agents and GUIs render it; neither interprets exceptions.

```json
{
  "ok": false,
  "refusals": [{
    "code": "PARAM_OUT_OF_BOUNDS",
    "path": "plan[2].sequence[1].params.torque_nm",
    "message": "torque_nm=6.0 exceeds drive_screw limit on sd1 (com.accelsolutions.screwdriver.sd50@1.2.0)",
    "allowed": {"min": 0.2, "max": 5.0, "unit": "N.m"},
    "hint": "Reduce torque_nm or select a module whose capability covers 6.0 N.m."
  }],
  "warnings": []
}
```

   `path` is a JSON-path into the submitted document. `allowed` carries the machine-usable
   constraint (bounds, enum values, known ops list — the resolver's existing "known ops:
   [...]" pattern, promoted to data). `hint` is one actionable sentence. **All violations in
   one response** — never first-error-only.

2. **Document-granularity writes.** Submit a whole manifest / cell / plan (or an RFC-6902
   patch). No field-level setters.

3. **Files are the state; git is the review layer.** Every mutation lands in the working
   tree. Nothing is hidden from `git diff`. Commits stay human.

4. **Server-side singular rules.** No client re-implements a check. A GUI drag that leaves
   the workspace is refused by the same code path that refuses the agent's YAML.

## Verbs

### Discovery (the agent's eyes)

| Verb | Returns |
|---|---|
| `describe_schema(section?)` | The JSON Schema (or a subtree, e.g. `capabilities`), plus the version and changelog. The agent never guesses field names. |
| `get_example(kind)` | The best-matching existing manifest for a module kind (sd50 for end_effector, dh200 for process, gocator for sensor). The worked examples are the real documentation. |
| `list_modules()` / `describe_module(id)` | Registry contents; full parsed manifest with capability signatures. |
| `list_cells()` / `describe_cell(id)` | Cells; resolved composition incl. instance list, mounts, plan summary. |
| `list_frames(cell_id)` | Every referenceable frame in a resolved cell (`robot1.flange`, `nest1.part_datum`, ...) — what a `pose6d.frame` or `mount.on` may point at. |

### Module authoring

| Verb | Behavior |
|---|---|
| `create_module_draft(id, kind)` | Scaffolds `modules/<id>/` with a minimal manifest pre-filled from the kind's schema requirements. Draft = `revision: 0.x`, excluded from cell resolution until published. |
| `update_module(id, manifest \| patch)` | Writes + validates. Returns the envelope. Invalid content **is still written** (with `ok:false`) so iteration is cheap and the diff shows the attempt — validation gates *publishing*, not *saving*. |
| `generate_geometry_stub(id, {footprint_mm, height_mm, kind})` | Emits the box-primitive URDF fragment + registers it in the manifest. **Agents never hand-write URDF** — geometry is generated (ADR-0011 discipline). Real meshes replace stubs later by humans/CAD. |
| `validate_module(id)` | Full validation incl. cross-file checks (urdf_fragment exists, ESI path exists if declared). |
| `publish_module(id, revision)` | Validation must pass; sets the SemVer; module becomes resolvable. |

### Cell composition

| Verb | Behavior |
|---|---|
| `create_cell(id, base_module)` | Scaffolds cell.yaml with the base + datum conventions. |
| `place_instance(cell, instance, module@rev, mount)` / `move_instance` / `remove_instance` | Each call re-resolves and returns the envelope — **live refusals**: unknown module, revision mismatch, dangling `mount.on`, workspace overhang (with mm + direction). This is the GUI's drag handler and the agent's placement tool: same verb. |
| `set_plan(cell, plan)` | Writes + resolves: unknown ops, param bounds, precondition references. |
| `set_joint_state(cell, instance, joints)` | Robot home pose. |

### Checking & generation (wrapping what exists)

| Verb | Behavior |
|---|---|
| `build_scene(cell)` | Composes URDF; returns link/joint stats + containment result. |
| `check_collision(cell)` | Tesseract contact check at the composed state; contacts as instance pairs + depth. |
| `plan_cell(cell)` | Full plan: IK, path checks, cycle estimate table as structured data. Refusals name segment + contact pair + t (existing behavior, promoted to the envelope). |
| `emit(cell, {urscript?, animation?, view?})` | Writes artifacts, returns paths. |

## Hard rules

- **The API refuses to write `safety.verified_by`.** That field is a human signature
  (spec/06). Code: `HUMAN_SIGNATURE_REQUIRED`. The agent may fill every other safety field
  (hazards, PL, guarding) — declaring hazards is authoring; signing off is not.
- **No transport I/O.** This surface ends at generated artifacts. Going live (coordinator,
  drivers) is a separate, later surface with its own authz story.
- **Determinism:** same repo state + same call ⇒ same result. No hidden server state beyond
  the working tree.

## MCP specifics

- One MCP server, stdio, launched against a repo path. Tools map 1:1 to the verbs above.
- Tool descriptions embed the envelope contract and one worked example each — the agent
  should succeed without reading this spec.
- Long outputs (schema, manifests) returned as text; artifacts (HTML, scripts) as file
  paths, never inlined.

## The acceptance demo (this is the test)

Scripted agent session that must pass end to end, refusal count > 0:

1. Agent receives a short prose "datasheet" for a fictional pneumatic pick head
   (stroke, vacuum, M12 pinout, a `pick` op with force bounds).
2. `describe_schema` + `get_example(end_effector)` → `create_module_draft` →
   `update_module` with its first-attempt manifest.
3. First attempt contains a planted trap the datasheet makes natural (e.g. a `pose6d`
   result with no frame, or a signal named `IN_3`): **refused with path + hint** →
   agent corrects → `validate_module` passes → `publish_module`.
4. `place_instance` into bracket-asm-01 at a spot that overhangs the workspace:
   **refused, +X by N mm** → agent moves it inside → ok.
5. `plan_cell` → cycle table returned.

When that transcript exists, it is the second video.
