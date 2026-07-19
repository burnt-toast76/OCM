# SPDX-License-Identifier: AGPL-3.0-or-later
"""Locate module manifests on disk by (id, revision) ref.

Convention: a ref `id@revision` is looked up as `<search-root>/<id>/module.yaml`,
matching the layout already used under `modules/` in this repo. The manifest's
own declared id/revision must match the ref exactly -- a mismatch is treated
as "not found" (see ocm_core's ModuleRef), not a silent substitution.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from ocm_core import Component, Module, ModuleRef, load_component, load_module
from ocm_core.errors import ManifestValidationError
from ocm_core.module import ComponentRef

SearchPath = Union[Path, str, Sequence[Union[Path, str]]]


def _as_roots(search_path: SearchPath) -> tuple[Path, ...]:
    if isinstance(search_path, (str, Path)):
        return (Path(search_path),)
    return tuple(Path(p) for p in search_path)


def find_module(ref: ModuleRef, search_path: SearchPath) -> tuple[Module | None, list[str]]:
    """Look up `ref` under each root of `search_path`.

    Returns (module, errors): `module` is None if it could not be resolved,
    in which case `errors` explains why (not found anywhere it was looked
    for, found but schema-invalid, or found but declaring a different
    id/revision than requested).
    """
    errors: list[str] = []
    roots = _as_roots(search_path)
    tried: list[Path] = []

    for root in roots:
        candidate = root / ref.id / "module.yaml"
        tried.append(candidate)
        if not candidate.is_file():
            continue

        try:
            module = load_module(candidate)
        except ManifestValidationError as e:
            errors.append(f"{ref}: found {candidate} but it failed manifest validation: {e}")
            return None, errors

        if module.id != ref.id or module.revision != ref.revision:
            errors.append(
                f"{ref}: found {candidate} but it declares "
                f"{module.id}@{module.revision}, not {ref}"
            )
            return None, errors

        return module, errors

    tried_str = ", ".join(str(p) for p in tried)
    errors.append(f"{ref}: module not found (looked in: {tried_str})")
    return None, errors


def find_component(ref: ComponentRef, search_path: SearchPath) -> tuple[Component | None, list[str]]:
    """Look up `ref` under each root of `search_path` -- ADR-0014's
    `components/<id>/component.yaml` layout, mirroring find_module exactly.

    Returns (component, errors): `component` is None if it could not be
    resolved, in which case `errors` explains why (not found anywhere it
    was looked for, found but schema-invalid, or found but declaring a
    different id/revision than requested).
    """
    errors: list[str] = []
    roots = _as_roots(search_path)
    tried: list[Path] = []

    for root in roots:
        candidate = root / ref.id / "component.yaml"
        tried.append(candidate)
        if not candidate.is_file():
            continue

        try:
            component = load_component(candidate)
        except ManifestValidationError as e:
            errors.append(f"{ref}: found {candidate} but it failed component validation: {e}")
            return None, errors

        if component.id != ref.id or component.revision != ref.revision:
            errors.append(
                f"{ref}: found {candidate} but it declares "
                f"{component.id}@{component.revision}, not {ref}"
            )
            return None, errors

        return component, errors

    tried_str = ", ".join(str(p) for p in tried)
    errors.append(f"{ref}: component not found (looked in: {tried_str})")
    return None, errors
