# SPDX-License-Identifier: AGPL-3.0-or-later
"""Resolves and scene-builds the real, checked-in bracket-asm-01 cell
against the real modules/ directory.

Every module the cell references now has real collision geometry: the six
non-robot modules got a box primitive derived from mechanical.mount.
footprint_mm plus a height already present elsewhere in the manifest (a tcp/
pick/part_datum frame, or a documented estimate where none exists), and
com.universal-robots.ur5e got a real per-link mesh + kinematic chain
vendored and flattened from Universal_Robots_ROS2_Description (BSD-3-Clause;
see that module's NOTICE.md). None of this is real CAD -- the six box
primitives are explicitly placeholders -- but it's real enough for the
generator to actually assemble a connected, collision-checkable Tesseract
scene end-to-end, which is the point of this test.
"""

from __future__ import annotations

from pathlib import Path

from ocm_core import load_cell
from ocm_generator.scene import Scene, build_scene
from ocm_resolve import resolve_cell


def _link_names(scene: Scene) -> set[str]:
    sg = scene.environment.getSceneGraph()
    links = sg.getLinks()
    return {links[i].getName() for i in range(len(links))}


def test_real_bracket_cell_scene_builds_end_to_end(repo_root: Path):
    cell = load_cell(repo_root / "cells" / "bracket-asm-01" / "cell.yaml")
    resolved = resolve_cell(cell, repo_root / "modules")

    scene = build_scene(resolved, repo_root / "modules")

    assert isinstance(scene, Scene)
    assert set(scene.instances) == {"robot1", "sd1", "feed1", "nest1", "cam1"}


def test_real_bracket_cell_sd1_is_kinematically_parented_to_the_real_ur5e_flange(repo_root: Path):
    cell = load_cell(repo_root / "cells" / "bracket-asm-01" / "cell.yaml")
    resolved = resolve_cell(cell, repo_root / "modules")

    scene = build_scene(resolved, repo_root / "modules")

    # "robot1__flange" only exists because it's a real link in the vendored
    # UR5e URDF (see NOTICE.md) -- not something ocm_generator invented.
    assert scene.instance("sd1").parent_link == "robot1__flange"
    assert "robot1__flange" in _link_names(scene)


def test_real_bracket_cell_base_grid_instances_attach_to_world(repo_root: Path):
    cell = load_cell(repo_root / "cells" / "bracket-asm-01" / "cell.yaml")
    resolved = resolve_cell(cell, repo_root / "modules")

    scene = build_scene(resolved, repo_root / "modules")

    assert scene.base.parent_link == "world"
    for name in ("robot1", "feed1", "nest1", "cam1"):
        assert scene.instance(name).parent_link == "world"
