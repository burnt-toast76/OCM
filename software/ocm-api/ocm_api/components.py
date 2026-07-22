# SPDX-License-Identifier: AGPL-3.0-or-later
"""Component authoring + discovery verbs (ADR-0014, spec/10). Mirrors
authoring.py's module lifecycle exactly (create_*_draft -> update_* ->
validate_* -> publish_*, always-write, validation gates publishing not
saving) and discovery.py's list_*/describe_* shape -- same envelope, same
draft convention (revision 0.x), same "write anyway, report every
violation" discipline. Two real differences, both ADR-0014 policy, not
oversights:

- `create_component_draft` does NOT pre-fill a schema-valid skeleton the
  way create_module_draft does. A module's mount/frames/geometry fields
  are DESIGN placeholders an agent legitimately starts sketching before
  the human refines them; a component's vendor/source are DATASHEET FACTS
  that either are known right now or aren't -- inventing a "TODO" string
  for them would be exactly the fabrication ADR-0014 exists to stop. The
  scaffold is genuinely minimal (ocm_version/id/revision/kind only), so a
  freshly created draft fails validate_component with precisely the
  completion list spec/10 describes: "vendor" and "source" required.
- No verified_by handling -- components carry no `safety` block at all
  (spec/10: PL/guarding/safe-state judgment is module-layer, never
  transcribed here), so there is nothing to strip.
"""

from __future__ import annotations

import re
import shutil
from typing import Any

import jsonpatch
import jsonpointer

from ocm_core import load_schema
from ocm_core.loader import validate_module_dict

from .envelope import Codes, Envelope, Refusal, single_refusal
from .translate import schema_violation_to_refusal
from .workspace import Workspace, is_draft_revision, read_yaml, write_yaml

DRAFT_REVISION = "0.1.0"

_REVISION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_X_KIND_RE = re.compile(r"^x-[a-z0-9][a-z0-9-]*$")


def _known_component_kinds(schema: dict[str, Any]) -> list[str]:
    kind_schema = schema["properties"]["kind"]
    for branch in kind_schema.get("anyOf", []):
        if "enum" in branch:
            return list(branch["enum"])
    return list(kind_schema.get("enum", []))


def _component_kind_is_valid(kind: str, schema: dict[str, Any]) -> bool:
    return kind in _known_component_kinds(schema) or bool(_X_KIND_RE.match(kind))


def create_component_draft(ws: Workspace, component_id: str, kind: str) -> Envelope:
    if ws.component_exists(component_id):
        return single_refusal(Codes.ALREADY_EXISTS, path=f"components['{component_id}']", message=f"a component {component_id!r} already exists")

    schema = load_schema(ws.component_schema_path)
    if not _component_kind_is_valid(kind, schema):
        known = _known_component_kinds(schema)
        return single_refusal(Codes.INVALID_ARGUMENT, path="kind", message=f"{kind!r} is not a known kind", allowed={"values": known})

    doc: dict[str, Any] = {"ocm_version": "1.1", "id": component_id, "revision": DRAFT_REVISION, "kind": kind}
    write_yaml(ws.component_path(component_id), doc)
    return Envelope.succeed(
        {"id": component_id, "revision": DRAFT_REVISION, "draft": True, "path": str(ws.component_path(component_id)), "component": doc}
    )


def update_component(ws: Workspace, component_id: str, manifest: dict[str, Any] | None = None, patch: list[dict[str, Any]] | None = None) -> Envelope:
    if (manifest is None) == (patch is None):
        return single_refusal(Codes.INVALID_ARGUMENT, path="$", message="update_component needs exactly one of `manifest` or `patch`")

    if patch is not None:
        if not ws.component_exists(component_id):
            return single_refusal(Codes.NOT_FOUND, path=f"components['{component_id}']", message=f"no component {component_id!r} to patch")
        current = read_yaml(ws.component_path(component_id)) or {}
        try:
            doc = jsonpatch.apply_patch(current, patch)
        except (jsonpatch.JsonPatchException, jsonpointer.JsonPointerException, TypeError, KeyError, IndexError) as e:
            return single_refusal(Codes.INVALID_ARGUMENT, path="$", message=f"invalid RFC-6902 patch: {e}")
    else:
        doc = dict(manifest)  # type: ignore[arg-type]

    write_yaml(ws.component_path(component_id), doc)

    schema = load_schema(ws.component_schema_path)
    errors = validate_module_dict(doc, schema)  # schema-agnostic; reused, not duplicated
    refusals = [schema_violation_to_refusal(e) for e in errors]

    if refusals:
        return Envelope.refuse(refusals)

    revision = str(doc.get("revision", "0.0.0"))
    return Envelope.succeed({"id": doc.get("id", component_id), "revision": revision, "draft": is_draft_revision(revision), "path": str(ws.component_path(component_id))})


def validate_component(ws: Workspace, component_id: str) -> Envelope:
    """Full validation including the one cross-file check schema
    validation alone can't do: does `geometry.mesh` exist, if declared
    (spec/10: "mesh: only if the file exists").
    """
    if not ws.component_exists(component_id):
        return single_refusal(Codes.NOT_FOUND, path=f"components['{component_id}']", message=f"no component {component_id!r} in this workspace")

    doc = read_yaml(ws.component_path(component_id)) or {}
    schema = load_schema(ws.component_schema_path)
    errors = validate_module_dict(doc, schema)
    refusals = [schema_violation_to_refusal(e) for e in errors]

    component_dir = ws.component_dir(component_id)
    mesh = doc.get("geometry", {}).get("mesh")
    if mesh and not (component_dir / mesh).is_file():
        refusals.append(
            Refusal(
                code=Codes.NOT_FOUND,
                path="geometry.mesh",
                message=f"{mesh!r} does not exist under {component_dir}",
                hint="Only declare geometry.mesh once the file is actually committed, or omit it.",
            )
        )

    if refusals:
        return Envelope.refuse(refusals)
    return Envelope.succeed({"id": component_id, "valid": True})


def publish_component(ws: Workspace, component_id: str, revision: str) -> Envelope:
    if not ws.component_exists(component_id):
        return single_refusal(Codes.NOT_FOUND, path=f"components['{component_id}']", message=f"no component {component_id!r} in this workspace")
    if not _REVISION_RE.match(revision):
        return single_refusal(Codes.INVALID_ARGUMENT, path="revision", message=f"{revision!r} is not a valid SemVer (X.Y.Z)")
    if is_draft_revision(revision):
        return single_refusal(
            Codes.DRAFT_NOT_PUBLISHABLE,
            path="revision",
            message=f"{revision!r} is itself a 0.x draft revision -- publishing requires a real (>=1.0.0) release",
            hint="Choose a revision whose major version is >= 1.",
        )

    validation = validate_component(ws, component_id)
    if not validation.ok:
        return validation

    doc = read_yaml(ws.component_path(component_id)) or {}
    doc["revision"] = revision
    write_yaml(ws.component_path(component_id), doc)

    return Envelope.succeed({"id": doc.get("id", component_id), "revision": revision, "draft": False, "published": True})


def list_components(ws: Workspace) -> Envelope:
    rows = []
    for component_id in ws.list_component_ids():
        data = read_yaml(ws.component_path(component_id)) or {}
        revision = str(data.get("revision", "0.0.0"))
        rows.append(
            {
                "id": data.get("id", component_id),
                "revision": revision,
                "kind": data.get("kind"),
                "vendor": data.get("vendor"),
                "name": data.get("name"),
                "draft": is_draft_revision(revision),
            }
        )
    return Envelope.succeed(rows)


def delete_component(ws: Workspace, component_id: str) -> Envelope:
    """Unconditional, like every other write here (spec/09: "writes are
    unconditional") -- a component referenced by a module is still
    deletable, same as remove_instance never blocks on a cell-level
    reference. The reference is named as a `warnings` entry, not a refusal,
    so the caller finds out what it broke without the delete itself being
    gated behind resolving that first.
    """
    if not ws.component_exists(component_id):
        return single_refusal(Codes.NOT_FOUND, path=f"components['{component_id}']", message=f"no component {component_id!r} in this workspace")

    referencing_modules = []
    for module_id in ws.list_module_ids():
        data = read_yaml(ws.module_path(module_id)) or {}
        for mc in data.get("components") or []:
            ref = mc.get("ref", "")
            ref_id, _, _ = ref.partition("@")
            if ref_id == component_id:
                referencing_modules.append(module_id)
                break

    shutil.rmtree(ws.component_dir(component_id))

    warnings = []
    if referencing_modules:
        warnings.append(
            f"{component_id} was referenced by {len(referencing_modules)} module(s) "
            f"({', '.join(sorted(referencing_modules))}); those modules will no longer resolve."
        )

    return Envelope.succeed({"id": component_id, "deleted": True}, warnings=warnings)


def describe_component(ws: Workspace, component_id: str) -> Envelope:
    """Reads whatever is on disk, valid or not -- an ADR-0014 draft is
    EXPECTED to be incomplete for a while (that's the point: the
    validation gaps are the human's completion list, not a broken state
    to hide), so describing one can't refuse just because it isn't
    publishable yet. Same pattern discovery.py's describe_cell already
    uses for an unresolvable cell: succeed with the document, name the
    gaps as `warnings`, never withhold `data` -- a caller that wants a
    hard pass/fail already has validate_component for that.
    """
    if not ws.component_exists(component_id):
        return single_refusal(Codes.NOT_FOUND, path=f"components['{component_id}']", message=f"no component {component_id!r} in this workspace")

    data = read_yaml(ws.component_path(component_id)) or {}
    schema = load_schema(ws.component_schema_path)
    errors = validate_module_dict(data, schema)
    revision = str(data.get("revision", "0.0.0"))
    payload = {"id": data.get("id", component_id), "revision": revision, "draft": is_draft_revision(revision), "component": data}

    warnings = [schema_violation_to_refusal(e).message for e in errors]
    return Envelope.succeed(payload, warnings=warnings)
