# SPDX-License-Identifier: AGPL-3.0-or-later
"""Resolve a Cell with the envelope's Refusal shape, PLUS the one rule
ocm-resolve has no way to know about: a draft module (revision 0.x --
spec/09: "excluded from cell resolution until published") must not
resolve into a cell at all. "Draft" is purely an ocm-api authoring
concept -- ocm-resolve's own `find_module` matches whatever revision was
asked for, no questions asked, which is correct for ITS job (a resolver
shouldn't have opinions about publishing workflow). This is new logic
this task calls for, so it lives here once, and every verb that resolves
a cell (`place_instance`, `set_plan`, `build_scene`, `plan_cell`, ...)
gets it for free by going through this one function.
"""

from __future__ import annotations

from ocm_core import Cell, Module
from ocm_resolve import CellResolutionError, ResolvedCell, resolve_cell

from .envelope import Codes, Refusal
from .translate import resolve_error_to_refusal
from .workspace import Workspace, is_draft_revision


def _draft_component_refusals(location: str, module: Module) -> list[Refusal]:
    """ADR-0014, same rule as _draft_refusals below but one layer down:
    ocm_resolve.find_component matches whatever revision a module's
    components: list asks for, no questions asked -- correct for ITS job.
    A draft (0.x) component being referenced at all, even by an otherwise
    published module, is new policy this task calls for, so it lives here
    once too.
    """
    refusals: list[Refusal] = []
    for mc in module.components:
        if is_draft_revision(mc.ref.revision):
            refusals.append(
                Refusal(
                    code=Codes.OCM_DRAFT_MODULE_REFERENCED,
                    path=f"modules['{location}'].components['{mc.refdes}']",
                    message=f"{location} ({module.id}) references component {mc.refdes} ({mc.ref}), a draft (0.x) -- it cannot be resolved into a cell",
                    hint=f"publish_component({mc.ref.id!r}, <semver>) first, then repoint {mc.refdes} at the published revision.",
                )
            )
    return refusals


def _draft_refusals(resolved: ResolvedCell) -> list[Refusal]:
    refusals: list[Refusal] = []
    if is_draft_revision(resolved.base.revision):
        refusals.append(
            Refusal(
                code=Codes.OCM_DRAFT_MODULE_REFERENCED,
                path="base.module",
                message=f"base module {resolved.base.id}@{resolved.base.revision} is a draft (0.x) -- it cannot be resolved into a cell",
                hint=f"publish_module({resolved.base.id!r}, <semver>) first.",
            )
        )
    refusals.extend(_draft_component_refusals("base", resolved.base))
    for name, ri in sorted(resolved.instances.items()):
        if is_draft_revision(ri.module.revision):
            refusals.append(
                Refusal(
                    code=Codes.OCM_DRAFT_MODULE_REFERENCED,
                    path=f"modules['{name}']",
                    message=f"{name} references {ri.module.id}@{ri.module.revision}, a draft (0.x) -- it cannot be resolved into a cell",
                    hint=f"publish_module({ri.module.id!r}, <semver>) first, then repoint {name} at the published revision.",
                )
            )
        refusals.extend(_draft_component_refusals(name, ri.module))
    return refusals


def resolve_with_refusals(cell: Cell, ws: Workspace) -> tuple[ResolvedCell | None, list[Refusal]]:
    try:
        resolved = resolve_cell(cell, ws.modules_dir, ws.components_dir)
    except CellResolutionError as e:
        return None, [resolve_error_to_refusal(err) for err in e.errors]

    draft_refusals = _draft_refusals(resolved)
    if draft_refusals:
        return None, draft_refusals

    return resolved, []
