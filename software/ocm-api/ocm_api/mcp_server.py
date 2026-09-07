# SPDX-License-Identifier: AGPL-3.0-or-later
"""The MCP server (spec/09 "MCP specifics"): one stdio server, launched
against a repo path, tools mapping 1:1 to `OcmApi`'s verbs. Every tool
just calls the matching `OcmApi` method and returns `envelope.to_dict()`
-- no reshaping, so this transport's JSON payload is exactly the library
call's own envelope (see tests/test_envelope_consistency.py).

The authoring workflow (ADR-0014) is two layers, in order:
  datasheet -> COMPONENT (transcription: create_component_draft -> update_component ->
    validate_component -> publish_component) -> a MODULE, designed by a human or an agent
    with human approval, references published components (create_module_draft -> update_module
    -> generate_geometry_stub -> validate_module -> publish_module).
A datasheet describes a purchasable PART -- transcribe it as a component, zero assumption:
a value appears only if the source states it, everything else is omitted, and the resulting
validation refusals ARE the completion list a human works through. A datasheet is NEVER
enough to author a MODULE directly: a module asks design questions (TCP placement,
capabilities, PackML, safety) a datasheet doesn't answer. Creating module or component files
directly with file-editing tools bypasses validation and produces broken definitions (phantom
geometry paths, unpublished revisions, fabricated design values).

Each tool's description embeds the envelope contract (spec/09 design
principle #1) and one worked example -- "the agent should succeed
without reading this spec." Long outputs (schema subtrees, manifests) are
returned as text (they're already inside the JSON envelope); artifacts
(`emit`'s URScript/animation/view) are file paths in `data.written`,
never inlined -- spec/09: "artifacts... as file paths, never inlined."
"""

from __future__ import annotations

import argparse
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from .api import OcmApi
from .prompts import ZERO_ASSUMPTION_DOCTRINE

_ENVELOPE_CONTRACT = (
    "Returns the ocm-api envelope: "
    '{"ok": bool, "refusals": [{"code","path","message","allowed"?,"hint"?}], '
    '"warnings": [str], "data": <verb-specific>}. '
    "ok=false means the call was REFUSED, not that it errored -- render "
    "`refusals` (every one found, not just the first); never treat this as "
    "an exception to catch. `path` is a JSON-path into the document you "
    "submitted; `allowed` (when present) is the machine-usable constraint "
    "(bounds/enum values/known names); `hint` is one actionable next step."
)


def _doc(summary: str, example: str) -> str:
    return f"{summary}\n\n{_ENVELOPE_CONTRACT}\n\nExample:\n{example}"


def build_server(repo_root: str) -> FastMCP:
    api = OcmApi(repo_root)
    mcp = FastMCP(
        name="ocm-api",
        instructions=(
            "OCM's authoring/composition/planning surface (spec/09-ocm-api.md, ADR-0014). "
            "NEVER guess field names -- start with describe_schema and get_example.\n\n"
            + ZERO_ASSUMPTION_DOCTRINE + "\n\n" + _ENVELOPE_CONTRACT
        ),
    )

    # -- Discovery ---------------------------------------------------

    @mcp.tool(description=_doc(
        "The JSON Schema (module by default, or target='component' for the ADR-0014 component "
        "schema), or one section of it (e.g. section='capabilities'). Includes the supported "
        "ocm_version list and the full spec changelog.",
        '  call: describe_schema(section="capabilities")\n'
        '  response: {"ok": true, "data": {"ocm_version": ["1.0","1.1"], "target": "module", "schema": {...}, "changelog": "..."}}',
    ))
    def describe_schema(section: str | None = None, target: str = "module") -> dict[str, Any]:
        return api.describe_schema(section, target=target).to_dict()

    @mcp.tool(description=_doc(
        "The best-matching REAL, committed manifest for a module kind (e.g. sd50 for "
        "end_effector, dh200 for process, gocator for sensor) -- the worked example IS the documentation.",
        '  call: get_example(kind="end_effector")\n'
        '  response: {"ok": true, "data": {"module_id": "com.accelsolutions.screwdriver.sd50", "manifest_yaml": "..."}}',
    ))
    def get_example(kind: str) -> dict[str, Any]:
        return api.get_example(kind).to_dict()

    @mcp.tool(description=_doc(
        "Every module in the registry: id, revision, kind, name, and whether it's still a draft (revision 0.x).",
        "  call: list_modules()\n"
        '  response: {"ok": true, "data": [{"id": "com.accelsolutions.screwdriver.sd50", "revision": "1.2.0", "kind": "end_effector", "draft": false}, ...]}',
    ))
    def list_modules() -> dict[str, Any]:
        return api.list_modules().to_dict()

    @mcp.tool(description=_doc(
        "The full parsed manifest for one module id, including capability signatures. If the "
        "module has a components: list (ADR-0014), also returns DERIVED aggregates -- the "
        "purchasable BOM, power budget per rail, air consumption -- summed only from what its "
        "referenced components actually state; a rail/gas with any contributing component silent "
        "on the relevant number is omitted from the totals entirely (never a partial sum passed "
        "off as complete), with a warning naming which component has the gap.",
        '  call: describe_module(id="com.example.pickhead.pk100")\n'
        '  response: {"ok": true, "data": {"id": "...", "revision": "1.0.0", "draft": false, "manifest": {...}, '
        '"aggregates": {"bom": [{"refdes": "VG1", "id": "com.smc.ejector.zk2-agh", "vendor": "SMC", "part_number": "ZK2-AGH"}], '
        '"power_budget": {"24VDC": {"current_nominal_a": 0.4}}, "air_consumption": 12.0, "air_consumption_units": "Nl/min"}}, "warnings": []}',
    ))
    def describe_module(id: str) -> dict[str, Any]:
        return api.describe_module(id).to_dict()

    @mcp.tool(description=_doc(
        "Every cell in the registry: its directory id, its manifest id, and its name.",
        "  call: list_cells()\n"
        '  response: {"ok": true, "data": [{"cell_id": "bracket-asm-01", "id": "com.accelsolutions.cell.bracket-asm-01", "name": "Bracket Assembly Cell 01"}]}',
    ))
    def list_cells() -> dict[str, Any]:
        return api.list_cells().to_dict()

    @mcp.tool(description=_doc(
        "A resolved cell's composition: instance list, mounts, and plan step count. Unresolvable "
        "issues are reported as `warnings`, not refusals -- describing a broken cell isn't itself an error.",
        '  call: describe_cell(id="bracket-asm-01")\n'
        '  response: {"ok": true, "data": {"cell_id": "bracket-asm-01", "instances": [{"instance": "sd1", "module": "com.accelsolutions.screwdriver.sd50@1.2.0", "mounted_on": "robot1"}, ...]}}',
    ))
    def describe_cell(id: str) -> dict[str, Any]:
        return api.describe_cell(id).to_dict()

    @mcp.tool(description=_doc(
        "Every referenceable frame in a resolved cell -- what a pose6d `frame` field or a "
        "`mount.on` may point at (manifest-declared frames AND real URDF attachment links, e.g. robot1.flange).",
        '  call: list_frames(cell_id="bracket-asm-01")\n'
        '  response: {"ok": true, "data": ["nest1.part_datum", "robot1.flange", "sd1.tcp", ...]}',
    ))
    def list_frames(cell_id: str) -> dict[str, Any]:
        return api.list_frames(cell_id).to_dict()

    # -- Module authoring ---------------------------------------------------

    @mcp.tool(description=_doc(
        "THE entry point for creating any new module -- NEVER create module directories or "
        "write module.yaml by hand with file tools; every module starts here. NEVER author a "
        "module directly from a datasheet -- a datasheet describes a purchasable COMPONENT "
        "(create_component_draft), and a module ASSEMBLES published components plus design "
        "judgment (TCP, capabilities, PackML, safety) a datasheet never answers (ADR-0014). "
        "Scaffolds modules/<id>/module.yaml (storage location is derived from the id -- never ask "
        "where to put it) with a minimal, already schema-valid manifest for `kind`, "
        "filled with honest TODO placeholders. revision is always 0.1.0 (a draft) -- excluded from cell "
        "resolution until publish_module. ADR-0011: agents never hand-write URDF; use generate_geometry_stub next.",
        '  call: create_module_draft(id="com.example.pickhead.pk100", kind="end_effector")\n'
        '  response: {"ok": true, "data": {"id": "com.example.pickhead.pk100", "revision": "0.1.0", "draft": true}}',
    ))
    def create_module_draft(id: str, kind: str) -> dict[str, Any]:
        return api.create_module_draft(id, kind).to_dict()

    @mcp.tool(description=_doc(
        "Write a module manifest -- a full replacement document (`manifest`) or an RFC-6902 patch "
        "(`patch`), exactly one of the two. ALWAYS WRITES, even if invalid (ok=false then, with every "
        "schema violation as a refusal) -- validation gates publish_module, not this call, so iteration "
        "is cheap and the diff shows the attempt. Exception: safety.verified_by is a human signature and "
        "is stripped before the write lands, every time (code OCM_HUMAN_SIGNATURE_REQUIRED).",
        '  call: update_module(id="com.example.pickhead.pk100", manifest={"ocm_version": "1.1", ...})\n'
        '  response: {"ok": false, "data": null, "refusals": [{"code": "OCM_SCHEMA_INVALID", "path": "capabilities[0].results.part_pose", "message": "\'frame\' is a required property", "hint": "..."}]}',
    ))
    def update_module(id: str, manifest: dict[str, Any] | None = None, patch: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return api.update_module(id, manifest=manifest, patch=patch).to_dict()

    @mcp.tool(description=_doc(
        "Generate a box-primitive URDF fragment sized footprint_mm x height_mm and register it as this "
        "module's collision geometry -- ADR-0011: agents never hand-write URDF; real meshes replace this later.",
        '  call: generate_geometry_stub(id="com.example.pickhead.pk100", footprint_mm=[80, 60], height_mm=40)\n'
        '  response: {"ok": true, "data": {"id": "com.example.pickhead.pk100", "urdf_fragment": "urdf/generated_box.urdf.xacro"}}',
    ))
    def generate_geometry_stub(id: str, footprint_mm: list[float], height_mm: float, kind: str | None = None) -> dict[str, Any]:
        fp = (footprint_mm[0], footprint_mm[1])
        return api.generate_geometry_stub(id, fp, height_mm, kind=kind).to_dict()

    @mcp.tool(description=_doc(
        "Full validation: schema PLUS cross-file checks schema validation alone can't do (does "
        "geometry.urdf_fragment exist on disk, does comms.esi exist, if declared).",
        '  call: validate_module(id="com.example.pickhead.pk100")\n'
        '  response: {"ok": true, "data": {"id": "com.example.pickhead.pk100", "valid": true}}',
    ))
    def validate_module(id: str) -> dict[str, Any]:
        return api.validate_module(id).to_dict()

    @mcp.tool(description=_doc(
        "Validate, then set revision (must be >= 1.0.0 -- a real SemVer, not another 0.x draft) -- the "
        "module becomes resolvable into cells only after this succeeds.",
        '  call: publish_module(id="com.example.pickhead.pk100", revision="1.0.0")\n'
        '  response: {"ok": true, "data": {"id": "com.example.pickhead.pk100", "revision": "1.0.0", "published": true}}',
    ))
    def publish_module(id: str, revision: str) -> dict[str, Any]:
        return api.publish_module(id, revision).to_dict()

    # -- Component authoring (ADR-0014) ---------------------------------------------------

    @mcp.tool(description=_doc(
        "A datasheet becomes a COMPONENT -- THE entry point for transcribing any datasheet, "
        "manual, or catalog page. NEVER author a module from a datasheet. Scaffolds "
        "components/<id>/component.yaml with ONLY ocm_version/id/revision/kind -- unlike "
        "create_module_draft, no TODO placeholders for vendor/source: those are facts you either "
        "have from the document in front of you or don't, and inventing one would be exactly the "
        "fabrication ADR-0014 exists to stop. revision is always 0.1.0 (a draft) -- excluded from "
        "module components: references until publish_component.",
        '  call: create_component_draft(id="com.smc.ejector.zk2-agh", kind="vacuum_ejector")\n'
        '  response: {"ok": true, "data": {"id": "com.smc.ejector.zk2-agh", "revision": "0.1.0", "draft": true}}',
    ))
    def create_component_draft(id: str, kind: str) -> dict[str, Any]:
        return api.create_component_draft(id, kind).to_dict()

    @mcp.tool(description=_doc(
        "Write a component definition -- a full replacement document (`manifest`) or an RFC-6902 "
        "patch (`patch`), exactly one of the two. ALWAYS WRITES, even if invalid (ok=false then, "
        "with every schema violation as a refusal) -- validation gates publish_component, not this "
        "call. ZERO ASSUMPTION (ADR-0014): a value goes in only if the source document states it -- "
        "never convert units, record every value in the exact unit the source prints, verbatim "
        "('bar', 'psi', 'VDC'). A stated RANGE stays a range (pressure_min/pressure_max plus "
        "pressure_units; flow plus flow_units), never narrowed to one number, and anything the datasheet "
        "doesn't answer is OMITTED, never estimated, never copied from another component. Leave the draft "
        "incomplete and report the refusals as the human's completion list -- do not guess to make "
        "validation pass.",
        '  call: update_component(id="com.smc.ejector.zk2-agh", manifest={"ocm_version": "1.1", "vendor": "SMC", "source": {"kind": "datasheet", "ref": "ZK2-AGH catalog page, 2024 ed."}, ...})\n'
        '  response: {"ok": false, "data": null, "refusals": [{"code": "OCM_SCHEMA_INVALID", "path": "source", "message": "\'ref\' is a required property", "hint": "..."}]}',
    ))
    def update_component(id: str, manifest: dict[str, Any] | None = None, patch: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return api.update_component(id, manifest=manifest, patch=patch).to_dict()

    @mcp.tool(description=_doc(
        "Full schema validation. A schema-required field left out by an "
        "honest transcription (vendor, source) shows up here as a refusal -- that refusal list IS "
        "the handoff to a human, not a bug to work around.",
        '  call: validate_component(id="com.smc.ejector.zk2-agh")\n'
        '  response: {"ok": true, "data": {"id": "com.smc.ejector.zk2-agh", "valid": true}}',
    ))
    def validate_component(id: str) -> dict[str, Any]:
        return api.validate_component(id).to_dict()

    @mcp.tool(description=_doc(
        "Validate a carrier TYPE manifest (carriers/<id>/carrier.yaml, ADR-0031): schema, the "
        "no-control rule (state_machine/comms/capabilities refuse OCM_CARRIER_TYPE_HAS_CONTROL -- "
        "a carrier has no controller), and that declared geometry artifacts exist and parse.",
        '  call: validate_carrier(id="com.example.carrier.pallet")\n'
        '  response: {"ok": true, "data": {"id": "com.example.carrier.pallet", "valid": true}}',
    ))
    def validate_carrier(id: str) -> dict[str, Any]:
        return api.validate_carrier(id).to_dict()

    @mcp.tool(description=_doc(
        "Validate one document's claims file (claims/<hex>/claims.yaml, ADR-0035), addressed by "
        "its document hash: schema, vocabulary binding (declared shape, subject-taking, x- keys "
        "marked unbound in warnings), and stored-id verification against the canonical "
        "serialization -- an edited ingested record fails here by construction.",
        '  call: validate_claims(document_hash="sha256:c03286e02ea14374f3b7e69ffb4d9616125bc7db49b9f397a1cb716211a290bb")\n'
        '  response: {"ok": true, "data": {"document": "sha256:c032...", "claims": 12, "valid": true}}',
    ))
    def validate_claims(document_hash: str) -> dict[str, Any]:
        return api.validate_claims(document_hash).to_dict()

    @mcp.tool(description=_doc(
        "Draft a split of one stuffed text claim into candidate claims (ADR-0035 D1) -- READ-ONLY. "
        "Candidates from a uniform grammar inherit the source key; heterogeneous statements come "
        "back with key: null because choosing a vocabulary key is design judgment. Leftover text "
        "is returned, never dropped. Review, assign keys, then call append_claims.",
        '  call: propose_claim_split(document_hash="sha256:9ce6...", claim_id="sha256:dff3...")\n'
        '  response: {"ok": true, "data": {"grammar": "alternates", "candidates": [...], "leftovers": []}}',
    ))
    def propose_claim_split(document_hash: str, claim_id: str) -> dict[str, Any]:
        return api.propose_claim_split(document_hash, claim_id).to_dict()

    @mcp.tool(description=_doc(
        "Append reviewed claims (and optionally a transcription pass's vocabulary-pinned "
        "attestation) to an existing claims file -- ADR-0035 D7's two legal mutations, and the ONE "
        "write path. Ids are computed server-side, never supplied; the whole updated file must "
        "pass full validation before anything is written; existing records are never touched. "
        "Idempotent per record: a claim whose id the file already holds is skipped and reported, "
        "so a retried submission is harmless (ADR-0038 D11).",
        '  call: append_claims(document_hash="sha256:9ce6...", claims=[{...}], attestation={"vocab_version": "1.1", "date": "2026-09-01"})\n'
        '  response: {"ok": true, "data": {"written": 6, "skipped": 0, "skipped_ids": [], "ids": ["sha256:..."], "claims": 19}}',
    ))
    def append_claims(document_hash: str, claims: list[dict[str, Any]], attestation: dict[str, Any] | None = None) -> dict[str, Any]:
        return api.append_claims(document_hash, claims, attestation=attestation).to_dict()

    @mcp.tool(description=_doc(
        "Validate, then set revision (must be >= 1.0.0 -- a real SemVer, not another 0.x draft) -- "
        "the component becomes referenceable from a module's components: list only after this "
        "succeeds.",
        '  call: publish_component(id="com.smc.ejector.zk2-agh", revision="1.0.0")\n'
        '  response: {"ok": true, "data": {"id": "com.smc.ejector.zk2-agh", "revision": "1.0.0", "published": true}}',
    ))
    def publish_component(id: str, revision: str) -> dict[str, Any]:
        return api.publish_component(id, revision).to_dict()

    @mcp.tool(description=_doc(
        "Every component in the registry: id, revision, kind, vendor, and whether it's still a draft (revision 0.x).",
        "  call: list_components()\n"
        '  response: {"ok": true, "data": [{"id": "com.smc.ejector.zk2-agh", "revision": "1.0.0", "kind": "vacuum_ejector", "vendor": "SMC", "draft": false}, ...]}',
    ))
    def list_components() -> dict[str, Any]:
        return api.list_components().to_dict()

    @mcp.tool(description=_doc(
        "The full parsed component definition for one id.",
        '  call: describe_component(id="com.smc.ejector.zk2-agh")\n'
        '  response: {"ok": true, "data": {"id": "...", "revision": "1.0.0", "draft": false, "component": {...}}}',
    ))
    def describe_component(id: str) -> dict[str, Any]:
        return api.describe_component(id).to_dict()

    @mcp.tool(description=_doc(
        "Delete a component permanently -- removes its directory (manifest + attachments) from "
        "the workspace. Unconditional, like every other write here: if a module still references "
        "this component, the delete still happens and the response's warnings name which module(s) "
        "will no longer resolve. This is a deliberate, destructive, human-gated action -- it is not "
        "offered to the /agent/chat assistant.",
        '  call: delete_component(id="com.smc.ejector.zk2-agh")\n'
        '  response: {"ok": true, "data": {"id": "com.smc.ejector.zk2-agh", "deleted": true}}',
    ))
    def delete_component(id: str) -> dict[str, Any]:
        return api.delete_component(id).to_dict()

    # -- Cell composition ---------------------------------------------------

    @mcp.tool(description=_doc(
        "Scaffold cells/<id>/cell.yaml with the base module + the standard datum/grid conventions.",
        '  call: create_cell(id="my-cell", base_module="com.accelsolutions.base.frame1200@2.0.0")\n'
        '  response: {"ok": true, "data": {"cell_id": "my-cell", "id": "com.example.cell.my-cell"}}',
    ))
    def create_cell(id: str, base_module: str) -> dict[str, Any]:
        return api.create_cell(id, base_module).to_dict()

    @mcp.tool(description=_doc(
        "Add a module instance to a cell (mount is {\"pose\": {\"xyz_mm\":[...], \"rpy_deg\":[...]}} or "
        "{\"on\": \"other_instance.attachment_link\"}). ALWAYS writes, then re-resolves and rebuilds the "
        "scene -- live refusals: unknown module, revision mismatch, dangling mount.on, workspace "
        "overhang (with the exact mm + direction, e.g. \"+X by 2.2 mm\"), or OCM_TOOL_SLOT_OCCUPIED if "
        "mount.on names an attachment another instance already occupies -- this NEVER evicts or swaps "
        "the incumbent; remove_instance it first if that's what you mean.",
        '  call: place_instance(cell="bracket-asm-01", instance="pk1", module="com.example.pickhead.pk100@1.0.0", mount={"pose": {"xyz_mm": [2000, 300, 0], "rpy_deg": [0,0,0]}})\n'
        '  response: {"ok": false, "refusals": [{"code": "OCM_WORKSPACE_OVERHANG", "path": "modules.pk1.mount", "message": "...+X by 800.0 mm", "hint": "Move pk1 inside the base footprint (...)."}]}',
    ))
    def place_instance(
        cell: str, instance: str, module: str, mount: dict[str, Any], requires: dict[str, str] | None = None
    ) -> dict[str, Any]:
        # ADR-0023: `requires` binds a capability's abstract requirement to a
        # concrete `instance.signal` (e.g. {"workpiece_secured": "nest1.clamped"}).
        return api.place_instance(cell, instance, module, mount, requires=requires).to_dict()

    @mcp.tool(description=_doc(
        "Reposition an already-placed instance's mount. Same live-refusal behavior as place_instance, "
        "including OCM_TOOL_SLOT_OCCUPIED if the new mount.on is already taken by a DIFFERENT instance.",
        '  call: move_instance(cell="bracket-asm-01", instance="pk1", mount={"pose": {"xyz_mm": [600, 300, 0], "rpy_deg": [0,0,0]}})\n'
        '  response: {"ok": true, "data": {"cell_id": "bracket-asm-01", "instances": ["cam1","feed1","nest1","pk1","robot1","sd1"]}}',
    ))
    def move_instance(cell: str, instance: str, mount: dict[str, Any]) -> dict[str, Any]:
        return api.move_instance(cell, instance, mount).to_dict()

    @mcp.tool(description=_doc(
        "Remove a placed instance from a cell. If any plan step still names it, or another instance's "
        "`tool:` field still points at it, the removal still goes through (ok may be true or false, "
        "depending on whether the plan reference alone is now enough to break resolution) but "
        "`warnings[]` names the impact on THIS SAME call -- e.g. \"removing sd1 orphans 3 plan steps "
        "(drive_screw ×3); the plan will no longer resolve.\"",
        '  call: remove_instance(cell="bracket-asm-01", instance="pk1")\n'
        '  response: {"ok": true, "data": {"cell_id": "bracket-asm-01", "instances": ["cam1","feed1","nest1","robot1","sd1"]}, "warnings": []}',
    ))
    def remove_instance(cell: str, instance: str) -> dict[str, Any]:
        return api.remove_instance(cell, instance).to_dict()

    @mcp.tool(description=_doc(
        "Write a cell's whole `plan:` list (and, optionally, its `part:` block -- the physical part + "
        "named features a drive_screw step's `at:` resolves against) and re-resolve -- refusals for "
        "unknown ops, out-of-bounds params, or a reference to a module instance that doesn't exist.",
        '  call: set_plan(cell="my-cell", plan=[{"step": "fasten", "module": "sd1", "op": "drive_screw", "params": {"torque_nm": 2.4}}])\n'
        '  response: {"ok": true, "data": {"cell_id": "my-cell", "instances": ["robot1", "sd1"]}}',
    ))
    def set_plan(cell: str, plan: list[Any], part: dict[str, Any] | None = None) -> dict[str, Any]:
        return api.set_plan(cell, plan, part=part).to_dict()

    @mcp.tool(description=_doc(
        "Set a robot instance's home joint_state (radians, joint name -> value).",
        '  call: set_joint_state(cell="bracket-asm-01", instance="robot1", joints={"shoulder_lift_joint": -1.5708, "elbow_joint": 1.5708})\n'
        '  response: {"ok": true, "data": {"cell_id": "bracket-asm-01", "instances": [...]}}',
    ))
    def set_joint_state(cell: str, instance: str, joints: dict[str, float]) -> dict[str, Any]:
        return api.set_joint_state(cell, instance, joints).to_dict()

    # -- Checking & generation ---------------------------------------------------

    @mcp.tool(description=_doc(
        "Compose the cell's URDF and return link/joint counts plus the workspace containment result.",
        '  call: build_scene(cell="bracket-asm-01")\n'
        '  response: {"ok": true, "data": {"cell_id": "bracket-asm-01", "n_links": 18, "n_joints": 17, "instances": [...]}}',
    ))
    def build_scene(cell: str) -> dict[str, Any]:
        return api.build_scene(cell).to_dict()

    @mcp.tool(description=_doc(
        "A real Tesseract discrete contact check at the cell's composed state -- needs the `tesseract` "
        "extra (code OCM_UNAVAILABLE if it isn't installed). Refusals name each colliding instance pair and penetration depth.",
        '  call: check_collision(cell="bracket-asm-01")\n'
        '  response: {"ok": true, "data": {"cell_id": "bracket-asm-01", "margin_mm": 1.0, "contacts": []}}',
    ))
    def check_collision(cell: str, collision_margin_mm: float = 1.0) -> dict[str, Any]:
        return api.check_collision(cell, collision_margin_mm=collision_margin_mm).to_dict()

    @mcp.tool(description=_doc(
        "Plan the cell's fastening sequence end to end (IK, collision-checked joint-space path, cycle-time "
        "table) -- needs the `tesseract` extra. Refusals name the pose (OCM_POSE_UNREACHABLE) or the segment + "
        "colliding pair + fraction along it (OCM_PATH_COLLISION).",
        '  call: plan_cell(cell="bracket-asm-01")\n'
        '  response: {"ok": true, "data": {"holes": ["hole_1","hole_2","hole_3"], "cycle_table": [...], "total_s": 15.6}}',
    ))
    def plan_cell(cell: str, collision_margin_mm: float = 1.0, path_samples: int = 50) -> dict[str, Any]:
        return api.plan_cell(cell, collision_margin_mm=collision_margin_mm, path_samples=path_samples).to_dict()

    @mcp.tool(description=_doc(
        "Write generated artifacts to disk -- URScript, an animated HTML viewer, and/or a static HTML "
        "viewer (any combination; omit an argument to skip it). Returns file PATHS in data.written, never "
        "inlines file content.",
        '  call: emit(cell="bracket-asm-01", urscript="/tmp/out.script", view="/tmp/cell.html")\n'
        '  response: {"ok": true, "data": {"cell_id": "bracket-asm-01", "written": {"urscript": "/tmp/out.script", "view": "/tmp/cell.html"}}}',
    ))
    def emit(
        cell: str,
        urscript: str | None = None,
        animation: str | None = None,
        view: str | None = None,
        collision_margin_mm: float = 1.0,
        path_samples: int = 50,
    ) -> dict[str, Any]:
        return api.emit(
            cell, urscript=urscript, animation=animation, view=view,
            collision_margin_mm=collision_margin_mm, path_samples=path_samples,
        ).to_dict()

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(prog="ocm-api-mcp", description="ocm-api's MCP server (stdio).")
    parser.add_argument(
        "--repo", type=str, default=os.environ.get("OCM_API_REPO", "."),
        help="Path to the OCM repo working tree this server operates against (default: $OCM_API_REPO or cwd).",
    )
    args = parser.parse_args()
    server = build_server(args.repo)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
