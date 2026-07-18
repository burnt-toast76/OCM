# SPDX-License-Identifier: AGPL-3.0-or-later
"""Module authoring verbs (spec/09). `create_module_draft` scaffolds a
schema-valid `revision: 0.x` starting point (ADR-0011: "agents never
hand-write URDF" -- geometry is generated too, see `generate_geometry_stub`).
`update_module` always writes (spec/09: "validation gates *publishing*,
not *saving*" -- cheap iteration, the diff shows every attempt) with ONE
hard exception: `safety.verified_by` is a human signature (spec/06) and is
stripped before the write lands, every time, regardless of how the rest of
the document validates.
"""

from __future__ import annotations

import re
from typing import Any

import jsonpatch

from ocm_core import load_schema
from ocm_core.loader import validate_module_dict

from .envelope import Codes, Envelope, Refusal, single_refusal
from .translate import schema_violation_to_refusal
from .workspace import Workspace, is_draft_revision, read_yaml, write_yaml

DRAFT_REVISION = "0.1.0"

_REVISION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _todo_capability() -> dict[str, Any]:
    return {"name": "todo_op", "summary": "TODO: describe what this capability does (the agent-facing surface)."}


def _todo_comms() -> dict[str, Any]:
    return {
        "protocol": "ethercat",
        "signals": [
            {"name": "packml_cmd", "direction": "output", "type": "uint16", "role": "packml_cmd"},
            {"name": "packml_state", "direction": "input", "type": "uint16", "role": "packml_state"},
        ],
    }


def _skeleton_manifest(module_id: str, kind: str) -> dict[str, Any]:
    """A minimal manifest that already validates against the schema for
    `kind` -- every field a real manifest of this kind requires, filled
    with an honest TODO placeholder, not omitted (spec/09: "pre-filled
    from the kind's schema requirements").
    """
    doc: dict[str, Any] = {
        "ocm_version": "1.1",
        "id": module_id,
        "revision": DRAFT_REVISION,
        "kind": kind,
        "license": "CERN-OHL-S-2.0",
        "name": module_id.rsplit(".", 1)[-1],
        "mechanical": {
            "mount": {"interface": "custom", "footprint_mm": [100.0, 100.0]},
            "frames": {"origin": {"xyz_mm": [0.0, 0.0, 0.0], "note": "TODO: mounting datum"}},
            "geometry": {"collision": "meshes/TODO_convex.stl"},
            "mass_kg": 1.0,
        },
        "state_machine": {
            "model": "packml",
            "implements": [
                "idle", "starting", "execute", "completing", "complete",
                "resetting", "aborting", "aborted", "clearing", "stopping", "stopped",
            ],
            "abort_safe": False,
        },
    }

    if kind == "end_effector":
        doc["mechanical"]["mount"]["interface"] = "iso-9409-1-a50"
        doc["mechanical"]["frames"]["tcp"] = {"xyz_mm": [0.0, 0.0, 50.0], "note": "TODO: tool center point"}
        doc["mechanical"]["com_mm"] = [0.0, 0.0, 25.0]
        doc["capabilities"] = [_todo_capability()]
        doc["comms"] = _todo_comms()
    elif kind == "process":
        doc["capabilities"] = [_todo_capability()]
        doc["comms"] = _todo_comms()
        doc["process"] = {}
        doc["safety"] = {}
    elif kind == "feeder":
        doc["mechanical"]["frames"]["pick"] = {"xyz_mm": [0.0, 0.0, 0.0], "note": "TODO: where the part presents"}
        doc["capabilities"] = [_todo_capability()]
        doc["comms"] = _todo_comms()
    elif kind == "robot":
        doc["mechanical"]["mount"]["interface"] = "ocm-base-grid-50"
        doc["mechanical"]["geometry"]["urdf_fragment"] = "urdf/TODO.urdf.xacro"
        doc["comms"] = _todo_comms()

    return doc


def create_module_draft(ws: Workspace, module_id: str, kind: str) -> Envelope:
    if ws.module_exists(module_id):
        return single_refusal(Codes.ALREADY_EXISTS, path=f"modules['{module_id}']", message=f"a module {module_id!r} already exists")

    known_kinds = load_schema(ws.schema_path)["properties"]["kind"]["enum"]
    if kind not in known_kinds:
        return single_refusal(Codes.INVALID_ARGUMENT, path="kind", message=f"{kind!r} is not a known kind", allowed={"values": known_kinds})

    doc = _skeleton_manifest(module_id, kind)
    write_yaml(ws.module_path(module_id), doc)
    return Envelope.succeed({"id": module_id, "revision": DRAFT_REVISION, "draft": True, "path": str(ws.module_path(module_id)), "manifest": doc})


def _strip_verified_by(doc: dict[str, Any]) -> Refusal | None:
    """Spec/09 hard rule: "The API refuses to write `safety.verified_by`."
    That field is a human signature (spec/06); code HUMAN_SIGNATURE_REQUIRED.
    Mutates `doc` in place (removes the field) so the caller's subsequent
    write genuinely never persists it -- not merely reports an error while
    still saving it.
    """
    safety = doc.get("safety")
    if isinstance(safety, dict) and safety.get("verified_by"):
        del safety["verified_by"]
        return Refusal(
            code=Codes.HUMAN_SIGNATURE_REQUIRED,
            path="safety.verified_by",
            message="safety.verified_by is a human signature (spec/06) -- the API will not write it.",
            hint="Have a qualified person sign off out of band and commit that edit directly, not through this API.",
        )
    return None


def update_module(ws: Workspace, module_id: str, manifest: dict[str, Any] | None = None, patch: list[dict[str, Any]] | None = None) -> Envelope:
    if (manifest is None) == (patch is None):
        return single_refusal(Codes.INVALID_ARGUMENT, path="$", message="update_module needs exactly one of `manifest` or `patch`")

    if patch is not None:
        if not ws.module_exists(module_id):
            return single_refusal(Codes.NOT_FOUND, path=f"modules['{module_id}']", message=f"no module {module_id!r} to patch")
        current = read_yaml(ws.module_path(module_id)) or {}
        try:
            doc = jsonpatch.apply_patch(current, patch)
        except jsonpatch.JsonPatchException as e:
            return single_refusal(Codes.INVALID_ARGUMENT, path="$", message=f"invalid RFC-6902 patch: {e}")
    else:
        doc = dict(manifest)  # type: ignore[arg-type]

    verified_by_refusal = _strip_verified_by(doc)

    write_yaml(ws.module_path(module_id), doc)

    schema = load_schema(ws.schema_path)
    errors = validate_module_dict(doc, schema)
    refusals = [schema_violation_to_refusal(e) for e in errors]
    if verified_by_refusal is not None:
        refusals.insert(0, verified_by_refusal)

    if refusals:
        return Envelope.refuse(refusals)

    revision = str(doc.get("revision", "0.0.0"))
    return Envelope.succeed({"id": doc.get("id", module_id), "revision": revision, "draft": is_draft_revision(revision), "path": str(ws.module_path(module_id))})


def generate_geometry_stub(ws: Workspace, module_id: str, footprint_mm: tuple[float, float], height_mm: float, kind: str | None = None) -> Envelope:
    """A box-primitive URDF fragment sized `footprint_mm` x `height_mm`,
    registered as this module's `geometry.urdf_fragment` (and, until real
    CAD replaces it, its `collision` mesh too). ADR-0011: agents never
    hand-write URDF -- this is the generator.
    """
    if not ws.module_exists(module_id):
        return single_refusal(Codes.NOT_FOUND, path=f"modules['{module_id}']", message=f"no module {module_id!r} in this workspace")

    x_mm, y_mm = footprint_mm
    x_m, y_m, z_m = x_mm / 1000.0, y_mm / 1000.0, height_mm / 1000.0
    fragment_rel = "urdf/generated_box.urdf.xacro"
    fragment_path = ws.module_dir(module_id) / fragment_rel

    urdf_xml = (
        '<?xml version="1.0"?>\n'
        '<robot name="frag">\n'
        '  <link name="origin">\n'
        "    <collision>\n"
        f'      <origin xyz="0 0 {z_m / 2:.6g}" rpy="0 0 0"/>\n'
        f'      <geometry><box size="{x_m:.6g} {y_m:.6g} {z_m:.6g}"/></geometry>\n'
        "    </collision>\n"
        "  </link>\n"
        "</robot>\n"
    )
    fragment_path.parent.mkdir(parents=True, exist_ok=True)
    fragment_path.write_text(urdf_xml, encoding="utf-8")

    doc = read_yaml(ws.module_path(module_id)) or {}
    mechanical = doc.setdefault("mechanical", {})
    mechanical.setdefault("mount", {})["footprint_mm"] = [x_mm, y_mm]
    mechanical.setdefault("geometry", {})["urdf_fragment"] = fragment_rel
    mechanical["geometry"]["collision"] = fragment_rel
    write_yaml(ws.module_path(module_id), doc)

    return Envelope.succeed({"id": module_id, "urdf_fragment": fragment_rel, "fragment_path": str(fragment_path)})


def validate_module(ws: Workspace, module_id: str) -> Envelope:
    """Full validation including cross-file checks schema validation alone
    can't do -- does `geometry.urdf_fragment` exist, does `comms.esi`
    exist, if declared.
    """
    if not ws.module_exists(module_id):
        return single_refusal(Codes.NOT_FOUND, path=f"modules['{module_id}']", message=f"no module {module_id!r} in this workspace")

    doc = read_yaml(ws.module_path(module_id)) or {}
    schema = load_schema(ws.schema_path)
    errors = validate_module_dict(doc, schema)
    refusals = [schema_violation_to_refusal(e) for e in errors]

    module_dir = ws.module_dir(module_id)
    urdf_fragment = doc.get("mechanical", {}).get("geometry", {}).get("urdf_fragment")
    if urdf_fragment and not (module_dir / urdf_fragment).is_file():
        refusals.append(
            Refusal(
                code=Codes.NOT_FOUND,
                path="mechanical.geometry.urdf_fragment",
                message=f"{urdf_fragment!r} does not exist under {module_dir}",
                hint="generate_geometry_stub(...) first, or point at a real file.",
            )
        )
    esi = doc.get("comms", {}).get("esi")
    if esi and not (module_dir / esi).is_file():
        refusals.append(Refusal(code=Codes.NOT_FOUND, path="comms.esi", message=f"{esi!r} does not exist under {module_dir}"))

    if refusals:
        return Envelope.refuse(refusals)
    return Envelope.succeed({"id": module_id, "valid": True})


def publish_module(ws: Workspace, module_id: str, revision: str) -> Envelope:
    if not ws.module_exists(module_id):
        return single_refusal(Codes.NOT_FOUND, path=f"modules['{module_id}']", message=f"no module {module_id!r} in this workspace")
    if not _REVISION_RE.match(revision):
        return single_refusal(Codes.INVALID_ARGUMENT, path="revision", message=f"{revision!r} is not a valid SemVer (X.Y.Z)")
    if is_draft_revision(revision):
        return single_refusal(
            Codes.DRAFT_NOT_PUBLISHABLE,
            path="revision",
            message=f"{revision!r} is itself a 0.x draft revision -- publishing requires a real (>=1.0.0) release",
            hint="Choose a revision whose major version is >= 1.",
        )

    validation = validate_module(ws, module_id)
    if not validation.ok:
        return validation

    doc = read_yaml(ws.module_path(module_id)) or {}
    doc["revision"] = revision
    write_yaml(ws.module_path(module_id), doc)

    return Envelope.succeed({"id": doc.get("id", module_id), "revision": revision, "draft": False, "published": True})
