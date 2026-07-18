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

from pathlib import Path
from typing import Any

from . import authoring, composition, discovery, generation
from .envelope import Envelope
from .workspace import Workspace


class OcmApi:
    def __init__(self, repo_root: str | Path):
        self.workspace = Workspace(Path(repo_root))

    # -- Discovery ---------------------------------------------------

    def describe_schema(self, section: str | None = None) -> Envelope:
        return discovery.describe_schema(self.workspace, section)

    def get_example(self, kind: str) -> Envelope:
        return discovery.get_example(self.workspace, kind)

    def list_modules(self) -> Envelope:
        return discovery.list_modules(self.workspace)

    def describe_module(self, id: str) -> Envelope:
        return discovery.describe_module(self.workspace, id)

    def list_cells(self) -> Envelope:
        return discovery.list_cells(self.workspace)

    def describe_cell(self, id: str) -> Envelope:
        return discovery.describe_cell(self.workspace, id)

    def list_frames(self, cell_id: str) -> Envelope:
        return discovery.list_frames(self.workspace, cell_id)

    # -- Module authoring ---------------------------------------------------

    def create_module_draft(self, id: str, kind: str) -> Envelope:
        return authoring.create_module_draft(self.workspace, id, kind)

    def update_module(self, id: str, manifest: dict[str, Any] | None = None, patch: list[dict[str, Any]] | None = None) -> Envelope:
        return authoring.update_module(self.workspace, id, manifest=manifest, patch=patch)

    def generate_geometry_stub(self, id: str, footprint_mm: tuple[float, float], height_mm: float, kind: str | None = None) -> Envelope:
        return authoring.generate_geometry_stub(self.workspace, id, footprint_mm, height_mm, kind=kind)

    def validate_module(self, id: str) -> Envelope:
        return authoring.validate_module(self.workspace, id)

    def publish_module(self, id: str, revision: str) -> Envelope:
        return authoring.publish_module(self.workspace, id, revision)

    # -- Cell composition ---------------------------------------------------

    def create_cell(self, id: str, base_module: str) -> Envelope:
        return composition.create_cell(self.workspace, id, base_module)

    def place_instance(self, cell: str, instance: str, module: str, mount: dict[str, Any]) -> Envelope:
        return composition.place_instance(self.workspace, cell, instance, module, mount)

    def move_instance(self, cell: str, instance: str, mount: dict[str, Any]) -> Envelope:
        return composition.move_instance(self.workspace, cell, instance, mount)

    def remove_instance(self, cell: str, instance: str) -> Envelope:
        return composition.remove_instance(self.workspace, cell, instance)

    def set_plan(self, cell: str, plan: list[Any], part: dict[str, Any] | None = None) -> Envelope:
        return composition.set_plan(self.workspace, cell, plan, part=part)

    def set_joint_state(self, cell: str, instance: str, joints: dict[str, float]) -> Envelope:
        return composition.set_joint_state(self.workspace, cell, instance, joints)

    # -- Checking & generation ---------------------------------------------------

    def build_scene(self, cell: str) -> Envelope:
        return generation.build_scene_verb(self.workspace, cell)

    def check_collision(self, cell: str, collision_margin_mm: float = 1.0) -> Envelope:
        return generation.check_collision(self.workspace, cell, collision_margin_mm=collision_margin_mm)

    def plan_cell(self, cell: str, collision_margin_mm: float = 1.0, path_samples: int = 50) -> Envelope:
        return generation.plan_cell(self.workspace, cell, collision_margin_mm=collision_margin_mm, path_samples=path_samples)

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
