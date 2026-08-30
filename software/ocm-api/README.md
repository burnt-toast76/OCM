# ocm-api

**The one programmatic surface** (ADR-0012: "the GUI and the AI agent are clients of one
API"). spec/09-ocm-api.md's tool surface, implemented exactly, and nowhere else:

```
ocm_api/
  envelope.py     the ONE response shape -- Envelope/Refusal/Codes, .to_dict()
  translate.py    ocm-core/ocm-resolve/ocm-generator error strings -> structured Refusals
  workspace.py    Workspace(repo_root) -- module/cell/component paths, draft-revision
                  convention, and the comment-preserving YAML write path
  resolution.py   resolve_cell() + the NEW rules ocm-resolve has no opinion on: a draft
                  module/component can't resolve into a cell
  discovery.py    describe_schema, get_example, list/describe module & cell, list_frames,
                  and describe_module's ADR-0014 BOM/power/air aggregates
  authoring.py    create_module_draft, update_module, generate_geometry_stub,
                  validate_module, publish_module -- and the verified_by hard refusal
  components.py   create_component_draft, update_component, validate_component,
                  publish_component, list_components, describe_component (ADR-0014)
  composition.py  create_cell, place/move/remove_instance, set_plan, set_joint_state --
                  OCM_TOOL_SLOT_OCCUPIED and orphaned-plan-step/stale-tool: warnings live here
  generation.py   build_scene, check_collision, plan_cell, emit
  api.py          OcmApi -- the facade every client calls through
  mcp_server.py   stdio MCP server, tools mapping 1:1 to OcmApi's verbs
  http_app.py     FastAPI HTTP wrapper over the same OcmApi
```

**The refusal engine lives behind `OcmApi` and nowhere else.** `mcp_server.py` and
`http_app.py` are transports: every tool/route calls the matching `OcmApi` method and
returns `envelope.to_dict()` verbatim, with no reshaping. That's what makes their responses
byte-identical to the library call and to each other for the same verb + arguments (see
`tests/test_transports.py`) -- a GUI drag that overhangs the workspace is refused by the
exact same code path that refuses the agent's YAML (design principle #4).

## The envelope

Every verb returns one shape, whether you call `OcmApi` directly, an MCP tool, or an HTTP
route:

```json
{
  "ok": false,
  "refusals": [{
    "code": "OCM_PARAM_OUT_OF_BOUNDS",
    "path": "plan[2].sequence[1].params.torque_nm",
    "message": "torque_nm=6.0 exceeds drive_screw limit on sd1 (com.accelsolutions.screwdriver.sd50@1.2.0)",
    "allowed": {"min": 0.2, "max": 5.0, "unit": "N.m"},
    "hint": "Reduce torque_nm or select a module whose capability covers 6.0 N.m."
  }],
  "warnings": [],
  "data": null
}
```

`ok=false` is a **result**, not a transport error -- HTTP still answers 200, MCP still
returns a normal tool result. `refusals` carries every violation found in one response, never
first-error-only. Only two codes are named directly in spec/09 (`OCM_PARAM_OUT_OF_BOUNDS`,
`OCM_HUMAN_SIGNATURE_REQUIRED`); the rest (`OCM_WORKSPACE_OVERHANG`, `OCM_DRAFT_MODULE_REFERENCED`,
`OCM_PATH_COLLISION`, ...) are this library's own naming for scenarios the spec describes
narratively -- see `envelope.Codes` for the full set, chosen once so every verb that can hit
the same scenario uses the same code.

`translate.py` never re-implements a check -- it's regexes over the already-stable message
text `ocm-core`/`ocm-resolve`/`ocm-generator` already raise (`ManifestValidationError`,
`CellResolutionError`, `SceneBuildError`, `PoseUnreachableError`, `PathCollisionError`, ...),
re-shaped into `{code, path, message, allowed?, hint?}`. The checks themselves still live
exactly once, in the packages that already implement them.

## New rules (they don't exist upstream -- they live here, once)

- **`safety.verified_by` is never written.** `authoring._strip_verified_by` removes it from
  the document in place before *any* write lands, unconditionally, and returns a
  `OCM_HUMAN_SIGNATURE_REQUIRED` refusal alongside whatever else the write produced. That field is
  a human signature (spec/06); the agent may fill every other safety field, but not this one.
- **A draft module (`revision: 0.x`) cannot resolve into a cell.** `resolution.py` wraps
  `ocm_resolve.resolve_cell` and additionally refuses (`OCM_DRAFT_MODULE_REFERENCED`) if the base
  module or any placed instance is still a draft -- `ocm-resolve` itself has no opinion on
  publishing workflow, so this is genuinely new logic, implemented once here, and every verb
  that resolves a cell (`place_instance`, `set_plan`, `build_scene`, `plan_cell`, ...) gets it
  for free by going through `resolve_with_refusals`.
- **Writes are unconditional; validity gates *publishing*, not *saving*.** `update_module` and
  every cell-composition verb write the document to disk even when the result is `ok:false` --
  iteration is cheap and `git diff` shows every attempt (design principle #3). A module only
  becomes resolvable once `publish_module` succeeds.
- **`set_plan(cell, plan, part=None)`** takes an optional `part` document beyond spec/09's
  literal two-argument signature. spec/09's verb table has no separate `set_part`, but
  `cell.yaml`'s `part:` block (the physical part + named features a `drive_screw` step's `at:`
  resolves against) is structurally required for `plan_cell` to ever succeed. The two are too
  tightly coupled to write independently without a moment where they disagree, so one
  document-granularity write covers both.
- **Cells are addressed by directory name** (`bracket-asm-01`), not by `cell.yaml`'s own
  internal `id:` field (`com.accelsolutions.cell.bracket-asm-01`) -- deliberately different
  from modules, where directory name and manifest id match. Cells are filesystem-addressable
  scratch documents in a way published modules aren't.
- **No verb raises.** Every `OcmApi` method is wrapped (`api._never_raise`) so an exception a
  verb didn't anticipate (a malformed RFC-6902 patch reaching `jsonpatch`/`jsonpointer` in a
  shape nothing here foresaw, say) still comes back as an `OCM_INVALID_ARGUMENT` envelope, never a
  raw exception -- design principle #1 applies to inputs this library's authors didn't think
  of too, not just the ones it has a named refusal code for.
- **`validate_module` checks every declared file, not just `urdf_fragment`/`comms.esi`.**
  `mechanical.geometry.collision` is schema-*required* for every module (unlike the other two,
  which are optional), so it's checked too -- a claimed collision mesh path is exactly as much
  a claim as a claimed URDF fragment. This is why `create_module_draft`'s own scaffold (an
  honest `meshes/TODO_convex.stl` placeholder) doesn't pass `validate_module` until
  `generate_geometry_stub` has actually run.
- **Composition verbs return the workspace bounds on every successful call**
  (`data.workspace_bounds`, `{"x_mm": [...], "y_mm": [...]}`) -- the base module's real X/Y
  footprint (deck *and* guard walls, per `ocm_generator.scene.containment`) is usually larger
  than its nominal `footprint_mm`, and that margin was previously only discoverable by
  tripping a `OCM_WORKSPACE_OVERHANG` refusal once. An agent building a mental model of "how much
  room do I have" should get that from data, not from a near-miss.
- **`place_instance`/`move_instance` never evict or swap.** A `mount.on` naming an attachment
  another instance already occupies is refused (`OCM_TOOL_SLOT_OCCUPIED`, hint naming the
  incumbent) rather than silently displacing it -- a GUI drag and an agent's tool swap both go
  through `remove_instance` first if that's genuinely what's meant.
- **A mutation that orphans a plan step, or leaves another instance's `tool:` field pointing at
  a removed instance, says so in `warnings[]` -- on the same call, whether or not that call is
  also refused for a harder reason.** `remove_instance` is the one verb that can create both:
  a plan step naming the removed instance also trips `resolve_cell`'s own hard
  `OCM_UNKNOWN_MODULE` check (so the warning usually rides alongside a refusal, adding a
  human-readable "here's the blast radius" summary a bare per-step error list doesn't), while a
  stale `tool:` reference (e.g. `robot1: {tool: grip1}`, spec/02's "which end effector is
  mounted" convention) is never cross-checked by `resolve_cell` at all -- without this, removing
  the instance it names would succeed completely silently.
- **Components (ADR-0014) mirror the module lifecycle exactly, with one governing
  difference: transcription, not design.** `create_component_draft` -> `update_component` ->
  `validate_component` -> `publish_component`, same always-write/validate-gates-publish
  discipline -- but `create_component_draft` does NOT pre-fill a schema-valid skeleton the way
  `create_module_draft` does. A module's mount/frames/geometry are DESIGN placeholders an agent
  legitimately starts sketching; a component's `vendor`/`source` are DATASHEET FACTS that
  either are known right now or aren't, so a fresh draft is genuinely minimal
  (`ocm_version`/`id`/`revision`/`kind` only) and `validate_component` on it fails with exactly
  the completion list spec/10 describes ("vendor is a required property", "source is a required
  property"). A component with real gaps (no stated mass, no stated current draw) validates
  fine -- ADR-0014: omission isn't invalidity -- and simply stays unpublished until a human
  says otherwise. Two new schema-additive (v1.1) module fields make the assembly relationship
  real: an optional `components:` list (`{refdes, ref}`) and an optional `source:`
  provenance field on a `comms.signals` entry (`'REFDES.signal_name'`); `ocm-resolve` checks
  both at cell-resolution time (unknown component id/revision, duplicate refdes, a `source`
  naming a signal the referenced component doesn't declare -- codes `OCM_UNKNOWN_COMPONENT`,
  `OCM_DUPLICATE_REFDES`, `OCM_INVALID_SOURCE`). `describe_module` derives a purchasable BOM, a power
  budget per electrical rail, and total air consumption straight from a module's own
  `components:` list -- summing only what every contributing component actually states;  a
  rail/gas with even one silent component is omitted from the totals entirely (never a partial
  sum passed off as complete), with a warning naming the incomplete component.

## Comment-preserving writes

Every write in this repo used to round-trip through `yaml.safe_dump`, which silently destroyed
every comment in the file -- and this repo's YAML comments carry real design intent (ADR
references, `# placeholder -- not authored yet`, unit/provisional-value caveats). `write_yaml`
(in `workspace.py`) now loads the EXISTING file with `ruamel.yaml`'s round-trip mode (a
comment-carrying `CommentedMap`/`CommentedSeq` tree), diffs the old file's plain value against
the new data as an RFC-6902 patch (`jsonpatch.make_patch`, the same library `update_module`'s
own explicit `patch=` verb already uses), and applies that patch to the round-trip tree in
place -- so untouched keys, and their comments, never move. A brand new file is written fresh
(nothing to preserve). One honest limitation: round-trip mode preserves comments, key order,
blank-line grouping, and quoting, but not manual inter-column alignment whitespace
(`id:       foo`) a couple of this repo's earliest, hand-typed files use for visual alignment --
that padding isn't meaningful YAML syntax any round-trip library models as preservable state.
See `tests/test_yaml_comments.py`.

## Running it

```
pip install -e ../ocm-core -e ../ocm-resolve -e "../ocm-generator[tesseract]" -e ".[serve,tesseract,test]"

# MCP server (stdio), against a repo working tree:
ocm-api-mcp --repo /path/to/OCM
# or: python -m ocm_api.mcp_server --repo /path/to/OCM

# FastAPI HTTP wrapper:
ocm-api-http --repo /path/to/OCM --port 8000
# or: python -m ocm_api.http_app --repo /path/to/OCM

# Library, directly:
python -c "from ocm_api import OcmApi; api = OcmApi('/path/to/OCM'); print(api.list_modules().to_dict())"
```

Drop `[tesseract]` to skip Tesseract entirely -- everything works except `check_collision`'s
and `plan_cell`'s (and `emit`'s motion-planning path's) happy path, which refuse with
`OCM_UNAVAILABLE` instead of raising. `[serve]` is only needed to actually run `ocm-api-http`
(FastAPI's `TestClient`, used by the test suite, needs `httpx` but not a real ASGI server).

**Debian/Ubuntu:** the `mcp` dependency pulls in `PyJWT`, and on these distros a system
`python3-jwt` apt package is often already installed without proper `dist-info` metadata --
`pip install` then fails trying to uninstall it before reinstalling. Work around it with:

```
pip install --ignore-installed PyJWT -e ../ocm-core -e ../ocm-resolve -e "../ocm-generator[tesseract]" -e ".[serve,tesseract,test]"
```

Every MCP tool's description embeds the envelope contract and one worked example inline
(`mcp_server._doc`) -- spec/09: "the agent should succeed without reading this spec." Long
outputs (schema subtrees, manifests) come back as structured JSON inside the envelope;
`emit`'s artifacts (URScript, HTML viewers) are always file paths in `data.written`, never
inlined.

## Tests

```
pytest
```

- `test_verbs.py` -- every module/cell verb's happy path (22: 7 discovery, 5 authoring, 6
  composition, 4 generation) -- component verbs get their own full-lifecycle coverage in
  `test_components.py` instead of a separate happy-path pass.
- `test_refusals.py` -- the envelope shape for every refusal code in `envelope.Codes`,
  including `OCM_HUMAN_SIGNATURE_REQUIRED` (confirms the signature is actually absent from the
  written file, not just flagged) and `OCM_DRAFT_MODULE_REFERENCED` (a draft module blocks
  resolution; publishing it makes the same cell resolve).
- `test_components.py` -- the full component lifecycle; a fresh draft's refusal list reads as
  spec/10's own completion list; a deliberately gap-filled (no mass, no current) transcription
  validates cleanly and simply stays unpublished; a module referencing two published
  components resolves into a cell AND aggregates a correct BOM/power budget/air consumption;
  every ADR-0014 refusal path (`OCM_UNKNOWN_COMPONENT`, `OCM_DUPLICATE_REFDES`, `OCM_INVALID_SOURCE`, a
  draft component blocking resolution).
- `test_guardrails.py` -- `place_instance`/`move_instance` onto an occupied `mount.on` refuse
  with `OCM_TOOL_SLOT_OCCUPIED` (and never evict the incumbent -- confirmed by reading the file back
  off disk); `remove_instance` orphaning plan steps warns on the same call that causes it
  (alongside the resulting `OCM_UNKNOWN_MODULE` refusal, since the plan genuinely can't resolve any
  more); `remove_instance` leaving a stale `robot1.tool:` reference warns even when the call
  otherwise succeeds (`ok: true`) since `resolve_cell` never cross-checks that field itself.
- `test_yaml_comments.py` -- a targeted patch to a real, heavily-commented module (frame1200)
  preserves every comment and top-level key order; a targeted patch to a freshly-annotated file
  produces a minimal diff (only the changed field's line differs).
- `test_transports.py` -- the library call, an in-process MCP `call_tool`, and a FastAPI
  `TestClient` call produce canonically-identical JSON (`json.dumps(..., sort_keys=True)`
  equality -- transport-level formatting may differ, content must not) for the same verb +
  arguments, for both a happy path and a refusal.
- `test_acceptance_demo.py` -- spec/09's own "acceptance demo" section, scripted verbatim:
  describe/example a fictional pneumatic pick head -> draft it -> a first attempt with a
  planted trap (a `pose6d` result missing `frame`) is refused with path + hint -> corrected,
  geometry generated, validated, published -> placed into `bracket-asm-01` overhanging the
  workspace (refused, `+X by N mm`) -> moved inside -> `plan_cell` succeeds with a cycle
  table. Asserts at least two distinct refusals occur and the final call succeeds.

Every test runs against a fresh `tmp_path` copy of the repo's real `spec/`, `modules/`, and
`cells/` (see `tests/conftest.py`) -- real, committed manifests (`sd50`, the real
`dh200` draft, the real `bracket-asm-01` cell) give tests something genuine to exercise
without ever mutating this repo's own working tree.
