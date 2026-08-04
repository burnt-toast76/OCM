# SPDX-License-Identifier: AGPL-3.0-or-later
"""OcmApi -- the one facade every client (MCP server, HTTP wrapper, and
any future CLI) calls through. spec/09 / ADR-0012: "The refusal engine
lives behind this surface and nowhere else." Every method here returns an
`Envelope`; nothing raises for an ordinary refusal (unknown module, bad
bounds, workspace overhang, ...) -- those are results, not exceptions.

This class holds no state beyond a `Workspace` (a repo path). Same repo
state + same call => same result (spec/09's determinism rule) -- there is
nothing else to hold.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any, Callable, TypeVar

from . import authoring, carriers, components, composition, discovery, generation
from .envelope import Codes, Envelope, single_refusal
from .workspace import Workspace

_F = TypeVar("_F", bound=Callable[..., Envelope])


def _never_raise(fn: _F) -> _F:
    """spec/09 design principle #1: "Refusals are results, not errors" --
    no verb may let bad input escape as a raw exception (a caller across
    an MCP/HTTP transport can't catch a Python exception anyway). Every
    verb already turns the failure modes it KNOWS about into refusals;
    this is the facade-boundary backstop for the ones it doesn't -- a
    malformed argument reaching some third-party parser (jsonpatch,
    jsonschema, ...) in a shape nothing here anticipated. Genuine
    programming bugs still show up in `message` (via `str(e)`), just as an
    OCM_INVALID_ARGUMENT refusal instead of a crash.
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Envelope:
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 -- deliberately broad, see docstring
            return single_refusal(Codes.OCM_INVALID_ARGUMENT, path="$", message=f"{type(e).__name__}: {e}")

    return wrapper  # type: ignore[return-value]


class OcmApi:
    def __init__(self, repo_root: str | Path):
        self.workspace = Workspace(Path(repo_root))

    # -- Discovery ---------------------------------------------------

    @_never_raise
    def describe_schema(self, section: str | None = None, target: str = "module") -> Envelope:
        return discovery.describe_schema(self.workspace, section, target=target)

    @_never_raise
    def get_example(self, kind: str) -> Envelope:
        return discovery.get_example(self.workspace, kind)

    @_never_raise
    def list_modules(self) -> Envelope:
        return discovery.list_modules(self.workspace)

    @_never_raise
    def describe_module(self, id: str) -> Envelope:
        return discovery.describe_module(self.workspace, id)

    @_never_raise
    def list_cells(self) -> Envelope:
        return discovery.list_cells(self.workspace)

    @_never_raise
    def describe_cell(self, id: str) -> Envelope:
        return discovery.describe_cell(self.workspace, id)

    @_never_raise
    def list_frames(self, cell_id: str) -> Envelope:
        return discovery.list_frames(self.workspace, cell_id)

    # -- Module authoring ---------------------------------------------------

    @_never_raise
    def create_module_draft(self, id: str, kind: str) -> Envelope:
        return authoring.create_module_draft(self.workspace, id, kind)

    @_never_raise
    def update_module(self, id: str, manifest: dict[str, Any] | None = None, patch: list[dict[str, Any]] | None = None) -> Envelope:
        return authoring.update_module(self.workspace, id, manifest=manifest, patch=patch)

    @_never_raise
    def generate_geometry_stub(self, id: str, footprint_mm: tuple[float, float], height_mm: float, kind: str | None = None) -> Envelope:
        return authoring.generate_geometry_stub(self.workspace, id, footprint_mm, height_mm, kind=kind)

    @_never_raise
    def validate_module(self, id: str) -> Envelope:
        return authoring.validate_module(self.workspace, id)

    @_never_raise
    def publish_module(self, id: str, revision: str) -> Envelope:
        return authoring.publish_module(self.workspace, id, revision)

    # -- Component authoring (ADR-0014) ---------------------------------------------------

    @_never_raise
    def create_component_draft(self, id: str, kind: str) -> Envelope:
        return components.create_component_draft(self.workspace, id, kind)

    @_never_raise
    def update_component(self, id: str, manifest: dict[str, Any] | None = None, patch: list[dict[str, Any]] | None = None) -> Envelope:
        return components.update_component(self.workspace, id, manifest=manifest, patch=patch)

    @_never_raise
    def validate_component(self, id: str) -> Envelope:
        return components.validate_component(self.workspace, id)

    @_never_raise
    def publish_component(self, id: str, revision: str) -> Envelope:
        return components.publish_component(self.workspace, id, revision)

    # -- Carrier types (ADR-0031) ---------------------------------------------------------

    @_never_raise
    def validate_carrier(self, id: str) -> Envelope:
        return carriers.validate_carrier(self.workspace, id)

    @_never_raise
    def list_components(self) -> Envelope:
        return components.list_components(self.workspace)

    @_never_raise
    def describe_component(self, id: str) -> Envelope:
        return components.describe_component(self.workspace, id)

    @_never_raise
    def delete_component(self, id: str) -> Envelope:
        return components.delete_component(self.workspace, id)

    # -- Cell composition ---------------------------------------------------

    @_never_raise
    def create_cell(self, id: str, base_module: str) -> Envelope:
        return composition.create_cell(self.workspace, id, base_module)

    @_never_raise
    def place_instance(
        self,
        cell: str,
        instance: str,
        module: str,
        mount: dict[str, Any],
        requires: dict[str, str] | None = None,
    ) -> Envelope:
        # ADR-0023 Decision 4: a module may declare abstract `requires:`; the
        # cell binds each to a concrete `instance.signal`. This is where a cell
        # composed through the API expresses that binding -- without it, an
        # instance carrying a requires-capable capability (e.g. sd50's
        # drive_screw) would resolve straight to OCM_REQUIREMENT_UNBOUND.
        return composition.place_instance(self.workspace, cell, instance, module, mount, requires=requires)

    @_never_raise
    def move_instance(self, cell: str, instance: str, mount: dict[str, Any]) -> Envelope:
        return composition.move_instance(self.workspace, cell, instance, mount)

    @_never_raise
    def remove_instance(self, cell: str, instance: str) -> Envelope:
        return composition.remove_instance(self.workspace, cell, instance)

    @_never_raise
    def set_plan(self, cell: str, plan: list[Any], part: dict[str, Any] | None = None) -> Envelope:
        return composition.set_plan(self.workspace, cell, plan, part=part)

    @_never_raise
    def set_joint_state(self, cell: str, instance: str, joints: dict[str, float]) -> Envelope:
        return composition.set_joint_state(self.workspace, cell, instance, joints)

    # -- Checking & generation ---------------------------------------------------

    @_never_raise
    def build_scene(self, cell: str) -> Envelope:
        return generation.build_scene_verb(self.workspace, cell)

    @_never_raise
    def check_collision(self, cell: str, collision_margin_mm: float = 1.0) -> Envelope:
        return generation.check_collision(self.workspace, cell, collision_margin_mm=collision_margin_mm)

    @_never_raise
    def plan_cell(self, cell: str, collision_margin_mm: float = 1.0, path_samples: int = 50) -> Envelope:
        return generation.plan_cell(self.workspace, cell, collision_margin_mm=collision_margin_mm, path_samples=path_samples)

    @_never_raise
    def emit(
        self,
        cell: str,
        urscript: str | None = None,
        animation: str | None = None,
        view: str | None = None,
        collision_margin_mm: float = 1.0,
        path_samples: int = 50,
    ) -> Envelope:
        return generation.emit(
            self.workspace,
            cell,
            urscript=urscript,
            animation=animation,
            view=view,
            collision_margin_mm=collision_margin_mm,
            path_samples=path_samples,
        )
