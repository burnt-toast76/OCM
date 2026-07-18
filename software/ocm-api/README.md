# ocm-api

**The one programmatic surface** (ADR-0012: "the GUI and the AI agent are clients of one
API"). spec/09-ocm-api.md's tool surface, implemented exactly, and nowhere else:

```
ocm_api/
  envelope.py     the ONE response shape -- Envelope/Refusal/Codes, .to_dict()
  translate.py    ocm-core/ocm-resolve/ocm-generator error strings -> structured Refusals
  workspace.py    Workspace(repo_root) -- module/cell paths, draft-revision convention
  resolution.py   resolve_cell() + the one NEW rule: a draft module can't resolve into a cell
  discovery.py    describe_schema, get_example, list/describe module & cell, list_frames
  authoring.py    create_module_draft, update_module, generate_geometry_stub,
                  validate_module, publish_module -- and the verified_by hard refusal
  composition.py  create_cell, place/move/remove_instance, set_plan, set_joint_state
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
    "code": "PARAM_OUT_OF_BOUNDS",
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
first-error-only. Only two codes are named directly in spec/09 (`PARAM_OUT_OF_BOUNDS`,
`HUMAN_SIGNATURE_REQUIRED`); the rest (`WORKSPACE_OVERHANG`, `DRAFT_MODULE_REFERENCED`,
`PATH_COLLISION`, ...) are this library's own naming for scenarios the spec describes
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
  `HUMAN_SIGNATURE_REQUIRED` refusal alongside whatever else the write produced. That field is
  a human signature (spec/06); the agent may fill every other safety field, but not this one.
- **A draft module (`revision: 0.x`) cannot resolve into a cell.** `resolution.py` wraps
  `ocm_resolve.resolve_cell` and additionally refuses (`DRAFT_MODULE_REFERENCED`) if the base
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
`UNAVAILABLE` instead of raising. `[serve]` is only needed to actually run `ocm-api-http`
(FastAPI's `TestClient`, used by the test suite, needs `httpx` but not a real ASGI server).

Every MCP tool's description embeds the envelope contract and one worked example inline
(`mcp_server._doc`) -- spec/09: "the agent should succeed without reading this spec." Long
outputs (schema subtrees, manifests) come back as structured JSON inside the envelope;
`emit`'s artifacts (URScript, HTML viewers) are always file paths in `data.written`, never
inlined.

## Tests

```
pytest
```

- `test_verbs.py` -- every verb's happy path (all 22: 7 discovery, 5 authoring, 5
  composition, 4 generation, plus `create_cell`).
- `test_refusals.py` -- the envelope shape for every refusal code in `envelope.Codes`,
  including `HUMAN_SIGNATURE_REQUIRED` (confirms the signature is actually absent from the
  written file, not just flagged) and `DRAFT_MODULE_REFERENCED` (a draft module blocks
  resolution; publishing it makes the same cell resolve).
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
